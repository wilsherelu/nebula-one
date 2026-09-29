from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..adapters.nebula_lca import NebulaLCAClient
from ..analysis.mfa import project_declared_mfa
from ..database import Database
from ..errors import DomainError
from ..hashing import canonical_json_sha256
from ..models import AnalysisRun, Application, OutboxEvent, SystemModel, SystemRevision
from ..runtime_schemas import ProviderBackgroundProcessPin, ProviderProjectBackgroundPin
from ..mapped_background_schemas import ProviderMappedBackgroundProcessPin
from ..schemas import AnalysisRunCreate
from .model_processing_runtime import flow_selection_of, resolve_purpose_derivation
from .run_idempotency import build_run_identity
from .outbox import OutboxService, enqueue_outbox_event


ANALYSIS_EXECUTE_TOPIC = "analysis.execute.v1"


@dataclass(slots=True)
class AnalysisExecutionContext:
    graph: dict[str, Any]
    upstream_project_id: str
    upstream_version: int
    base_graph_sha256: str
    provider_snapshot_ref: dict[str, Any] | None
    graph_sha256: str
    system_revision_hash: str | None


CAPABILITIES: tuple[dict[str, Any], ...] = (
    {
        "key": "mfa.declared.v1",
        "name": "Declared-flow MFA",
        "execution": "nebula_one",
        "basis": "nebula_lca_graph_declared_amounts",
        "limits": [
            "no solved-activity scaling",
            "no reference-unit conversion",
            "no unequal dual-quantity conversion",
        ],
    },
    {
        "key": "lcia.nebula.v1",
        "name": "Nebula LCA LCIA",
        "execution": "nebula_lca",
        "basis": "POST /api/model/run",
        "limits": ["method and data availability are owned by Nebula LCA"],
    },
    {
        "key": "solve.nebula.v1",
        "name": "Nebula LCA solved system",
        "execution": "nebula_lca_provider",
        "basis": "POST /api/provider/v1/solve",
        "limits": [
            "requires an explicit demand vector",
            "requires the provider activity-vector and scaled-exchange contract",
        ],
    },
    {
        "key": "mfa.solved.v1",
        "name": "Solved-system MFA and Sankey",
        "execution": "nebula_one_snapshot",
        "analysis_run": False,
        "basis": "provider activity vector and scaled exchanges",
        "limits": [
            "process balances are application projections",
            "provider residuals and contribution graph remain authoritative-engine gaps",
        ],
    },
    {
        "key": "energy.carrier.solved.v1",
        "name": "Solved energy-carrier series",
        "execution": "nebula_one_snapshot",
        "analysis_run": False,
        "basis": "provider scaled exchanges and quantity-conversion receipts",
        "limits": [
            "does not claim a complete energy balance",
            "unit identity and LHV/HHV or material-condition bases remain separate series",
            "converted quantities require an exact same-snapshot conversion receipt",
        ],
    },
    {
        "key": "energy.flow.solved.v1",
        "name": "Explicit solved energy conversion flow",
        "execution": "nebula_one_snapshot",
        "analysis_run": False,
        "basis": "energy.carrier.solved.v1 plus explicit solved internal and loss exchanges",
        "limits": [
            "requires explicit conversion Process and MJ exchange pairs",
            "requires an explicit positive loss output; no loss is inferred",
            "audits declared energy conversion only and does not replace the provider solver",
        ],
    },
    {
        "key": "water.balance.solved.v1",
        "name": "Explicit solved water balance",
        "execution": "nebula_one_snapshot",
        "analysis_run": False,
        "basis": "exact versioned water Flow identities and solved exchanges",
        "limits": [
            "requires explicit withdrawal, wastewater, reuse, discharge and consumptive-output bindings",
            "does not infer water roles, losses, conversions, quality or scarcity impacts",
            "mass and volume series remain separate without an explicit conversion receipt",
        ],
    },
    {
        "key": "energy.scenario-comparison.v1",
        "name": "Frozen energy-scenario comparison",
        "execution": "nebula_one_snapshot",
        "analysis_run": False,
        "basis": "comparable energy.carrier.solved.v1 series from sibling frozen revisions",
        "limits": [
            "requires two to five frozen scenarios from one base revision",
            "runtime comparison requires one exact application reporting period",
            "exact unit and energy-basis identities must match across scenarios",
            "does not aggregate unlike series or claim a complete energy balance",
        ],
    },
    {
        "key": "energy.period-trend.v1",
        "name": "Multi-period energy intensity trend",
        "execution": "nebula_one_snapshot",
        "analysis_run": False,
        "basis": "explicit period-to-energy-result observations",
        "limits": [
            "compares functional-unit intensity and does not infer period totals",
            "requires one application, system model, functional unit and resolution",
            "exact unit, energy-basis and carrier Flow identities must match",
            "reporting periods must be unique and non-overlapping",
        ],
    },
    {
        "key": "energy.period-total.v1",
        "name": "Evidence-scaled reporting-period energy totals",
        "execution": "nebula_one_snapshot",
        "analysis_run": False,
        "basis": "solved energy intensity and frozen period product-output inventory",
        "limits": [
            "requires one approved period_product_output data point per reporting period",
            "requires exact functional-output Flow and unit identity",
            "does not infer production, convert units or claim a complete site energy balance",
        ],
    },
    {
        "key": "electricity.province-scenario.v1",
        "name": "Province electricity location-based CO2 scenarios",
        "execution": "nebula_one_snapshot",
        "analysis_run": False,
        "basis": "frozen period electricity activity and versioned official province factors",
        "limits": [
            "uses exact TIDAS electricity and UnitGroup identities",
            "is a location-based indirect CO2 reference calculation, not EF 3.1 LCIA",
            "does not re-solve the model or constitute a complete Scope 2 statement",
        ],
    },
    {
        "key": "ghg.inventory.trial.v1",
        "name": "Partial organization GHG inventory trial",
        "execution": "nebula_one_snapshot",
        "analysis_run": False,
        "basis": "exact direct EF 3.1 contributions plus a frozen province electricity reference",
        "limits": [
            "Scope 1 covers only exact direct contributions in the frozen model boundary",
            "Scope 2 is a location-based electricity CO2 reference and not a complete Scope 2 statement",
            "Scope 3 remains uncalculated without frozen value-chain classification evidence",
            "unlike result units and semantics are never combined into an inventory total",
        ],
    },
    {
        "key": "organization.ghg-inventory.v1",
        "name": "Organization GHG inventory from bound solved systems",
        "execution": "nebula_one_snapshot",
        "analysis_run": False,
        "basis": "exact SystemBinding revision/snapshot chains and versioned role classification",
        "limits": [
            "requires complete Scope 1, Scope 2 and Scope 3 role coverage",
            "requires exact period, boundary, LCIA method, unit and database release comparability",
            "does not infer emission factors or replace source PCF evidence",
        ],
    },
    {
        "key": "pcf.product.v1",
        "name": "Product carbon footprint from a solved snapshot",
        "execution": "nebula_one_snapshot",
        "analysis_run": False,
        "basis": "versioned MethodPackage and provider LCIA result",
        "limits": [
            "current claim scope is foreground boundary only",
            "does not create a complete or certified product declaration",
            "requires exact elementary Flow receipts",
        ],
    },
    {
        "key": "cbam.trial.v1",
        "name": "CBAM direct-only embedded-emissions trial",
        "execution": "nebula_one_snapshot",
        "analysis_run": False,
        "basis": "versioned EU rule package, provider activity vector and exact solved exchanges",
        "limits": [
            "current gold standard covers actual direct emissions for a simple hydrogen good only",
            "requires a complete calendar-year period from 2026 and exact TIDAS/elementary Flow receipts",
            "does not calculate certificates, carbon-price deductions, free-allocation adjustments or a declaration",
        ],
    },
    {
        "key": "cbam.complex-trial.v1",
        "name": "CBAM one-level precursor direct-component trial",
        "execution": "nebula_one_snapshot",
        "analysis_run": False,
        "basis": "versioned EU rule package, solved precursor result and exact scaled exchanges",
        "limits": [
            "current gold standard covers one solved simple-goods precursor only",
            "calculates the direct component of Equation 62 and excludes indirect emissions",
            "does not calculate defaults, verification, certificates or a declaration",
        ],
    },
    {
        "key": "spatial.aggregate.v1",
        "name": "Frozen park spatial aggregation",
        "execution": "nebula_one_snapshot",
        "analysis_run": False,
        "basis": "facility bindings and solved-system MFA",
        "limits": [
            "requires a frozen park boundary and exact facility Process bindings",
            "geometry is identity evidence and does not participate in solving",
        ],
    },
    {
        "key": "spatial.energy.v1",
        "name": "Facility-attributed external energy inputs",
        "execution": "nebula_one_snapshot",
        "analysis_run": False,
        "basis": "energy carrier entries joined to frozen facility Process bindings",
        "limits": [
            "attributes solved external inputs only",
            "does not infer internal conversion, losses or downstream allocation",
            "requires an exact same-snapshot energy result and park spatial aggregate",
        ],
    },
    {
        "key": "spatial.energy-flow.v1",
        "name": "Facility-attributed explicit energy flow",
        "execution": "nebula_one_snapshot",
        "analysis_run": False,
        "basis": "energy.flow.solved.v1 joined to frozen facility Process bindings",
        "limits": [
            "requires explicit conversion, useful-energy and loss exchanges",
            "requires every energy-flow Process to resolve to exactly one facility",
            "does not infer conversion, losses, downstream allocation or geometry effects",
        ],
    },
    {
        "key": "spatial.distribution.v1",
        "name": "Frozen supply spatial distribution",
        "execution": "nebula_one_snapshot",
        "analysis_run": False,
        "basis": "solved boundary Flow and versioned spatial allocation package",
        "limits": [
            "current regions use demonstration representative points",
            "declared shares are attribution scenarios, not measured supply data",
            "source-origin changes do not alter the solved model or LCIA",
        ],
    },
)


