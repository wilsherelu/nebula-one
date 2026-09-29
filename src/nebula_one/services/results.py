from __future__ import annotations

import copy

from sqlalchemy import select

from ..database import Database
from ..errors import DomainError
from ..hashing import canonical_json_sha256
from ..models import AnalysisRun
from ..runtime_models import (
    AnalysisPlan,
    EvidenceItem,
    EvidencePack,
    InventoryDataPoint,
    InventorySnapshot,
    MethodPackage,
    ParameterSet,
    ResultSet,
    Scenario,
    SolvedSystemSnapshot,
)
from ..runtime_schemas import (
    EvidencePackCreate,
    ResultSetCreate,
    SolvedSystemSnapshotCreate,
)
from .runtime_support import (
    is_ancestor,
    require_application,
    require_method_package,
    require_revision,
)


_PER_RUN_IDENTITY_KEYS = (
    "analysis_run_id",
    "upstream_run_id",
    "scenario_id",
    "scenario_hash",
    "provider_idempotency_key",
    "provider_request_hash",
)
_PER_RUN_PROVENANCE_KEYS = (
    "scenario_id",
    "scenario_hash",
    "idempotency_key",
    "request_hash",
)


def _strip_per_run_identity(container: dict) -> None:
    for key in _PER_RUN_IDENTITY_KEYS:
        container.pop(key, None)
    provenance = container.get("provenance")
    if isinstance(provenance, dict):
        for key in _PER_RUN_PROVENANCE_KEYS:
            provenance.pop(key, None)


def _semantic_solved_output(output: dict) -> dict:
    normalized = copy.deepcopy(output)
    # solve_hash already binds the content hash of these three inputs, so the
    # surrogate ids would only add per-run churn to the solved content identity.
    normalized.pop("system_revision_id", None)
    normalized.pop("inventory_snapshot_id", None)
    normalized.pop("parameter_set_id", None)
    receipt = normalized.get("provider_receipt")
    if isinstance(receipt, dict):
        _strip_per_run_identity(receipt)
    contribution_graph = normalized.get("contribution_graph")
    if isinstance(contribution_graph, dict):
        _strip_per_run_identity(contribution_graph)
    return normalized


def _persisted_solved_output(record: SolvedSystemSnapshot) -> dict:
    return {
        field: getattr(record, field)
        for field in (
            "provider",
            "provider_receipt",
            "functional_unit",
            "database_release",
            "solver_version",
            "activity_vector",
            "scaled_technosphere_exchanges",
            "scaled_elementary_exchanges",
            "internal_transfers",
            "boundary_flows",
            "process_balance_residuals",
            "contribution_graph",
            "lcia_results",
            "native_background_climate",
        )
    }


