"""Persist one Nebula authored organization lifecycle carbon calculation."""
from __future__ import annotations

from math import isclose

from sqlalchemy import select

from ..analysis.organization_lifecycle import build_organization_lifecycle
from ..database import Database
from ..errors import DomainError
from ..hashing import canonical_json_sha256
from ..models import Application, SystemRevision, new_id
from ..runtime_models import OrganizationPeriodInventory, Period, SolvedSystemSnapshot
from ..runtime_schemas import OrganizationLifecycleCreate
from .native_climate import NativeClimateArtifactService
from .organization_project_supply import project_supply_climate
from .runtime_support import require_method_package


class OrganizationLifecycleService:
    RESULT_SCHEMAS = {"nebula_one.organization-lifecycle-carbon.v1", "nebula_one.organization-lifecycle-carbon.v2"}

    def __init__(self, database: Database) -> None:
        self.database = database
        self.native = NativeClimateArtifactService(database)

    def create(self, application_id: str, payload: OrganizationLifecycleCreate) -> dict:
        inputs = payload.model_dump(mode="json")
        request_hash = canonical_json_sha256(inputs)
        with self.database.session() as db:
            app = db.get(Application, application_id)
            snapshot = db.get(SolvedSystemSnapshot, payload.solved_snapshot_id)
            period = db.get(Period, payload.reporting_period_id)
            if app is None or snapshot is None or snapshot.application_id != application_id:
                raise DomainError(code="ORGANIZATION_LIFECYCLE_SOURCE_NOT_FOUND", message="application or frozen snapshot is absent", status_code=404)
            if period is None or period.application_id != application_id:
                raise DomainError(code="ORGANIZATION_LIFECYCLE_PERIOD_NOT_FOUND", message="period is absent", status_code=404)
            revision = db.get(SystemRevision, snapshot.system_revision_id)
            if revision is None:
                raise DomainError(code="ORGANIZATION_LIFECYCLE_REVISION_NOT_FOUND", message="source revision is absent", status_code=409)
            if payload.method_package_ref not in ((app.context or {}).get("method_package_refs") or []):
                raise DomainError(code="ORGANIZATION_LIFECYCLE_METHOD_NOT_BOUND", message="method is not bound to this project", status_code=409)
            method = require_method_package(db, payload.method_package_ref)
            if method.package_kind != "organization_lifecycle_carbon":
                raise DomainError(code="ORGANIZATION_LIFECYCLE_METHOD_KIND_INVALID", message="method has another kind", status_code=422)
            existing = db.scalar(select(OrganizationPeriodInventory).where(
                OrganizationPeriodInventory.application_id == application_id,
                OrganizationPeriodInventory.request_sha256 == request_hash))
            if existing is not None:
                return self._out(existing)
            basis = (snapshot.provider_receipt or {}).get("calculation_basis") or {}
            demand = basis.get("demand") or []
            if len(demand) != 1 or demand[0].get("unit") != "kg":
                raise DomainError(code="ORGANIZATION_LIFECYCLE_PRODUCT_INVALID", message="source solve must have one kilogram product demand", status_code=422)
            climate_source = None
            if (method.manifest.get("classification_rules") or {}).get("energy_path_source") in {
                    "project_background_process_receipts", "optional_project_background_process_receipts"}:
                foreground_value, background_value, climate_unit, climate_method, climate_source, mapped = (
                    project_supply_climate(snapshot, revision, method.manifest))
            else:
                mapped = [item.get("consumer_exchange_id") for item in basis.get("mapped_background_process_pins") or []]
                if not mapped or any(not item for item in mapped):
                    raise DomainError(code="ORGANIZATION_LIFECYCLE_BACKGROUND_MISSING", message="source solve lacks exact energy background pins", status_code=422)
                _, _, answer, request = self.native._frozen_answer(snapshot.id)
                if (answer.merge_status != "merged" or answer.unified_climate_total is None
                        or not isclose(answer.unified_climate_total,
                                       sum(item.contribution_value for item in answer.domains.values()),
                                       rel_tol=1e-9, abs_tol=1e-12)):
                    raise DomainError(code="ORGANIZATION_LIFECYCLE_CLIMATE_UNMERGED", message="native climate domains do not reconcile", status_code=422)
                foreground_value = answer.domains["foreground"].contribution_value
                background_value = answer.domains["native_background"].contribution_value
                climate_unit = answer.indicator.unit
                climate_method = {"id": request.method_package_id, "version": request.method_package_version,
                                  "content_sha256": request.method_package_sha256,
                                  "runtime_manifest_sha256": request.runtime_manifest_sha256}
            internal_exchange_ids: set[str] = set()
            for edge in revision.graph_snapshot.get("exchanges", []):
                if edge.get("fromNode") and edge.get("toNode"):
                    if not edge.get("sourcePortId") or not edge.get("targetPortId"):
                        raise DomainError(code="ORGANIZATION_LIFECYCLE_INTERNAL_LINK_UNRESOLVED", message="an internal model link lacks exact port identities", status_code=422)
                    internal_exchange_ids.add(f"{edge['fromNode']}::{edge['sourcePortId']}")
                    internal_exchange_ids.add(f"{edge['toNode']}::{edge['targetPortId']}")
            if any(exchange_id in internal_exchange_ids for exchange_id in mapped):
                raise DomainError(code="ORGANIZATION_LIFECYCLE_INTERNAL_ENERGY_PATH", message="a mapped energy path is an internal product link", status_code=422)
            factor_hashes = {}
            for activity in payload.other_activities:
                if not activity.factor_package_ref:
                    continue
                factor_package = require_method_package(db, activity.factor_package_ref)
                factor = (factor_package.manifest or {}).get("factor") or {}
                source = next((item for item in snapshot.scaled_technosphere_exchanges
                               if item.get("exchange_id") == activity.consumer_exchange_id), None)
                evidence = factor.get("evidence") or {}
                climate_method = factor.get("climate_method") or {}
                if (factor_package.package_kind != "organization_lifecycle_factor"
                        or factor_package.valid_from is None or factor_package.valid_to is None
                        or factor_package.valid_from > period.start_date or factor_package.valid_to < period.end_date
                        or source is None or factor.get("consumer_exchange_id") != activity.consumer_exchange_id
                        or factor.get("reference_flow_uuid") != source.get("flow_uuid")
                        or factor.get("value") != activity.factor_value
                        or factor.get("unit") != activity.factor_unit
                        or factor.get("boundary") != activity.factor_boundary
                        or factor.get("evidence_role") != activity.evidence_role
                        or evidence.get("source") != activity.factor_source
                        or evidence.get("sha256") != activity.evidence_sha256
                        or factor_package.version != activity.factor_version
                        or climate_method.get("id") != activity.factor_method_id
                        or climate_method.get("version") != activity.factor_method_version
                        or climate_method.get("content_sha256") != activity.factor_method_sha256
                        or factor.get("reference_flow_uuid") != activity.factor_reference_product):
                    raise DomainError(code="ORGANIZATION_LIFECYCLE_FACTOR_PACKAGE_MISMATCH", message="registered factor package does not match the activity, period or pinned method", status_code=422)
                factor_hashes[activity.activity_id] = factor_package.content_sha256
            result = build_organization_lifecycle(
                application_id=application_id, revision_id=revision.id,
                snapshot_id=snapshot.id, snapshot_hash=snapshot.content_sha256,
                period={"id": period.id, "name": period.name,
                        "start_date": period.start_date.isoformat(), "end_date": period.end_date.isoformat()},
                facility=payload.facility, controlled_process_ids=payload.controlled_process_ids,
                model_process_ids=[str(node["id"]) for node in revision.graph_snapshot.get("nodes", [])],
                input_basis=payload.input_basis, baseline_output=float(demand[0]["amount"]),
                period_output=payload.period_product_output,
                foreground_value=foreground_value,
                background_value=background_value,
                climate_unit=climate_unit, native_method=climate_method,
                method_ref=payload.method_package_ref, method_hash=method.content_sha256,
                manifest=method.manifest, mapped_exchange_ids=mapped,
                external_exchanges={item["exchange_id"]: item for item in snapshot.scaled_technosphere_exchanges
                                    if item.get("counterparty_process_id") is None
                                    and item["exchange_id"] not in internal_exchange_ids},
                activities=[{**item.model_dump(mode="json"),
                             **({"factor_package_sha256": factor_hashes[item.activity_id]}
                                if item.activity_id in factor_hashes else {})}
                            for item in payload.other_activities], climate_source=climate_source,
            )
            record = OrganizationPeriodInventory(id=new_id(), application_id=application_id,
                system_revision_id=revision.id, solved_snapshot_id=snapshot.id,
                period_id=period.id, request_sha256=request_hash, inputs_json=inputs,
                result_json=result, content_sha256=result["content_sha256"])
            db.add(record)
            db.commit()
            return self._out(record)

    @staticmethod
    def _out(record: OrganizationPeriodInventory) -> dict:
        return {"id": record.id, "application_id": record.application_id,
                "solved_snapshot_id": record.solved_snapshot_id, "result": record.result_json,
                "content_sha256": record.content_sha256, "created_at": record.created_at}

    def list(self, application_id: str) -> list[dict]:
        with self.database.session() as db:
            records = db.scalars(select(OrganizationPeriodInventory).where(
                OrganizationPeriodInventory.application_id == application_id).order_by(
                    OrganizationPeriodInventory.created_at.desc())).all()
            return [self._out(item) for item in records if item.result_json.get("schema_version") in self.RESULT_SCHEMAS]

    def get(self, application_id: str, record_id: str) -> dict:
        with self.database.session() as db:
            record = db.get(OrganizationPeriodInventory, record_id)
            if (record is None or record.application_id != application_id
                    or record.result_json.get("schema_version") not in self.RESULT_SCHEMAS):
                raise DomainError(code="ORGANIZATION_LIFECYCLE_RESULT_NOT_FOUND", message="result not found", status_code=404)
            return self._out(record)