_ELEMENTARY_REF_FIELDS = (
    "exchange_id",
    "source_namespace",
    "flow_uuid",
    "version",
    "flow_property_uuid",
    "flow_property_version",
    "unit_group_uuid",
    "unit_group_version",
    "unit",
    "direction",
    "compartment",
)


def _provider_elementary_flow_refs(
    graph: dict[str, Any], *, reviewed_excluded_exchange_ids: set[str] | None = None
) -> list[dict[str, str]]:
    elementary_ports: dict[str, dict[str, Any]] = {}
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or "").strip()
        for port in [*(node.get("inputs") or []), *(node.get("outputs") or [])]:
            if not isinstance(port, dict):
                continue
            if str(port.get("type") or "").casefold() not in {
                "biosphere",
                "elementary",
                "elementary_flow",
            }:
                continue
            port_id = str(port.get("id") or "").strip()
            if node_id and port_id:
                elementary_ports[f"{node_id}::{port_id}"] = port
    if not elementary_ports:
        return []

    metadata = graph.get("metadata")
    raw_refs = metadata.get("elementary_flow_refs") if isinstance(metadata, dict) else None
    if not isinstance(raw_refs, list) or not raw_refs:
        raise DomainError(
            code="ELEMENTARY_FLOW_REFERENCE_REQUIRED",
            message="LCIA requires an exact provider reference for every elementary exchange",
            status_code=422,
            details={"exchange_ids": sorted(elementary_ports)},
        )

    refs: list[dict[str, str]] = []
    seen: set[str] = set()
    graph_field_map = {
        "source_namespace": "flowSourceNamespace",
        "flow_uuid": "flowUuid",
        "version": "flowVersion",
        "flow_property_uuid": "flowPropertyUuid",
        "flow_property_version": "flowPropertyVersion",
        "unit_group_uuid": "unitGroupUuid",
        "unit_group_version": "unitGroupVersion",
        "unit": "unit",
        "direction": "direction",
    }
    for index, raw_ref in enumerate(raw_refs):
        if not isinstance(raw_ref, dict):
            raise DomainError(
                code="ELEMENTARY_FLOW_REFERENCE_INVALID",
                message="elementary Flow references must be objects",
                status_code=422,
                details={"index": index},
            )
        ref = {
            field: str(raw_ref.get(field) or "").strip()
            for field in _ELEMENTARY_REF_FIELDS
        }
        missing = [field for field, value in ref.items() if not value]
        if missing:
            raise DomainError(
                code="ELEMENTARY_FLOW_REFERENCE_INCOMPLETE",
                message="elementary Flow reference lacks exact identity fields",
                status_code=422,
                details={"index": index, "missing_fields": missing},
            )
        exchange_id = ref["exchange_id"]
        if exchange_id in seen:
            raise DomainError(
                code="ELEMENTARY_FLOW_REFERENCE_DUPLICATE",
                message="each elementary exchange must have exactly one provider reference",
                status_code=422,
                details={"exchange_id": exchange_id},
            )
        seen.add(exchange_id)
        port = elementary_ports.get(exchange_id)
        if port is None:
            if exchange_id in (reviewed_excluded_exchange_ids or set()):
                # The reviewed purpose derivation removed this exchange from the solve graph.
                # Its source metadata still cites it, but no other unknown reference is allowed.
                continue
            raise DomainError(
                code="ELEMENTARY_FLOW_REFERENCE_UNKNOWN_EXCHANGE",
                message="elementary Flow reference does not match a graph exchange",
                status_code=422,
                details={"exchange_id": exchange_id},
            )
        for ref_field, graph_field in graph_field_map.items():
            graph_value = str(port.get(graph_field) or "").strip()
            if ref[ref_field] != graph_value:
                raise DomainError(
                    code="ELEMENTARY_FLOW_REFERENCE_GRAPH_MISMATCH",
                    message="elementary Flow reference differs from the frozen graph identity",
                    status_code=422,
                    details={
                        "exchange_id": exchange_id,
                        "field": ref_field,
                        "graph_value": graph_value,
                        "reference_value": ref[ref_field],
                    },
                )
        refs.append(ref)
    missing_refs = sorted(set(elementary_ports).difference(seen))
    # A newly added exchange may reuse a flow already certified in this exact graph. Its port
    # carries the complete flow identity, while compartment lives in the reviewed metadata ref.
    # Copy that compartment only when the full identity has one unambiguous match.
    identity_fields = tuple(field for field in graph_field_map if field != "exchange_id")
    unresolved: list[str] = []
    for exchange_id in missing_refs:
        port = elementary_ports[exchange_id]
        matches = {
            ref["compartment"]
            for ref in refs
            if all(ref[field] == str(port.get(graph_field_map[field]) or "").strip()
                   for field in identity_fields)
        }
        if len(matches) != 1:
            unresolved.append(exchange_id)
            continue
        refs.append({
            "exchange_id": exchange_id,
            **{field: str(port.get(graph_field_map[field]) or "").strip()
               for field in identity_fields},
            "compartment": next(iter(matches)),
        })
    if unresolved:
        raise DomainError(
            code="ELEMENTARY_FLOW_REFERENCE_REQUIRED",
            message="LCIA requires an exact provider reference for every elementary exchange",
            status_code=422,
            details={"exchange_ids": unresolved},
        )
    return refs


