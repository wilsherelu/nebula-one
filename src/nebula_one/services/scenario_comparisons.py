from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..analysis.scenario_comparison import (
    build_comparison_metrics,
    render_comparison_svg,
)
from ..database import Database
from ..errors import DomainError
from ..hashing import canonical_json_sha256
from ..models import OutboxEvent
from ..runtime_models import (
    Comparison,
    Scenario,
    ScenarioComparisonRun,
    SolvedSystemSnapshot,
)
from ..runtime_schemas import (
    ProductCarbonFootprintCreate,
    ProviderSolveAndFreezeCreate,
    ScenarioComparisonExecuteCreate,
)
from .pcf import ProductCarbonFootprintService
from .provider_solve import ProviderSolveService
from .solved_mfa import SolvedMFAService
from .run_idempotency import build_run_identity
from .outbox import OutboxService, enqueue_outbox_event


SCENARIO_COMPARISON_EXECUTE_TOPIC = "scenario.comparison.execute.v1"


@dataclass(frozen=True, slots=True)
class ScenarioComparisonContext:
    application_id: str
    comparison_hash: str
    scenario_specs: tuple[dict[str, str], ...]
    semantic_request: dict[str, Any]
    request_basis: dict[str, Any]


class ScenarioComparisonService:
    def __init__(
        self,
        database: Database,
        provider_solves: ProviderSolveService,
        solved_mfa: SolvedMFAService,
        product_carbon_footprints: ProductCarbonFootprintService,
        outbox: OutboxService,
    ) -> None:
        self.database = database
        self.provider_solves = provider_solves
        self.solved_mfa = solved_mfa
        self.product_carbon_footprints = product_carbon_footprints
        self.outbox = outbox

    def submit(
        self,
        comparison_id: str,
        payload: ScenarioComparisonExecuteCreate,
    ) -> tuple[ScenarioComparisonRun, OutboxEvent, bool]:
        with self.database.session() as db:
            context = self._context(db, comparison_id, payload)
            run_id, idempotency_key, request_sha256 = build_run_identity(
                run_kind="scenario-comparison",
                scope_id=comparison_id,
                explicit_idempotency_key=payload.idempotency_key,
                request_basis=context.request_basis,
            )
            existing = db.scalar(
                select(ScenarioComparisonRun).where(
                    ScenarioComparisonRun.comparison_id == comparison_id,
                    ScenarioComparisonRun.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                self._assert_request_match(existing, request_sha256)
                event = db.scalar(
                    select(OutboxEvent).where(
                        OutboxEvent.topic == SCENARIO_COMPARISON_EXECUTE_TOPIC,
                        OutboxEvent.aggregate_id == existing.id,
                    )
                )
                if event is None:
                    raise DomainError(
                        code="COMPARISON_RUN_NOT_QUEUED",
                        message="the idempotent comparison run was not created by the queue API",
                        status_code=409,
                        details={"comparison_run_id": existing.id},
                    )
                return existing, event, True
            run = ScenarioComparisonRun(
                id=run_id,
                application_id=context.application_id,
                comparison_id=comparison_id,
                baseline_scenario_id=payload.baseline_scenario_id,
                idempotency_key=idempotency_key,
                request_sha256=request_sha256,
                status="pending",
                request_json=context.semantic_request,
                scenario_results=[],
                metrics=[],
                audit={
                    "status": "pending",
                    "checks": {"completed_scenario_count": 0},
                    "issues": [],
                },
                error={},
            )
            db.add(run)
            db.flush()
            event = enqueue_outbox_event(
                db,
                topic=SCENARIO_COMPARISON_EXECUTE_TOPIC,
                aggregate_type="ScenarioComparisonRun",
                aggregate_id=run.id,
                payload={"run_id": run.id},
                max_attempts=5,
            )
            try:
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                existing = db.scalar(
                    select(ScenarioComparisonRun).where(
                        ScenarioComparisonRun.comparison_id == comparison_id,
                        ScenarioComparisonRun.idempotency_key == idempotency_key,
                    )
                )
                if existing is not None:
                    self._assert_request_match(existing, request_sha256)
                    event = db.scalar(
                        select(OutboxEvent).where(
                            OutboxEvent.topic
                            == SCENARIO_COMPARISON_EXECUTE_TOPIC,
                            OutboxEvent.aggregate_id == existing.id,
                        )
                    )
                    if event is not None:
                        return existing, event, True
                raise DomainError(
                    code="COMPARISON_RUN_CLAIM_CONFLICT",
                    message="comparison run could not claim its idempotency key",
                    status_code=409,
                    details={"idempotency_key": idempotency_key},
                ) from exc
            db.refresh(run)
            db.refresh(event)
            return run, event, False

    def handle_outbox(self, payload: dict[str, Any]) -> dict[str, Any]:
        if set(payload) != {"run_id"} or not isinstance(payload.get("run_id"), str):
            raise DomainError(
                code="COMPARISON_OUTBOX_PAYLOAD_INVALID",
                message="comparison outbox payload must contain only run_id",
                status_code=422,
            )
        run = self.execute_queued(payload["run_id"])
        return {
            "resource_type": "ScenarioComparisonRun",
            "id": run.id,
            "content_sha256": run.content_sha256,
        }

    def execute_queued(self, run_id: str) -> ScenarioComparisonRun:
        try:
            return self._execute_queued(run_id)
        except DomainError as exc:
            self._persist_preflight_failure(run_id, exc)
            raise
        except Exception as exc:
            wrapped = DomainError(
                code="COMPARISON_EXECUTION_FAILED",
                message="scenario comparison execution failed unexpectedly",
                status_code=500,
                details={
                    "comparison_run_id": run_id,
                    "exception_type": type(exc).__name__,
                },
            )
            self._persist_preflight_failure(run_id, wrapped)
            raise wrapped from exc

    def _execute_queued(self, run_id: str) -> ScenarioComparisonRun:
        with self.database.session() as db:
            run = db.get(ScenarioComparisonRun, run_id)
            if run is None:
                raise DomainError(
                    code="SCENARIO_COMPARISON_RUN_NOT_FOUND",
                    message=f"scenario comparison run not found: {run_id}",
                    status_code=404,
                )
            if run.status == "succeeded":
                return run
            try:
                payload = ScenarioComparisonExecuteCreate.model_validate(
                    run.request_json
                )
            except Exception as exc:
                raise DomainError(
                    code="COMPARISON_RUN_REQUEST_INVALID",
                    message="persisted comparison request is invalid",
                    status_code=409,
                    details={"comparison_run_id": run.id},
                ) from exc
            context = self._context(db, run.comparison_id, payload)
            expected_run_id, _, request_sha256 = build_run_identity(
                run_kind="scenario-comparison",
                scope_id=run.comparison_id,
                explicit_idempotency_key=run.idempotency_key,
                request_basis=context.request_basis,
            )
            if expected_run_id != run.id or request_sha256 != run.request_sha256:
                raise DomainError(
                    code="COMPARISON_RUN_CONTEXT_CHANGED",
                    message="comparison or scenario identity changed after queue submission",
                    status_code=409,
                    details={
                        "comparison_run_id": run.id,
                        "expected_run_id": expected_run_id,
                        "expected_request_sha256": request_sha256,
                        "actual_request_sha256": run.request_sha256,
                    },
                )
            if (
                run.application_id != context.application_id
                or run.baseline_scenario_id != payload.baseline_scenario_id
            ):
                raise DomainError(
                    code="COMPARISON_RUN_CONTEXT_CHANGED",
                    message="queued comparison application or baseline changed",
                    status_code=409,
                    details={"comparison_run_id": run.id},
                )
            scenario_results = list(run.scenario_results or [])
            self._validate_partial_results(db, context, scenario_results)
            run.status = "running"
            run.error = {}
            run.completed_at = None
            db.commit()

        scenario_specs = list(context.scenario_specs)
        completed_ids = {item["scenario_id"] for item in scenario_results}
        current_scenario_id: str | None = None
        try:
            for scenario in scenario_specs:
                current_scenario_id = scenario["id"]
                if current_scenario_id in completed_ids:
                    continue
                scenario_results.append(
                    self._solve_scenario(
                        application_id=context.application_id,
                        run_id=run_id,
                        scenario=scenario,
                        payload=payload,
                    )
                )
                completed_ids.add(current_scenario_id)
                self._persist_progress(run_id, scenario_results)
            metrics, audit, content_sha256 = self._success_payload(
                comparison_hash=context.comparison_hash,
                request_sha256=request_sha256,
                semantic_request=context.semantic_request,
                payload=payload,
                scenario_results=scenario_results,
            )
        except DomainError as exc:
            failure_details = {
                **exc.details,
                "comparison_run_id": run_id,
                "scenario_id": current_scenario_id,
            }
            self._persist_failure(
                run_id,
                code=exc.code,
                message=exc.message,
                status_code=exc.status_code,
                details=failure_details,
                scenario_results=scenario_results,
            )
            exc.details = failure_details
            raise
        except Exception as exc:
            wrapped = DomainError(
                code="COMPARISON_EXECUTION_FAILED",
                message="scenario comparison execution failed unexpectedly",
                status_code=500,
                details={
                    "comparison_run_id": run_id,
                    "scenario_id": current_scenario_id,
                    "exception_type": type(exc).__name__,
                },
            )
            self._persist_failure(
                run_id,
                code=wrapped.code,
                message=wrapped.message,
                status_code=wrapped.status_code,
                details=wrapped.details,
                scenario_results=scenario_results,
            )
            raise wrapped from exc

        with self.database.session() as db:
            record = db.get(ScenarioComparisonRun, run_id)
            assert record is not None
            record.status = "succeeded"
            record.scenario_results = scenario_results
            record.metrics = metrics
            record.audit = audit
            record.error = {}
            record.content_sha256 = content_sha256
            record.completed_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(record)
            return record

    def _persist_preflight_failure(
        self,
        run_id: str,
        error: DomainError,
    ) -> None:
        with self.database.session() as db:
            record = db.get(ScenarioComparisonRun, run_id)
            if record is None or record.status == "failed":
                return
            scenario_results = list(record.scenario_results or [])
        self._persist_failure(
            run_id,
            code=error.code,
            message=error.message,
            status_code=error.status_code,
            details={**error.details, "comparison_run_id": run_id},
            scenario_results=scenario_results,
        )

    @staticmethod
    def _validate_partial_results(
        db: Session,
        context: ScenarioComparisonContext,
        scenario_results: list[dict[str, Any]],
    ) -> None:
        expected = list(context.scenario_specs)
        result_ids = [str(item.get("scenario_id") or "") for item in scenario_results]
        expected_prefix = [item["id"] for item in expected[: len(result_ids)]]
        if result_ids != expected_prefix:
            raise DomainError(
                code="COMPARISON_PARTIAL_RESULTS_INVALID",
                message="partial comparison results must be a unique scenario-order prefix",
                status_code=409,
                details={
                    "scenario_ids": result_ids,
                    "expected_prefix": expected_prefix,
                },
            )
        for result, scenario in zip(scenario_results, expected):
            if (
                result.get("scenario_hash") != scenario["content_sha256"]
                or result.get("system_revision_id") != scenario["system_revision_id"]
            ):
                raise DomainError(
                    code="COMPARISON_PARTIAL_RESULTS_INVALID",
                    message="partial comparison result no longer matches its frozen scenario",
                    status_code=409,
                    details={"scenario_id": scenario["id"]},
                )
            snapshot = db.get(SolvedSystemSnapshot, result.get("solved_snapshot_id"))
            if snapshot is None or snapshot.content_sha256 != result.get(
                "solved_snapshot_hash"
            ):
                raise DomainError(
                    code="COMPARISON_PARTIAL_SNAPSHOT_INVALID",
                    message="partial comparison result snapshot is missing or changed",
                    status_code=409,
                    details={"scenario_id": scenario["id"]},
                )

    def _persist_progress(
        self,
        run_id: str,
        scenario_results: list[dict[str, Any]],
    ) -> None:
        with self.database.session() as db:
            record = db.get(ScenarioComparisonRun, run_id)
            assert record is not None
            record.status = "running"
            record.scenario_results = scenario_results
            record.audit = {
                "status": "running",
                "checks": {
                    "completed_scenario_count": len(scenario_results),
                },
                "issues": [],
            }
            record.error = {}
            record.completed_at = None
            db.commit()

    def execute(
        self, comparison_id: str, payload: ScenarioComparisonExecuteCreate
    ) -> ScenarioComparisonRun:
        with self.database.session() as db:
            context = self._context(db, comparison_id, payload)
            run_id, idempotency_key, request_sha256 = build_run_identity(
                run_kind="scenario-comparison",
                scope_id=comparison_id,
                explicit_idempotency_key=payload.idempotency_key,
                request_basis=context.request_basis,
            )
            existing = db.scalar(
                select(ScenarioComparisonRun).where(
                    ScenarioComparisonRun.comparison_id == comparison_id,
                    ScenarioComparisonRun.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                return self._replay(existing, request_sha256)
            run = ScenarioComparisonRun(
                id=run_id,
                application_id=context.application_id,
                comparison_id=comparison_id,
                baseline_scenario_id=payload.baseline_scenario_id,
                idempotency_key=idempotency_key,
                request_sha256=request_sha256,
                status="running",
                request_json=context.semantic_request,
                scenario_results=[],
                metrics=[],
                audit={},
                error={},
            )
            db.add(run)
            try:
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                existing = db.scalar(
                    select(ScenarioComparisonRun).where(
                        ScenarioComparisonRun.comparison_id == comparison_id,
                        ScenarioComparisonRun.idempotency_key == idempotency_key,
                    )
                )
                if existing is not None:
                    return self._replay(existing, request_sha256)
                raise DomainError(
                    code="COMPARISON_RUN_CLAIM_CONFLICT",
                    message="comparison run could not claim its idempotency key",
                    status_code=409,
                    details={"idempotency_key": idempotency_key},
                ) from exc

        application_id = context.application_id
        comparison_hash = context.comparison_hash
        scenario_specs = list(context.scenario_specs)
        semantic_request = context.semantic_request

        scenario_results: list[dict[str, Any]] = []
        current_scenario_id: str | None = None
        try:
            for scenario in scenario_specs:
                current_scenario_id = scenario["id"]
                scenario_results.append(
                    self._solve_scenario(
                        application_id=application_id,
                        run_id=run_id,
                        scenario=scenario,
                        payload=payload,
                    )
                )
            metrics, audit, content_sha256 = self._success_payload(
                comparison_hash=comparison_hash,
                request_sha256=request_sha256,
                semantic_request=semantic_request,
                payload=payload,
                scenario_results=scenario_results,
            )
        except DomainError as exc:
            failure_details = {
                **exc.details,
                "comparison_run_id": run_id,
                "scenario_id": current_scenario_id,
            }
            self._persist_failure(
                run_id,
                code=exc.code,
                message=exc.message,
                status_code=exc.status_code,
                details=failure_details,
                scenario_results=scenario_results,
            )
            exc.details = failure_details
            raise
        except Exception as exc:
            wrapped = DomainError(
                code="COMPARISON_EXECUTION_FAILED",
                message="scenario comparison execution failed unexpectedly",
                status_code=500,
                details={
                    "comparison_run_id": run_id,
                    "scenario_id": current_scenario_id,
                    "exception_type": type(exc).__name__,
                },
            )
            self._persist_failure(
                run_id,
                code=wrapped.code,
                message=wrapped.message,
                status_code=wrapped.status_code,
                details=wrapped.details,
                scenario_results=scenario_results,
            )
            raise wrapped from exc

        with self.database.session() as db:
            record = db.get(ScenarioComparisonRun, run_id)
            assert record is not None
            record.status = "succeeded"
            record.scenario_results = scenario_results
            record.metrics = metrics
            record.audit = audit
            record.content_sha256 = content_sha256
            record.completed_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(record)
            return record

    @staticmethod
    def _success_payload(
        *,
        comparison_hash: str,
        request_sha256: str,
        semantic_request: dict[str, Any],
        payload: ScenarioComparisonExecuteCreate,
        scenario_results: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
        metrics = build_comparison_metrics(
            scenario_results=scenario_results,
            baseline_scenario_id=payload.baseline_scenario_id,
        )
        warning_scenarios = [
            item["scenario_id"]
            for item in scenario_results
            if item["mfa_audit"].get("status") != "passed"
        ]
        checks = {
            "comparison_compatible": True,
            "scenario_count": len(scenario_results),
            "solved_snapshot_count": len(scenario_results),
            "mfa_audit_passed_count": len(scenario_results),
            "lcia_result_count": (
                len(scenario_results) if payload.lcia_methods else 0
            ),
            "metric_count": len(metrics),
            "unit_series": sorted({metric["series_id"] for metric in metrics}),
        }
        if payload.pcf_method_package_ref:
            checks["pcf_result_count"] = len(scenario_results)
        audit = {
            "status": "passed_with_warnings" if warning_scenarios else "passed",
            "checks": checks,
            "issues": (
                [
                    {
                        "code": "MFA_AUDIT_WARNINGS_PRESENT",
                        "severity": "warning",
                        "scenario_ids": warning_scenarios,
                    }
                ]
                if warning_scenarios
                else []
            ),
            "provenance": {
                "comparison_hash": comparison_hash,
                "request_sha256": request_sha256,
                "baseline_scenario_id": payload.baseline_scenario_id,
                "scenario_hashes": {
                    item["scenario_id"]: item["scenario_hash"]
                    for item in scenario_results
                },
                "solved_snapshot_hashes": {
                    item["scenario_id"]: item["solved_snapshot_hash"]
                    for item in scenario_results
                },
            },
        }
        content_sha256 = canonical_json_sha256(
            {
                "comparison_hash": comparison_hash,
                "request": semantic_request,
                "scenario_results": scenario_results,
                "metrics": metrics,
                "audit": audit,
            }
        )
        return metrics, audit, content_sha256

    def _solve_scenario(
        self,
        *,
        application_id: str,
        run_id: str,
        scenario: dict[str, str],
        payload: ScenarioComparisonExecuteCreate,
    ) -> dict[str, Any]:
        solved = self.provider_solves.solve_and_freeze(
            application_id,
            scenario["system_revision_id"],
            ProviderSolveAndFreezeCreate(
                demand=payload.demand,
                idempotency_key=f"comparison:{run_id}:{scenario['id']}",
                scenario_id=scenario["id"],
                lcia_methods=payload.lcia_methods,
                background_process_pins=payload.background_process_pins,
                mapped_background_process_pins=payload.mapped_background_process_pins,
            ),
        )
        if payload.lcia_methods:
            indicators = solved.lcia_results.get("indicator_results")
            elementary_receipts = solved.provider_receipt.get(
                "elementary_flow_receipts"
            )
            if not isinstance(indicators, list) or not indicators:
                raise DomainError(
                    code="COMPARISON_LCIA_RESULT_MISSING",
                    message="scenario comparison requires provider LCIA results for every scenario",
                    status_code=409,
                    details={"scenario_id": scenario["id"]},
                )
            if not isinstance(elementary_receipts, list) or not elementary_receipts:
                raise DomainError(
                    code="COMPARISON_LCIA_RECEIPT_MISSING",
                    message="scenario comparison requires exact elementary Flow receipts",
                    status_code=409,
                    details={"scenario_id": scenario["id"]},
                )
        mfa = self.solved_mfa.analyze(solved.id)
        if mfa["audit"]["status"] == "failed":
            raise DomainError(
                code="COMPARISON_MFA_AUDIT_FAILED",
                message="scenario comparison requires every solved MFA audit to pass",
                status_code=409,
                details={
                    "scenario_id": scenario["id"],
                    "audit": mfa["audit"],
                },
            )
        pcf_result: dict[str, Any] = {}
        pcf_result_hash: str | None = None
        if payload.pcf_method_package_ref:
            pcf_result = self.product_carbon_footprints.analyze(
                solved.id,
                ProductCarbonFootprintCreate(
                    method_package_ref=payload.pcf_method_package_ref
                ),
            )
            pcf_result_hash = str(pcf_result.get("content_sha256") or "").strip()
            if not pcf_result_hash:
                raise DomainError(
                    code="COMPARISON_PCF_RESULT_INVALID",
                    message="scenario comparison requires a content-addressed PCF result",
                    status_code=409,
                    details={"scenario_id": scenario["id"]},
                )
        sankey_series = next(
            (
                item
                for item in mfa["series"]
                if str(item.get("unit_group_label") or "").casefold() == "mass"
            ),
            mfa["series"][0],
        )
        result = {
            "scenario_id": scenario["id"],
            "scenario_name": scenario["name"],
            "scenario_hash": scenario["content_sha256"],
            "system_revision_id": scenario["system_revision_id"],
            "solved_snapshot_id": solved.id,
            "solved_snapshot_hash": solved.content_sha256,
            "solve_hash": solved.solve_hash,
            "provider_receipt": solved.provider_receipt,
            "lcia_results": solved.lcia_results,
            "elementary_flow_receipts": solved.provider_receipt.get(
                "elementary_flow_receipts", []
            ),
            "technosphere_flow_receipts": solved.provider_receipt.get(
                "technosphere_flow_receipts", []
            ),
            "mfa_audit": mfa["audit"],
            "mfa_series": mfa["series"],
            "sankey_url": (
                f"/api/v1/solved-system-snapshots/{solved.id}/mfa/sankey.svg"
                f"?series_id={sankey_series['series_id']}"
            ),
        }
        if payload.pcf_method_package_ref:
            result["pcf_result"] = pcf_result
            result["pcf_result_hash"] = pcf_result_hash
        return result

    @staticmethod
    def _context(
        db: Session,
        comparison_id: str,
        payload: ScenarioComparisonExecuteCreate,
    ) -> ScenarioComparisonContext:
        comparison = db.get(Comparison, comparison_id)
        if comparison is None:
            raise DomainError(
                code="COMPARISON_NOT_FOUND",
                message=f"comparison not found: {comparison_id}",
                status_code=404,
            )
        if not comparison.comparability.get("compatible"):
            raise DomainError(
                code="COMPARISON_NOT_COMPATIBLE",
                message="scenario comparison cannot run until compatibility checks pass",
                status_code=409,
                details={"comparability": comparison.comparability},
            )
        if not 2 <= len(comparison.scenario_ids) <= 5:
            raise DomainError(
                code="COMPARISON_SCENARIO_COUNT_UNSUPPORTED",
                message="scenario comparison execution requires two to five scenarios",
                status_code=422,
                details={"scenario_count": len(comparison.scenario_ids)},
            )
        if payload.baseline_scenario_id not in comparison.scenario_ids:
            raise DomainError(
                code="COMPARISON_BASELINE_NOT_INCLUDED",
                message="baseline scenario must belong to the comparison",
                status_code=409,
            )
        scenarios = [
            db.get(Scenario, scenario_id) for scenario_id in comparison.scenario_ids
        ]
        if any(item is None for item in scenarios):
            raise DomainError(
                code="COMPARISON_SCENARIO_NOT_FOUND",
                message="comparison contains a missing scenario",
                status_code=409,
            )
        for scenario in scenarios:
            assert scenario is not None
            if scenario.status != "frozen":
                raise DomainError(
                    code="SCENARIO_NOT_FROZEN",
                    message="comparison execution requires frozen scenarios",
                    status_code=409,
                    details={"scenario_id": scenario.id},
                )
        revision_ids = [
            scenario.system_revision_id
            for scenario in scenarios
            if scenario is not None
        ]
        if len(set(revision_ids)) != len(revision_ids):
            raise DomainError(
                code="COMPARISON_REVISION_DUPLICATE",
                message="each scenario in an executable comparison must bind a distinct revision",
                status_code=409,
                details={"system_revision_ids": revision_ids},
            )
        scenario_specs = tuple(
            {
                "id": scenario.id,
                "name": scenario.name,
                "system_revision_id": scenario.system_revision_id,
                "content_sha256": scenario.content_sha256,
            }
            for scenario in scenarios
            if scenario is not None
        )
        semantic_request = payload.model_dump(
            mode="json", exclude={"idempotency_key"}
        )
        if payload.pcf_method_package_ref is None:
            semantic_request.pop("pcf_method_package_ref", None)
        request_basis = {
            "schema_version": "nebula.scenario-comparison-run-request.v1",
            "comparison_id": comparison.id,
            "comparison_sha256": comparison.content_sha256,
            "scenarios": list(scenario_specs),
            "request": semantic_request,
        }
        return ScenarioComparisonContext(
            application_id=comparison.application_id,
            comparison_hash=comparison.content_sha256,
            scenario_specs=scenario_specs,
            semantic_request=semantic_request,
            request_basis=request_basis,
        )

    @staticmethod
    def _assert_request_match(
        record: ScenarioComparisonRun, request_sha256: str
    ) -> None:
        if record.request_sha256 != request_sha256:
            raise DomainError(
                code="COMPARISON_IDEMPOTENCY_CONFLICT",
                message="the comparison idempotency key was used for a different request",
                status_code=409,
                details={
                    "comparison_run_id": record.id,
                    "idempotency_key": record.idempotency_key,
                    "existing_request_sha256": record.request_sha256,
                    "request_sha256": request_sha256,
                },
            )

    def _replay(
        self, record: ScenarioComparisonRun, request_sha256: str
    ) -> ScenarioComparisonRun:
        self._assert_request_match(record, request_sha256)
        if record.status == "succeeded":
            return record
        if record.status == "failed":
            error = record.error or {}
            details = dict(error.get("details") or {})
            details.update(
                {
                    "comparison_run_id": record.id,
                    "idempotent_replay": True,
                }
            )
            raise DomainError(
                code=str(error.get("code") or "COMPARISON_EXECUTION_FAILED"),
                message=str(error.get("message") or "scenario comparison failed"),
                status_code=int(error.get("status_code") or 409),
                details=details,
            )
        raise DomainError(
            code="COMPARISON_RUN_IN_PROGRESS",
            message="the idempotent comparison run is already in progress",
            status_code=409,
            details={
                "comparison_run_id": record.id,
                "idempotency_key": record.idempotency_key,
                "status": record.status,
            },
        )

    def _persist_failure(
        self,
        run_id: str,
        *,
        code: str,
        message: str,
        status_code: int,
        details: dict[str, Any],
        scenario_results: list[dict[str, Any]],
    ) -> None:
        error = {
            "code": code,
            "message": message,
            "status_code": status_code,
            "details": details,
        }
        with self.database.session() as db:
            record = db.get(ScenarioComparisonRun, run_id)
            assert record is not None
            record.status = "failed"
            record.scenario_results = scenario_results
            record.audit = {
                "status": "failed",
                "checks": {
                    "completed_scenario_count": len(scenario_results),
                },
                "issues": [error],
            }
            record.error = error
            record.completed_at = datetime.now(timezone.utc)
            db.commit()

    def get(self, run_id: str) -> ScenarioComparisonRun:
        with self.database.session() as db:
            record = db.get(ScenarioComparisonRun, run_id)
            if record is None:
                raise DomainError(
                    code="SCENARIO_COMPARISON_RUN_NOT_FOUND",
                    message=f"scenario comparison run not found: {run_id}",
                    status_code=404,
                )
            return record

    def list_for_application(
        self, application_id: str
    ) -> list[ScenarioComparisonRun]:
        with self.database.session() as db:
            return list(
                db.scalars(
                    select(ScenarioComparisonRun)
                    .where(ScenarioComparisonRun.application_id == application_id)
                    .order_by(ScenarioComparisonRun.created_at.desc())
                )
            )

    def chart_svg(self, run_id: str) -> str:
        record = self.get(run_id)
        if record.status != "succeeded":
            raise DomainError(
                code="SCENARIO_COMPARISON_RUN_NOT_SUCCEEDED",
                message="only a succeeded scenario comparison run can render a chart",
                status_code=409,
                details={"status": record.status},
            )
        return render_comparison_svg(
            {
                "scenario_results": record.scenario_results,
                "metrics": record.metrics,
            }
        )