class ResultService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def import_solved_snapshot(
        self, application_id: str, payload: SolvedSystemSnapshotCreate
    ) -> SolvedSystemSnapshot:
        with self.database.session() as db:
            require_application(db, application_id)
            revision, _ = require_revision(
                db, payload.system_revision_id, application_id
            )
            inventory_hash = None
            if payload.inventory_snapshot_id:
                inventory = db.get(InventorySnapshot, payload.inventory_snapshot_id)
                if inventory is None:
                    raise DomainError(
                        code="INVENTORY_SNAPSHOT_NOT_FOUND",
                        message=f"inventory snapshot not found: {payload.inventory_snapshot_id}",
                        status_code=404,
                    )
                if inventory.application_id != application_id:
                    raise DomainError(
                        code="INVENTORY_APPLICATION_MISMATCH",
                        message="inventory snapshot does not belong to the requested application",
                        status_code=409,
                    )
                if inventory.status != "frozen":
                    raise DomainError(
                        code="INVENTORY_SNAPSHOT_NOT_FROZEN",
                        message="solved snapshot requires a frozen inventory snapshot",
                        status_code=409,
                    )
                inventory_hash = inventory.content_sha256
                inventory_revision, inventory_model = require_revision(
                    db, inventory.system_revision_id, application_id
                )
                if inventory_model.id != revision.system_model_id or not is_ancestor(
                    db, inventory_revision.id, revision
                ):
                    raise DomainError(
                        code="SOLVED_SNAPSHOT_INVENTORY_REVISION_MISMATCH",
                        message="inventory snapshot must bind to the solved model and an ancestor revision",
                        status_code=409,
                    )
            parameter_hash = None
            if payload.parameter_set_id:
                parameter_set = db.get(ParameterSet, payload.parameter_set_id)
                if parameter_set is None:
                    raise DomainError(
                        code="PARAMETER_SET_NOT_FOUND",
                        message=f"parameter set not found: {payload.parameter_set_id}",
                        status_code=404,
                    )
                if parameter_set.application_id != application_id:
                    raise DomainError(
                        code="PARAMETER_SET_APPLICATION_MISMATCH",
                        message="parameter set does not belong to the requested application",
                        status_code=409,
                    )
                if parameter_set.status != "frozen":
                    raise DomainError(
                        code="PARAMETER_SET_NOT_FROZEN",
                        message="solved snapshot requires a frozen parameter set",
                        status_code=409,
                    )
                parameter_hash = parameter_set.content_sha256
            receipt = payload.provider_receipt
            missing_receipt = [
                key
                for key in (
                    "endpoint",
                    "status",
                    "system_revision_hash",
                    "database_release",
                    "solver_version",
                )
                if not receipt.get(key)
            ]
            if not any(
                receipt.get(key)
                for key in ("run_id", "upstream_run_id", "artifact_id")
            ):
                missing_receipt.append("run_id|upstream_run_id|artifact_id")
            if missing_receipt:
                raise DomainError(
                    code="SOLVED_SNAPSHOT_RECEIPT_INCOMPLETE",
                    message="solved snapshot requires traceable provider evidence",
                    status_code=422,
                    details={"missing": missing_receipt},
                )
            if str(receipt.get("status")).casefold() not in {
                "completed",
                "succeeded",
            }:
                raise DomainError(
                    code="SOLVED_SNAPSHOT_PROVIDER_NOT_SUCCEEDED",
                    message="provider receipt does not describe a succeeded solve",
                    status_code=409,
                    details={"provider_status": receipt.get("status")},
                )
            expected_receipt = {
                "system_revision_hash": revision.content_sha256,
                "inventory_snapshot_hash": inventory_hash,
                "parameter_set_hash": parameter_hash,
                "database_release": payload.database_release,
                "solver_version": payload.solver_version,
            }
            mismatches = {
                key: {"expected": expected, "actual": receipt.get(key)}
                for key, expected in expected_receipt.items()
                if receipt.get(key) != expected
            }
            if mismatches:
                raise DomainError(
                    code="SOLVED_SNAPSHOT_RECEIPT_MISMATCH",
                    message="provider receipt does not match the referenced frozen inputs",
                    status_code=409,
                    details={"mismatches": mismatches},
                )
            revision_functional_unit = revision.graph_snapshot.get(
                "functionalUnit", revision.graph_snapshot.get("functional_unit")
            )
            if canonical_json_sha256(payload.functional_unit) != canonical_json_sha256(
                revision_functional_unit
            ):
                raise DomainError(
                    code="SOLVED_SNAPSHOT_FUNCTIONAL_UNIT_MISMATCH",
                    message="solved functional unit differs from the system revision",
                    status_code=409,
                )
            solve_basis = {
                "system_revision_hash": revision.content_sha256,
                "inventory_snapshot_hash": inventory_hash,
                "parameter_set_hash": parameter_hash,
                "functional_unit": payload.functional_unit,
                "database_release": payload.database_release,
                "solver_version": payload.solver_version,
            }
            # New provider freezes distinguish computational inputs from per-run IDs.
            # Imported historical receipts without this field retain their identity.
            if receipt.get('calculation_basis') is not None:
                solve_basis['calculation_basis'] = receipt['calculation_basis']
            solve_hash = canonical_json_sha256(solve_basis)
            output = payload.model_dump(mode="json")
            content_sha256 = canonical_json_sha256(
                {
                    "solve_hash": solve_hash,
                    "output": _semantic_solved_output(output),
                }
            )
            existing = db.scalar(
                select(SolvedSystemSnapshot).where(
                    SolvedSystemSnapshot.application_id == application_id,
                    SolvedSystemSnapshot.solve_hash == solve_hash,
                )
            )
            if existing is not None:
                # Compare solved content itself: the stored hash is only valid
                # under the identity function generation that wrote it.
                if _semantic_solved_output(_persisted_solved_output(existing)) != (
                    _semantic_solved_output(output)
                ):
                    raise DomainError(
                        code="SOLVED_SNAPSHOT_CACHE_CONFLICT",
                        message="the same solve basis returned different solved content",
                        status_code=409,
                        details={
                            "solve_hash": solve_hash,
                            "existing_content_sha256": existing.content_sha256,
                            "returned_content_sha256": content_sha256,
                        },
                    )
                return existing
            record = SolvedSystemSnapshot(
                application_id=application_id,
                solve_hash=solve_hash,
                content_sha256=content_sha256,
                **output,
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            return record

    def list_solved_snapshots(
        self, application_id: str
    ) -> list[SolvedSystemSnapshot]:
        with self.database.session() as db:
            require_application(db, application_id)
            return list(
                db.scalars(
                    select(SolvedSystemSnapshot)
                    .where(SolvedSystemSnapshot.application_id == application_id)
                    .order_by(SolvedSystemSnapshot.created_at)
                )
            )

    def create_result_set(
        self, application_id: str, payload: ResultSetCreate
    ) -> ResultSet:
        with self.database.session() as db:
            require_application(db, application_id)
            scenario = db.get(Scenario, payload.scenario_id)
            if scenario is None:
                raise DomainError(
                    code="SCENARIO_NOT_FOUND",
                    message=f"scenario not found: {payload.scenario_id}",
                    status_code=404,
                )
            if scenario.application_id != application_id:
                raise DomainError(
                    code="SCENARIO_APPLICATION_MISMATCH",
                    message="scenario does not belong to the requested application",
                    status_code=409,
                )
            if scenario.status != "frozen":
                raise DomainError(
                    code="SCENARIO_NOT_FROZEN",
                    message="result set requires a frozen scenario",
                    status_code=409,
                )
            if payload.analysis_plan_id:
                plan = db.get(AnalysisPlan, payload.analysis_plan_id)
                if plan is None:
                    raise DomainError(
                        code="ANALYSIS_PLAN_NOT_FOUND",
                        message=f"analysis plan not found: {payload.analysis_plan_id}",
                        status_code=404,
                    )
                if plan.scenario_id != scenario.id or plan.status != "frozen":
                    raise DomainError(
                        code="RESULT_ANALYSIS_PLAN_MISMATCH",
                        message="result set requires a frozen plan for the same scenario",
                        status_code=409,
                    )
            solved_hash = None
            if payload.solved_snapshot_id:
                solved = db.get(SolvedSystemSnapshot, payload.solved_snapshot_id)
                if solved is None:
                    raise DomainError(
                        code="SOLVED_SNAPSHOT_NOT_FOUND",
                        message=f"solved snapshot not found: {payload.solved_snapshot_id}",
                        status_code=404,
                    )
                if (
                    solved.application_id != application_id
                    or solved.system_revision_id != scenario.system_revision_id
                    or solved.inventory_snapshot_id != scenario.inventory_snapshot_id
                    or solved.parameter_set_id != scenario.parameter_set_id
                ):
                    raise DomainError(
                        code="RESULT_SOLVED_SNAPSHOT_MISMATCH",
                        message="solved snapshot does not match the frozen scenario inputs",
                        status_code=409,
                    )
                solved_hash = solved.content_sha256
            run_hashes: dict[str, str] = {}
            for run_id in payload.source_run_ids:
                run = db.get(AnalysisRun, run_id)
                if run is None:
                    raise DomainError(
                        code="ANALYSIS_RUN_NOT_FOUND",
                        message=f"analysis run not found: {run_id}",
                        status_code=404,
                    )
                if (
                    run.status != "succeeded"
                    or run.system_revision_id != scenario.system_revision_id
                ):
                    raise DomainError(
                        code="RESULT_SOURCE_RUN_MISMATCH",
                        message="source run must be succeeded and bind to the scenario revision",
                        status_code=409,
                        details={"run_id": run_id},
                    )
                run_hashes[run.id] = canonical_json_sha256(
                    {
                        "model_graph_sha256": run.model_graph_sha256,
                        "capability_key": run.capability_key,
                        "parameters": run.parameters,
                        "result": run.result,
                        "provider_receipt": run.provider_receipt,
                    }
                )
            unbound_refs = sorted(
                set(payload.method_package_refs).difference(
                    scenario.method_package_refs
                )
            )
            if unbound_refs:
                raise DomainError(
                    code="RESULT_METHOD_PACKAGE_NOT_IN_SCENARIO",
                    message="result set cannot introduce method packages absent from the scenario",
                    status_code=409,
                    details={"unbound_refs": unbound_refs},
                )
            package_hashes = {
                reference: require_method_package(db, reference).content_sha256
                for reference in payload.method_package_refs
            }
            result_content = {
                "scenario_hash": scenario.content_sha256,
                "analysis_plan_id": payload.analysis_plan_id,
                "solved_snapshot_hash": solved_hash,
                "dimensions": payload.dimensions,
                "metrics": payload.metrics,
                "units": payload.units,
                "aggregation_rules": payload.aggregation_rules,
                "source_run_hashes": run_hashes,
                "method_package_hashes": package_hashes,
            }
            record = ResultSet(
                application_id=application_id,
                result_hash=canonical_json_sha256(result_content),
                **payload.model_dump(),
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            return record

    def list_result_sets(self, application_id: str) -> list[ResultSet]:
        with self.database.session() as db:
            require_application(db, application_id)
            return list(
                db.scalars(
                    select(ResultSet)
                    .where(ResultSet.application_id == application_id)
                    .order_by(ResultSet.created_at)
                )
            )

    def create_evidence_pack(
        self, application_id: str, payload: EvidencePackCreate
    ) -> EvidencePack:
        with self.database.session() as db:
            require_application(db, application_id)
            result = db.get(ResultSet, payload.result_set_id)
            if result is None:
                raise DomainError(
                    code="RESULT_SET_NOT_FOUND",
                    message=f"result set not found: {payload.result_set_id}",
                    status_code=404,
                )
            if result.application_id != application_id:
                raise DomainError(
                    code="RESULT_SET_APPLICATION_MISMATCH",
                    message="result set does not belong to the requested application",
                    status_code=409,
                )
            scenario = db.get(Scenario, result.scenario_id)
            assert scenario is not None
            revision, system_model = require_revision(
                db, scenario.system_revision_id, application_id
            )
            evidence_ids = set(payload.evidence_item_ids)
            data_points: list[InventoryDataPoint] = []
            inventory = None
            if scenario.inventory_snapshot_id:
                inventory = db.get(InventorySnapshot, scenario.inventory_snapshot_id)
                assert inventory is not None
                data_points = list(
                    db.scalars(
                        select(InventoryDataPoint).where(
                            InventoryDataPoint.inventory_snapshot_id == inventory.id
                        )
                    )
                )
                evidence_ids.update(point.evidence_id for point in data_points)
            evidence_hashes: dict[str, str] = {}
            missing_evidence: list[str] = []
            for evidence_id in sorted(evidence_ids):
                evidence = db.get(EvidenceItem, evidence_id)
                if evidence is None or evidence.application_id != application_id:
                    missing_evidence.append(evidence_id)
                else:
                    evidence_hashes[evidence.id] = evidence.content_sha256
            if missing_evidence:
                raise DomainError(
                    code="EVIDENCE_PACK_ITEM_MISSING",
                    message="evidence pack references missing or foreign evidence",
                    status_code=409,
                    details={"evidence_ids": missing_evidence},
                )
            parameter = (
                db.get(ParameterSet, scenario.parameter_set_id)
                if scenario.parameter_set_id
                else None
            )
            solved = (
                db.get(SolvedSystemSnapshot, result.solved_snapshot_id)
                if result.solved_snapshot_id
                else None
            )
            packages: dict[str, str] = {}
            for reference in result.method_package_refs:
                package: MethodPackage = require_method_package(db, reference)
                packages[reference] = package.content_sha256
            run_lineage: dict[str, dict] = {}
            for run_id in result.source_run_ids:
                run = db.get(AnalysisRun, run_id)
                assert run is not None
                run_lineage[run.id] = {
                    "capability_key": run.capability_key,
                    "model_graph_sha256": run.model_graph_sha256,
                    "provider_receipt": run.provider_receipt,
                }
            lineage = {
                "result_set": {"id": result.id, "result_hash": result.result_hash},
                "scenario": {
                    "id": scenario.id,
                    "content_sha256": scenario.content_sha256,
                },
                "system_revision": {
                    "id": revision.id,
                    "content_sha256": revision.content_sha256,
                    "graph_sha256": revision.graph_sha256,
                },
                "model_pin": {
                    "provider": system_model.provider,
                    "project_id": system_model.upstream_project_id,
                    "version": system_model.upstream_version,
                    "graph_sha256": system_model.graph_sha256,
                },
                "inventory_snapshot": (
                    {"id": inventory.id, "content_sha256": inventory.content_sha256}
                    if inventory
                    else None
                ),
                "parameter_set": (
                    {"id": parameter.id, "content_sha256": parameter.content_sha256}
                    if parameter
                    else None
                ),
                "solved_snapshot": (
                    {
                        "id": solved.id,
                        "solve_hash": solved.solve_hash,
                        "content_sha256": solved.content_sha256,
                        "provider_receipt": solved.provider_receipt,
                    }
                    if solved
                    else None
                ),
                "analysis_runs": run_lineage,
                "method_packages": packages,
                "evidence_items": evidence_hashes,
            }
            completeness = {
                "complete": len(evidence_hashes) == len(evidence_ids),
                "inventory_data_point_count": len(data_points),
                "evidence_item_count": len(evidence_hashes),
                "data_points_with_evidence": sum(
                    1 for point in data_points if point.evidence_id in evidence_hashes
                ),
            }
            content = {"lineage": lineage, "completeness": completeness}
            record = EvidencePack(
                application_id=application_id,
                result_set_id=result.id,
                evidence_item_ids=sorted(evidence_ids),
                lineage=lineage,
                completeness=completeness,
                content_sha256=canonical_json_sha256(content),
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            return record

    def list_evidence_packs(self, application_id: str) -> list[EvidencePack]:
        with self.database.session() as db:
            require_application(db, application_id)
            return list(
                db.scalars(
                    select(EvidencePack)
                    .where(EvidencePack.application_id == application_id)
                    .order_by(EvidencePack.created_at)
                )
            )