def capability_catalog(engine_probe: dict[str, Any] | None) -> dict[str, Any]:
    contracts = (engine_probe or {}).get("contracts") or {}
    engine_ready = (engine_probe or {}).get("status") == "ready"
    items: list[dict[str, Any]] = []
    for descriptor in CAPABILITIES:
        item = dict(descriptor)
        if item["execution"] in {"nebula_one", "nebula_one_snapshot"}:
            item["status"] = "ready"
        elif item["execution"] == "nebula_lca":
            item["status"] = (
                "ready" if engine_ready and contracts.get("lcia_run") else "unavailable"
            )
        else:
            item["status"] = (
                "ready"
                if engine_ready
                and contracts.get("provider_model_snapshot")
                and contracts.get("provider_solve")
                else "unavailable"
            )
        items.append(item)
    return {
        "schema_version": "nebula_one.capabilities.v1",
        "engine": engine_probe,
        "items": items,
    }


class AnalysisRunService:
    def __init__(
        self,
        database: Database,
        client: NebulaLCAClient,
        outbox: OutboxService,
    ) -> None:
        self.database = database
        self.client = client
        self.outbox = outbox
        self._registered = {
            item["key"] for item in CAPABILITIES if item.get("analysis_run", True)
        }

    def run(
        self,
        system_model_id: str,
        payload: AnalysisRunCreate,
        *,
        outbox_topic: str = ANALYSIS_EXECUTE_TOPIC,
    ) -> AnalysisRun:
        record, event, created = self.submit(
            system_model_id,
            payload,
            outbox_topic=outbox_topic,
        )
        if not created and (record.status != "pending" or event.status != "pending"):
            return self._replay(record, record.request_sha256)
        worker_id = f"inline:{record.id}"
        try:
            self.outbox.claim_event(
                event.id,
                worker_id=worker_id,
                lease_seconds=min(
                    3600,
                    max(30, int(self.client.timeout_seconds) + 5),
                ),
            )
        except DomainError as exc:
            if exc.code == "OUTBOX_EVENT_NOT_CLAIMABLE":
                return self._replay(self.get(record.id), record.request_sha256)
            raise
        try:
            completed = self.execute_queued(record.id)
        except DomainError as exc:
            self.outbox.fail(
                event.id,
                worker_id=worker_id,
                error={
                    "code": exc.code,
                    "message": exc.message,
                    "status_code": exc.status_code,
                    "details": exc.details,
                },
                retryable=exc.status_code >= 500,
            )
            raise
        self.outbox.complete(event.id, worker_id=worker_id)
        return completed

    def submit(
        self,
        system_model_id: str,
        payload: AnalysisRunCreate,
        *,
        outbox_topic: str = ANALYSIS_EXECUTE_TOPIC,
    ) -> tuple[AnalysisRun, OutboxEvent, bool]:
        if payload.capability_key not in self._registered:
            raise DomainError(
                code="CAPABILITY_NOT_EXECUTABLE",
                message=f"calculation capability is not executable: {payload.capability_key}",
                status_code=422,
                details={"executable_capabilities": sorted(self._registered)},
            )
        with self.database.session() as db:
            system_model = db.get(SystemModel, system_model_id)
            if system_model is None:
                raise DomainError(
                    code="SYSTEM_MODEL_NOT_FOUND",
                    message=f"system model not found: {system_model_id}",
                    status_code=404,
                )
            revision: SystemRevision | None = None
            if payload.system_revision_id is not None:
                revision = db.get(SystemRevision, payload.system_revision_id)
                if revision is None:
                    raise DomainError(
                        code="SYSTEM_REVISION_NOT_FOUND",
                        message=f"system revision not found: {payload.system_revision_id}",
                        status_code=404,
                    )
                if revision.system_model_id != system_model_id:
                    raise DomainError(
                        code="SYSTEM_REVISION_MODEL_MISMATCH",
                        message="system revision does not belong to the requested system model",
                        status_code=409,
                    )
            context = self._context(system_model, revision)
            graph_sha256 = (
                revision.graph_sha256 if revision is not None else system_model.graph_sha256
            )
            system_revision_hash = (
                revision.content_sha256 if revision is not None else None
            )
            request_basis = {
                "schema_version": "nebula.analysis-run-request.v1",
                "system_model_id": system_model_id,
                "system_model_graph_sha256": system_model.graph_sha256,
                "system_revision_id": revision.id if revision is not None else None,
                "system_revision_sha256": system_revision_hash,
                "capability_key": payload.capability_key,
                "parameters": payload.parameters,
            }
            run_id, idempotency_key, request_sha256 = build_run_identity(
                run_kind="analysis",
                scope_id=system_model_id,
                explicit_idempotency_key=payload.idempotency_key,
                request_basis=request_basis,
            )
            existing = db.scalar(
                select(AnalysisRun).where(
                    AnalysisRun.system_model_id == system_model_id,
                    AnalysisRun.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                self._assert_request_match(existing, request_sha256)
                if existing.status == "failed":
                    self._replay(existing, request_sha256)
                event = enqueue_outbox_event(
                    db,
                    topic=outbox_topic,
                    aggregate_type="AnalysisRun",
                    aggregate_id=existing.id,
                    payload={"run_id": existing.id},
                )
                if existing.status == "succeeded" and event.status in {
                    "pending",
                    "retry_wait",
                }:
                    event.status = "completed"
                    event.completed_at = existing.completed_at or datetime.now(timezone.utc)
                db.commit()
                db.refresh(event)
                return existing, event, False
            record = AnalysisRun(
                id=run_id,
                system_model_id=system_model_id,
                system_revision_id=revision.id if revision is not None else None,
                capability_key=payload.capability_key,
                idempotency_key=idempotency_key,
                request_sha256=request_sha256,
                parameters=payload.parameters,
                model_graph_sha256=graph_sha256,
                status="pending",
            )
            db.add(record)
            db.flush()
            event = enqueue_outbox_event(
                db,
                topic=outbox_topic,
                aggregate_type="AnalysisRun",
                aggregate_id=record.id,
                payload={"run_id": record.id},
            )
            try:
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                existing = db.scalar(
                    select(AnalysisRun).where(
                        AnalysisRun.system_model_id == system_model_id,
                        AnalysisRun.idempotency_key == idempotency_key,
                    )
                )
                if existing is not None:
                    self._assert_request_match(existing, request_sha256)
                    event = db.scalar(
                        select(OutboxEvent).where(
                            OutboxEvent.topic == outbox_topic,
                            OutboxEvent.aggregate_id == existing.id,
                        )
                    )
                    assert event is not None
                    return existing, event, False
                raise DomainError(
                    code="ANALYSIS_RUN_CLAIM_CONFLICT",
                    message="analysis run could not claim its idempotency key",
                    status_code=409,
                    details={"idempotency_key": idempotency_key},
                ) from exc
            db.refresh(record)
            db.refresh(event)
            return record, event, True

    def execute_queued(self, run_id: str) -> AnalysisRun:
        with self.database.session() as db:
            record = db.get(AnalysisRun, run_id)
            if record is None:
                raise DomainError(
                    code="ANALYSIS_RUN_NOT_FOUND",
                    message=f"analysis run not found: {run_id}",
                    status_code=404,
                )
            if record.status == "succeeded":
                return record
            if record.status == "failed":
                error_status = int((record.error or {}).get("status_code") or 400)
                if error_status < 500:
                    return self._replay(record, record.request_sha256)
                record.status = "pending"
                record.error = None
                record.completed_at = None
            system_model = db.get(SystemModel, record.system_model_id)
            assert system_model is not None
            revision = (
                db.get(SystemRevision, record.system_revision_id)
                if record.system_revision_id is not None
                else None
            )
            context = self._context(system_model, revision)
            if context.graph_sha256 != record.model_graph_sha256:
                raise DomainError(
                    code="ANALYSIS_RUN_MODEL_DRIFT",
                    message="analysis run model graph no longer matches its fixed identity",
                    status_code=409,
                    details={
                        "run_id": record.id,
                        "expected_graph_sha256": record.model_graph_sha256,
                        "actual_graph_sha256": context.graph_sha256,
                    },
                )
            record.status = "running"
            record.started_at = datetime.now(timezone.utc)
            derivation = self._model_derivation(db, record, system_model, revision)
            db.commit()

        execution_graph = context.graph
        execution_graph_sha256 = context.graph_sha256
        execution_parameters = record.parameters
        operation_hash: str | None = None
        if derivation is not None:
            execution_graph = derivation["graph"]
            execution_graph_sha256 = derivation["derived_graph_sha256"]
            execution_parameters = {
                **record.parameters,
                "demand": derivation["demand"],
                "background_process_pins": derivation["background_process_pins"],
                "mapped_background_process_pins": derivation[
                    "mapped_background_process_pins"
                ],
                "project_background_pins": derivation["project_background_pins"],
            }
            # Two purposes of one revision can solve the same stored graph bytes, so the operation
            # identity has to carry the derivation or one purpose's answer could stand for another.
            operation_hash = canonical_json_sha256(
                {
                    "operation": "nebula_one.model-derivation.v1",
                    "base_operation_hash": context.system_revision_hash
                    or context.graph_sha256,
                    "basis_sha256": derivation["basis_sha256"],
                }
            )

        try:
            result, receipt = self._execute(
                capability_key=record.capability_key,
                graph=execution_graph,
                upstream_project_id=context.upstream_project_id,
                upstream_version=context.upstream_version,
                base_graph_sha256=context.base_graph_sha256,
                provider_snapshot_ref=context.provider_snapshot_ref,
                graph_sha256=execution_graph_sha256,
                system_revision_hash=context.system_revision_hash,
                parameters=execution_parameters,
                provider_idempotency_key=f"nebula-one:analysis-run:{record.id}",
                operation_hash=operation_hash,
                model_derivation=None
                if derivation is None
                else derivation["stamp"],
            )
            receipt = {
                **receipt,
                "system_revision_id": record.system_revision_id,
                "model_graph_sha256": context.graph_sha256,
            }
        except DomainError as exc:
            self._mark_failed(run_id, exc)
            exc.details = {**exc.details, "run_id": run_id}
            raise
        except Exception as exc:
            wrapped = DomainError(
                code="ANALYSIS_EXECUTION_FAILED",
                message="analysis execution failed unexpectedly",
                status_code=500,
                details={"run_id": run_id, "exception_type": type(exc).__name__},
            )
            self._mark_failed(run_id, wrapped)
            raise wrapped from exc

        with self.database.session() as db:
            record = db.get(AnalysisRun, run_id)
            assert record is not None
            record.status = "succeeded"
            record.result = result
            record.provider_receipt = receipt
            record.completed_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(record)
            return record

    def handle_outbox(self, payload: dict[str, Any]) -> None:
        if set(payload) != {"run_id"} or not isinstance(payload.get("run_id"), str):
            raise DomainError(
                code="ANALYSIS_OUTBOX_PAYLOAD_INVALID",
                message="analysis outbox payload must contain only run_id",
                status_code=422,
            )
        self.execute_queued(payload["run_id"])

    def _model_derivation(
        self,
        db,
        record: AnalysisRun,
        system_model: SystemModel,
        revision: SystemRevision | None,
    ) -> dict[str, Any] | None:
        """Re-derive the accepted purpose's calculation model under its own saved identity.

        The worker never trusts a stored graph copy: it re-derives from the stored model under the
        exact rule package the accepted request named, and refuses if that no longer reproduces the
        saved basis. A restart, a retry or a new rule version therefore cannot change what an
        already-accepted calculation means.
        """
        parameters = record.parameters or {}
        purpose = parameters.get("calculation_purpose")
        basis = parameters.get("calculation_basis")
        if purpose is None and basis is None:
            return None
        if record.capability_key != "solve.nebula.v1":
            raise DomainError(
                code="MODEL_DERIVATION_CAPABILITY_UNSUPPORTED",
                message=(
                    "a purpose-derived calculation model can only be solved through the provider"
                    f" solve capability, not '{record.capability_key}'"
                ),
                status_code=422,
                details={"run_id": record.id, "capability_key": record.capability_key},
            )
        if not isinstance(purpose, str) or not purpose.strip() or not isinstance(basis, dict):
            raise DomainError(
                code="MODEL_DERIVATION_BASIS_MISSING",
                message=(
                    "this run names an accounting purpose without the calculation basis it was"
                    " accepted with, so it cannot be re-derived"
                ),
                status_code=409,
                details={"run_id": record.id, "calculation_purpose": purpose},
            )
        if revision is None:
            raise DomainError(
                code="MODEL_DERIVATION_REVISION_REQUIRED",
                message="a purpose-derived calculation model requires the model revision it was derived from",
                status_code=409,
                details={"run_id": record.id},
            )
        derivation = resolve_purpose_derivation(
            db,
            revision=revision,
            application=db.get(Application, system_model.application_id),
            purpose=purpose,
            demand=parameters.get("demand") or [],
            background_process_pins=parameters.get("background_process_pins") or [],
            mapped_background_process_pins=parameters.get(
                "mapped_background_process_pins"
            )
            or [],
            project_background_pins=parameters.get("project_background_pins") or [],
            lcia_methods=parameters.get("lcia_methods"),
            pinned_basis=basis,
        )
        return {
            "graph": derivation.derived.graph,
            "demand": derivation.derived.demand,
            "background_process_pins": derivation.derived.background_process_pins,
            "mapped_background_process_pins": derivation.derived.mapped_background_process_pins,
            "project_background_pins": derivation.derived.project_background_pins,
            "derived_graph_sha256": derivation.derived.derived_graph_sha256,
            "source_graph_sha256": derivation.derived.source_graph_sha256,
            "basis_sha256": derivation.basis_sha256,
            "stamp": {
                "schema_version": "nebula_one.model-derivation-stamp.v1",
                "purpose": derivation.purpose,
                "basis_sha256": derivation.basis_sha256,
                "source_graph_sha256": derivation.derived.source_graph_sha256,
                "derived_graph_sha256": derivation.derived.derived_graph_sha256,
                # The accepted request stores the basis with its own digest, so the stamp has to
                # carry the same shape or the freeze comparison could never agree with it.
                "basis": {**derivation.basis, "basis_sha256": derivation.basis_sha256},
                # Which exchanges this solve counted is a reviewed decision, not a side effect of the
                # graph it was handed, so the receipt states it and the freeze compares it.
                "flow_selection": flow_selection_of(derivation.derived),
            },
        }

    def _context(
        self,
        system_model: SystemModel,
        revision: SystemRevision | None,
    ) -> AnalysisExecutionContext:
        if system_model.provider_base_url.rstrip("/") != self.client.base_url:
            raise DomainError(
                code="MODEL_PROVIDER_CONNECTION_CHANGED",
                message="the configured Nebula LCA connection differs from the model pin source",
                status_code=409,
                details={
                    "pinned_base_url": system_model.provider_base_url,
                    "configured_base_url": self.client.base_url,
                },
            )
        graph_sha256 = (
            revision.graph_sha256 if revision is not None else system_model.graph_sha256
        )
        provider_snapshot_ref = None
        if system_model.upstream_receipt.get("source_kind") != "inline_casepack":
            provider_snapshot_ref = {
                "project_id": system_model.upstream_project_id,
                "version": system_model.upstream_version,
                "graph_hash": system_model.graph_sha256,
            }
        return AnalysisExecutionContext(
            graph=copy.deepcopy(
                revision.graph_snapshot if revision is not None else system_model.graph_snapshot
            ),
            upstream_project_id=system_model.upstream_project_id,
            upstream_version=system_model.upstream_version,
            base_graph_sha256=system_model.graph_sha256,
            provider_snapshot_ref=provider_snapshot_ref,
            graph_sha256=graph_sha256,
            system_revision_hash=(
                revision.content_sha256 if revision is not None else None
            ),
        )

    @staticmethod
    def _assert_request_match(record: AnalysisRun, request_sha256: str) -> None:
        if record.request_sha256 != request_sha256:
            raise DomainError(
                code="ANALYSIS_IDEMPOTENCY_CONFLICT",
                message="the analysis idempotency key was used for a different request",
                status_code=409,
                details={
                    "run_id": record.id,
                    "idempotency_key": record.idempotency_key,
                    "existing_request_sha256": record.request_sha256,
                    "request_sha256": request_sha256,
                },
            )

    def _replay(
        self, record: AnalysisRun, request_sha256: str
    ) -> AnalysisRun:
        self._assert_request_match(record, request_sha256)
        if record.status == "succeeded":
            return record
        if record.status == "failed":
            error = record.error or {}
            details = dict(error.get("details") or {})
            details.update(
                {
                    "run_id": record.id,
                    "idempotent_replay": True,
                }
            )
            raise DomainError(
                code=str(error.get("code") or "ANALYSIS_EXECUTION_FAILED"),
                message=str(error.get("message") or "analysis execution failed"),
                status_code=int(error.get("status_code") or 409),
                details=details,
            )
        raise DomainError(
            code="ANALYSIS_RUN_IN_PROGRESS",
            message="the idempotent analysis run is already in progress",
            status_code=409,
            details={
                "run_id": record.id,
                "idempotency_key": record.idempotency_key,
                "status": record.status,
            },
        )

    def _execute(
        self,
        *,
        capability_key: str,
        graph: dict[str, Any],
        upstream_project_id: str,
        upstream_version: int,
        base_graph_sha256: str,
        provider_snapshot_ref: dict[str, Any] | None,
        graph_sha256: str,
        system_revision_hash: str | None,
        parameters: dict[str, Any],
        provider_idempotency_key: str,
        operation_hash: str | None = None,
        model_derivation: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if capability_key == "mfa.declared.v1":
            return project_declared_mfa(graph, parameters), {
                "executor": "nebula_one.analysis.mfa",
                "schema_version": "nebula_one.mfa.v1",
                "basis": "nebula_lca_graph_declared_amounts",
            }
        if capability_key == "lcia.nebula.v1":
            if provider_snapshot_ref is None:
                raise DomainError(
                    code="INLINE_MODEL_LCIA_UNSUPPORTED",
                    message="inline CasePack models require an exact background provider pin before LCIA",
                    status_code=422,
                )
            methods = parameters.get("lcia_methods", ["EF v3.1"])
            if (
                not isinstance(methods, list)
                or not methods
                or any(not isinstance(item, str) or not item.strip() for item in methods)
            ):
                raise DomainError(
                    code="LCIA_METHODS_INVALID",
                    message="lcia_methods must be a non-empty list of method names",
                    status_code=422,
                )
            force_recompile = parameters.get("force_recompile", False)
            if not isinstance(force_recompile, bool):
                raise DomainError(
                    code="LCIA_PARAMETERS_INVALID",
                    message="force_recompile must be a boolean",
                    status_code=422,
                )
            upstream = self.client.run_lcia(
                graph=graph,
                project_id=upstream_project_id,
                lcia_methods=[item.strip() for item in methods],
                force_recompile=force_recompile,
            )
            return upstream.payload, {
                "provider": "nebula_lca",
                "endpoint": "/api/model/run",
                "base_url": self.client.base_url,
                "etag": upstream.etag,
                "upstream_run_id": upstream.payload.get("run_id"),
                "upstream_status": upstream.payload.get("status"),
            }
        if capability_key == "solve.nebula.v1":
            demand = parameters.get("demand")
            if not isinstance(demand, list) or not demand or any(
                not isinstance(item, dict) for item in demand
            ):
                raise DomainError(
                    code="SOLVE_DEMAND_INVALID",
                    message="provider solve requires a non-empty structured demand list",
                    status_code=422,
                )
            methods = parameters.get("lcia_methods")
            if methods is not None and (
                not isinstance(methods, list)
                or any(not isinstance(item, str) or not item.strip() for item in methods)
            ):
                raise DomainError(
                    code="SOLVE_METHODS_INVALID",
                    message="lcia_methods must be a list of method names when supplied",
                    status_code=422,
                )
            raw_background_pins = parameters.get("background_process_pins", [])
            if not isinstance(raw_background_pins, list) or any(
                not isinstance(item, dict) for item in raw_background_pins
            ):
                raise DomainError(
                    code="BACKGROUND_PROCESS_PINS_INVALID",
                    message="background_process_pins must be a list of exact pin objects",
                    status_code=422,
                )
            try:
                background_pins = [
                    ProviderBackgroundProcessPin.model_validate(item).model_dump(
                        mode="json"
                    )
                    for item in raw_background_pins
                ]
            except ValidationError as exc:
                raise DomainError(
                    code="BACKGROUND_PROCESS_PINS_INVALID",
                    message="background_process_pins failed exact identity validation",
                    status_code=422,
                    details={"errors": exc.errors(include_url=False)},
                ) from exc
            try:
                raw_mapped = parameters.get('mapped_background_process_pins', [])
                if not isinstance(raw_mapped, list):
                    raise ValueError('mapped pins must be a list')
                mapped_pins = [ProviderMappedBackgroundProcessPin.model_validate(p).model_dump(mode='json') for p in raw_mapped]
            except (ValueError, TypeError) as exc:
                raise DomainError(code='MAPPED_BACKGROUND_PINS_INVALID', message='Mapped background pins lack exact identity or confirmation.', status_code=422) from exc
            try:
                raw_project = parameters.get("project_background_pins", [])
                if not isinstance(raw_project, list):
                    raise ValueError("project pins must be a list")
                project_pins = [ProviderProjectBackgroundPin.model_validate(p).model_dump(mode="json") for p in raw_project]
            except (ValueError, TypeError) as exc:
                raise DomainError(code="PROJECT_BACKGROUND_PINS_INVALID", message="User project background pins lack exact identity.", status_code=422) from exc
            consumer_ids = [item["consumer_exchange_id"] for item in [*background_pins, *mapped_pins, *project_pins]]
            if len(consumer_ids) != len(set(consumer_ids)):
                raise DomainError(
                    code="BACKGROUND_PROCESS_PIN_DUPLICATE",
                    message="a consumer exchange may have only one background Process pin",
                    status_code=422,
                )
            functional_unit = graph.get(
                "functionalUnit", graph.get("functional_unit")
            )
            if not isinstance(functional_unit, dict):
                first_demand = demand[0]
                functional_unit = {
                    "display_text": str(functional_unit or "").strip(),
                    "amount": first_demand.get("amount"),
                    "flow_uuid": first_demand.get("reference_flow_uuid"),
                    "unit": first_demand.get("unit"),
                    "unit_group_uuid": first_demand.get("unit_group_uuid"),
                    "unit_group_version": first_demand.get("unit_group_version"),
                }
            else:
                functional_unit = dict(functional_unit)
                functional_unit.setdefault("display_text", str(functional_unit))
            inline_snapshot: dict[str, Any] = {
                "schema_version": "nebula_one.provider.inline_snapshot.v1",
                "graph_hash": graph_sha256,
                "functional_unit": functional_unit,
                "graph": graph,
            }
            if provider_snapshot_ref is not None:
                inline_snapshot["base_snapshot_ref"] = provider_snapshot_ref
            if model_derivation is not None:
                # The graph sent is a purpose-derived calculation model, so the snapshot names the
                # stored model it was derived from instead of implying it is that stored model.
                inline_snapshot["source_graph_hash"] = model_derivation[
                    "source_graph_sha256"
                ]
            request_payload: dict[str, Any] = {
                "inline_snapshot": {
                    **inline_snapshot,
                },
                "demand": demand,
                "operation_hash": operation_hash
                or system_revision_hash
                or graph_sha256,
                "idempotency_key": provider_idempotency_key,
            }
            if parameters.get("scenario_id") is not None:
                request_payload["scenario_id"] = parameters["scenario_id"]
            if methods is not None:
                request_payload["lcia_methods"] = [item.strip() for item in methods]
            if methods is not None or parameters.get("calculation_purpose") == "cbam":
                selection = (model_derivation or {}).get("flow_selection") or {}
                request_payload["elementary_flows"] = _provider_elementary_flow_refs(
                    graph,
                    reviewed_excluded_exchange_ids=set(selection.get("excluded_exchange_ids") or []),
                )
            if background_pins:
                request_payload["background_process_pins"] = background_pins
            if mapped_pins:
                request_payload['mapped_background_process_pins'] = mapped_pins
            if project_pins:
                request_payload["project_background_pins"] = project_pins
            native_climate_pin = parameters.get("native_background_climate")
            if isinstance(native_climate_pin, dict):
                request_payload["native_background_climate"] = native_climate_pin
            native_inventory_pin = parameters.get("native_background_inventory")
            if isinstance(native_inventory_pin, dict):
                request_payload["native_background_inventory"] = native_inventory_pin
            upstream = self.client.solve_provider(request_payload)
            upstream_status = str(upstream.payload.get("status") or "").casefold()
            if upstream_status not in {"completed", "succeeded"}:
                raise DomainError(
                    code="PROVIDER_SOLVE_NOT_SUCCEEDED",
                    message="Nebula LCA provider solve did not succeed",
                    status_code=409,
                    details={
                        "run_id": upstream.payload.get("run_id"),
                        "upstream_status": upstream.payload.get("status"),
                        "issues": upstream.payload.get("issues"),
                    },
                )
            return upstream.payload, {
                "provider": "nebula_lca",
                "endpoint": "/api/provider/v1/solve",
                "base_url": self.client.base_url,
                "etag": upstream.etag,
                "upstream_run_id": upstream.payload.get("run_id"),
                "upstream_status": upstream.payload.get("status"),
                "snapshot_ref": upstream.payload.get("snapshot_ref"),
                "provenance": upstream.payload.get("provenance"),
                "provider_idempotency_key": upstream.payload.get("idempotency_key"),
                "provider_request_hash": upstream.payload.get("request_hash"),
                **(
                    {}
                    if model_derivation is None
                    else {"model_derivation": model_derivation}
                ),
            }
        raise AssertionError(f"unhandled capability: {capability_key}")

    def _mark_failed(self, run_id: str, error: DomainError) -> None:
        with self.database.session() as db:
            record = db.get(AnalysisRun, run_id)
            if record is None:
                return
            record.status = "failed"
            record.error = {
                "code": error.code,
                "message": error.message,
                "status_code": error.status_code,
                "details": error.details,
            }
            record.completed_at = datetime.now(timezone.utc)
            db.commit()

    def get(self, run_id: str) -> AnalysisRun:
        with self.database.session() as db:
            record = db.get(AnalysisRun, run_id)
            if record is None:
                raise DomainError(
                    code="ANALYSIS_RUN_NOT_FOUND",
                    message=f"analysis run not found: {run_id}",
                    status_code=404,
                )
            return record

    def list_for_system_model(self, system_model_id: str) -> list[AnalysisRun]:
        with self.database.session() as db:
            if db.get(SystemModel, system_model_id) is None:
                raise DomainError(
                    code="SYSTEM_MODEL_NOT_FOUND",
                    message=f"system model not found: {system_model_id}",
                    status_code=404,
                )
            statement = (
                select(AnalysisRun)
                .where(AnalysisRun.system_model_id == system_model_id)
                .order_by(AnalysisRun.created_at.desc())
            )
            return list(db.scalars(statement))
