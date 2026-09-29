"""Persist a period inventory from one exact frozen model calculation."""
from __future__ import annotations

from math import isclose
from sqlalchemy import select

from ..analysis.organization_period import build_organization_period
from ..database import Database
from ..errors import DomainError
from ..hashing import canonical_json_sha256
from ..models import Application, SystemRevision, new_id
from ..runtime_models import OrganizationPeriodInventory, Period, SolvedSystemSnapshot
from ..runtime_schemas import OrganizationPeriodCreate
from .native_climate import NativeClimateArtifactService
from .runtime_support import require_method_package


def _out(record: OrganizationPeriodInventory) -> dict:
    return {"id": record.id, "application_id": record.application_id,
            "system_revision_id": record.system_revision_id,
            "solved_snapshot_id": record.solved_snapshot_id, "period_id": record.period_id,
            "request_sha256": record.request_sha256, "result": record.result_json,
            "content_sha256": record.content_sha256, "created_at": record.created_at}


class OrganizationPeriodService:
    def __init__(self, database: Database):
        self.database = database
        self.native = NativeClimateArtifactService(database)

    def create(self, application_id: str, payload: OrganizationPeriodCreate) -> dict:
        inputs = payload.model_dump(mode="json")
        request_hash = canonical_json_sha256(inputs)
        with self.database.session() as db:
            application = db.get(Application, application_id)
            snapshot = db.get(SolvedSystemSnapshot, payload.solved_snapshot_id)
            period = db.get(Period, payload.reporting_period_id)
            if application is None or snapshot is None or snapshot.application_id != application_id:
                raise DomainError(code="ORGANIZATION_PERIOD_SOURCE_NOT_FOUND", message="application or solved snapshot is absent", status_code=404)
            if period is None or period.application_id != application_id:
                raise DomainError(code="ORGANIZATION_PERIOD_NOT_FOUND", message="reporting period does not belong to this application", status_code=404)
            revision = db.get(SystemRevision, snapshot.system_revision_id)
            if revision is None:
                raise DomainError(code="ORGANIZATION_PERIOD_REVISION_NOT_FOUND", message="source revision is absent", status_code=409)
            if payload.method_package_ref not in ((application.context or {}).get("method_package_refs") or []):
                raise DomainError(code="ORGANIZATION_PERIOD_METHOD_NOT_BOUND", message="method is not bound to this application", status_code=409)
            method = require_method_package(db, payload.method_package_ref)
            if method.package_kind != "organization_period_inventory":
                raise DomainError(code="ORGANIZATION_PERIOD_METHOD_KIND_INVALID", message="method has another package kind", status_code=422)
            existing = db.scalar(select(OrganizationPeriodInventory).where(
                OrganizationPeriodInventory.application_id == application_id,
                OrganizationPeriodInventory.request_sha256 == request_hash))
            if existing is not None:
                return _out(existing)
            basis = (snapshot.provider_receipt or {}).get("calculation_basis") or {}
            demand = basis.get("demand") or []
            if len(demand) != 1 or demand[0].get("unit") != "kg":
                raise DomainError(code="ORGANIZATION_PERIOD_PRODUCT_BASIS_INVALID", message="source solve must have one kilogram product demand", status_code=422)
            mapped_ids = [item.get("consumer_exchange_id") for item in basis.get("mapped_background_process_pins") or []]
            if not mapped_ids or any(not item for item in mapped_ids):
                raise DomainError(code="ORGANIZATION_PERIOD_BACKGROUND_MISSING", message="source solve lacks exact purchased-energy background pins", status_code=422)
            _, _, answer, request = self.native._frozen_answer(snapshot.id)
            if answer.merge_status != "merged":
                raise DomainError(code="ORGANIZATION_PERIOD_CLIMATE_UNMERGED", message="native climate domains cannot be combined", status_code=422)
            if answer.unified_climate_total is None or not isclose(
                answer.unified_climate_total,
                sum(item.contribution_value for item in answer.domains.values()),
                rel_tol=1e-9, abs_tol=1e-12,
            ):
                raise DomainError(code="ORGANIZATION_PERIOD_CLIMATE_INCONSISTENT", message="native climate domains differ from their merged total", status_code=422)
            result = build_organization_period(
                application_id=application_id, revision_id=revision.id,
                snapshot_id=snapshot.id, snapshot_hash=snapshot.content_sha256,
                period={"id": period.id, "key": period.key, "name": period.name,
                        "start_date": period.start_date.isoformat(), "end_date": period.end_date.isoformat()},
                facility=payload.facility, controlled_process_ids=payload.controlled_process_ids,
                model_process_ids=[str(node["id"]) for node in revision.graph_snapshot.get("nodes", [])],
                baseline_output=float(demand[0]["amount"]), period_output=payload.period_product_output,
                output_unit="kg", foreground_value=answer.domains["foreground"].contribution_value,
                background_value=answer.domains["native_background"].contribution_value,
                climate_unit=answer.indicator.unit,
                native_method={"id": request.method_package_id, "version": request.method_package_version,
                               "content_sha256": request.method_package_sha256,
                               "runtime_manifest_sha256": request.runtime_manifest_sha256},
                method_ref=payload.method_package_ref, method_hash=method.content_sha256,
                manifest=method.manifest, mapped_exchange_ids=mapped_ids,
                unmodelled_inputs={item["exchange_id"]: item for item in snapshot.scaled_technosphere_exchanges
                                   if item.get("direction") == "input" and item.get("counterparty_process_id") is None},
                scope3_activities=[item.model_dump(mode="json") for item in payload.scope3_activities],
                category_statuses=payload.category_statuses,
            )
            record = OrganizationPeriodInventory(
                id=new_id(), application_id=application_id, system_revision_id=revision.id,
                solved_snapshot_id=snapshot.id, period_id=period.id, request_sha256=request_hash,
                inputs_json=inputs, result_json=result, content_sha256=result["content_sha256"],
            )
            db.add(record)
            db.commit()
            return _out(record)

    def list(self, application_id: str) -> list[dict]:
        with self.database.session() as db:
            return [_out(item) for item in db.scalars(select(OrganizationPeriodInventory).where(
                OrganizationPeriodInventory.application_id == application_id).order_by(
                    OrganizationPeriodInventory.created_at))
                    if item.result_json.get("schema_version") == "nebula_one.organization-period.v1"]

    def get(self, application_id: str, record_id: str) -> dict:
        with self.database.session() as db:
            record = db.get(OrganizationPeriodInventory, record_id)
            if (record is None or record.application_id != application_id
                    or record.result_json.get("schema_version") != "nebula_one.organization-period.v1"):
                raise DomainError(code="ORGANIZATION_PERIOD_RESULT_NOT_FOUND", message="period inventory not found", status_code=404)
            return _out(record)
