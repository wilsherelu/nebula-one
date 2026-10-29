from __future__ import annotations

from typing import Any

from sqlalchemy import select

from ..analysis.cbam_trial import build_cbam_trial
from ..analysis.cbam_trial_visual import render_cbam_trial_svg
from ..analysis.cbam_trial_v2 import SCHEMA_VERSION as V2_SCHEMA_VERSION
from ..analysis.cbam_trial_v2 import THREE_COMPONENT_CALCULATION
from ..analysis.cbam_trial_v2 import build_cbam_trial_v2
from ..database import Database
from ..errors import DomainError
from ..models import AnalysisRun, Application, SeedInstallation, SystemModel, SystemRevision
from ..runtime_models import BoundaryDefinition, Period, SolvedSystemSnapshot
from ..runtime_schemas import CbamTrialCreate
from .model_processing_runtime import (
    PurposeDerivation,
    derivation_basis_from_receipt,
    flow_selection_of,
    resolve_purpose_derivation,
)
from .method_execution_contract import recover_cbam_user_selection
from .runtime_support import require_method_package

V1_SCHEMA_VERSION = "nebula_one.cbam.trial.v1"


class CbamTrialService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def analyze(self, solved_snapshot_id: str, payload: CbamTrialCreate) -> dict:
        with self.database.session() as db:
            prepared = self._prepare(db, solved_snapshot_id, payload)
        if prepared["schema_version"] == V1_SCHEMA_VERSION:
            return build_cbam_trial(**prepared["common"])
        results: list[dict[str, Any]] = []
        for spec in prepared["precursor_specs"]:
            result = self.analyze(spec["solved_snapshot_id"], spec["request"])
            if (result.get("coverage") or {}).get("precursors"):
                raise DomainError(
                    code="CBAM_TRIAL_PRECURSOR_RESULT_NOT_PINNED",
                    message="a precursor result carries its own precursor term, so this request "
                    "would inherit a sum whose chain the method package declares unsupported",
                    status_code=422,
                    details={"solved_snapshot_id": spec["solved_snapshot_id"]},
                )
            results.append(result)
        return build_cbam_trial_v2(
            **prepared["common"], **prepared["v2"], precursor_results=results
        )

    def _prepare(
        self, db: Any, solved_snapshot_id: str, payload: CbamTrialCreate
    ) -> dict[str, Any]:
        snapshot = db.get(SolvedSystemSnapshot, solved_snapshot_id)
        if snapshot is None:
            raise DomainError(
                code="SOLVED_SYSTEM_SNAPSHOT_NOT_FOUND",
                message=f"solved system snapshot not found: {solved_snapshot_id}",
                status_code=404,
            )
        period = db.get(Period, payload.reporting_period_id)
        if period is None:
            raise DomainError(
                code="REPORTING_PERIOD_NOT_FOUND",
                message=f"reporting period not found: {payload.reporting_period_id}",
                status_code=404,
            )
        if period.application_id != snapshot.application_id:
            raise DomainError(
                code="CBAM_TRIAL_PERIOD_APPLICATION_MISMATCH",
                message="reporting period and solved snapshot belong to different applications",
                status_code=409,
            )
        application = db.get(Application, snapshot.application_id)
        if application is None:
            raise DomainError(
                code="APPLICATION_NOT_FOUND",
                message=f"application not found: {snapshot.application_id}",
                status_code=404,
            )
        bound_refs = set((application.context or {}).get("method_package_refs") or [])
        if payload.method_package_ref not in bound_refs:
            raise DomainError(
                code="CBAM_TRIAL_METHOD_NOT_BOUND",
                message="CBAM trial method is not bound to this application",
                status_code=409,
            )
        package = require_method_package(db, payload.method_package_ref)
        reporting_period = {
            "id": period.id,
            "key": period.key,
            "name": period.name,
            "start_date": period.start_date.isoformat(),
            "end_date": period.end_date.isoformat(),
            "resolution": period.resolution,
        }
        common = {
            "solved_snapshot_id": snapshot.id,
            "solved_snapshot_sha256": snapshot.content_sha256,
            "application_id": snapshot.application_id,
            "activity_vector": snapshot.activity_vector,
            "scaled_technosphere_exchanges": snapshot.scaled_technosphere_exchanges,
            "scaled_elementary_exchanges": snapshot.scaled_elementary_exchanges,
            "provider_receipt": snapshot.provider_receipt,
            "reporting_period": reporting_period,
            "method_package_ref": payload.method_package_ref,
            "method_package_sha256": package.content_sha256,
            "method_package_kind": package.package_kind,
            "method_package_jurisdiction": package.jurisdiction,
            "method_package_valid_from": package.valid_from,
            "method_package_valid_to": package.valid_to,
            "manifest": package.manifest,
        }
        schema_version = str(
            (package.manifest.get("output_schema") or {}).get("schema_version") or ""
        )
        derivation = self._derivation(db, snapshot)
        self._require_derivation_methods(derivation, package, snapshot)
        flow_selection = None if derivation is None else flow_selection_of(derivation.derived)
        self._require_recorded_selection(db, snapshot, flow_selection)
        if schema_version == V2_SCHEMA_VERSION:
            v2 = {
                "frozen_graph": self._frozen_graph(db, snapshot, derivation),
                "revision_identity": self._revision_identity(db, snapshot, derivation),
                "boundary": self._boundary(db, snapshot, payload.boundary_definition_id),
                "end_use_declaration": payload.end_use_declaration,
                "flow_selection": flow_selection,
            }
            return {
                "schema_version": V2_SCHEMA_VERSION,
                "common": common,
                "v2": v2,
                "precursor_specs": self._precursor_specs(db, package.manifest, payload, period),
            }
        if schema_version != V1_SCHEMA_VERSION:
            raise DomainError(
                code="CBAM_TRIAL_OUTPUT_SCHEMA_UNSUPPORTED",
                message="the method package targets a CBAM trial schema One cannot route",
                status_code=422,
                details={
                    "method_package_ref": payload.method_package_ref,
                    "schema_version": schema_version or None,
                },
            )
        if payload.boundary_definition_id or payload.end_use_declaration:
            raise DomainError(
                code="CBAM_TRIAL_INPUT_SCHEMA_MISMATCH",
                message="a v1 CBAM trial accepts neither a boundary id nor an end-use value",
                status_code=422,
                details={
                    "boundary_definition_id": payload.boundary_definition_id,
                    "end_use_declaration": payload.end_use_declaration,
                },
            )
        if payload.precursors:
            raise DomainError(
                code="CBAM_TRIAL_INPUT_SCHEMA_MISMATCH",
                message="a v1 CBAM trial accepts no precursor evidence",
                status_code=422,
                details={"precursors": [item.solved_snapshot_id for item in payload.precursors]},
            )
        return {"schema_version": V1_SCHEMA_VERSION, "common": common}

    def _precursor_specs(
        self,
        db: Any,
        manifest: dict[str, Any],
        payload: CbamTrialCreate,
        period: Period,
    ) -> list[dict[str, Any]]:
        """Resolve each pinned precursor source into a nested trial request.

        The version the precursor is computed under comes from the package's pin, never from the
        request, and the seed that produced its snapshot is read back out of the installation table
        the analyzer cannot see.
        """
        calculation = (manifest.get("formula_graph") or {}).get("calculation")
        if calculation != THREE_COMPONENT_CALCULATION:
            if payload.precursors:
                raise DomainError(
                    code="CBAM_TRIAL_INPUT_SCHEMA_MISMATCH",
                    message="this good's method package declares no precursor term, so a request "
                    "that supplies precursor snapshots computes nothing with them",
                    status_code=422,
                    details={
                        "precursors": [item.solved_snapshot_id for item in payload.precursors]
                    },
                )
            return []
        sources = (manifest.get("precursor_rules") or {}).get("sources") or []
        requests = payload.precursors or []
        if len(requests) != len(sources):
            raise DomainError(
                code="CBAM_TRIAL_PRECURSOR_RESULT_NOT_PINNED",
                message="the request supplies a different number of precursor snapshots than the "
                "method package pins, so a pinned source would compute with no inherited value or "
                "an unsourced snapshot would stand in for one",
                status_code=422,
                details={
                    "pinned": len(sources),
                    "requested": len(requests),
                },
            )
        specs: list[dict[str, Any]] = []
        for source, entry in zip(sources, requests, strict=True):
            precursor_snapshot = db.get(SolvedSystemSnapshot, entry.solved_snapshot_id)
            if precursor_snapshot is None:
                raise DomainError(
                    code="SOLVED_SYSTEM_SNAPSHOT_NOT_FOUND",
                    message=f"solved system snapshot not found: {entry.solved_snapshot_id}",
                    status_code=404,
                )
            self._verify_source_seed(db, precursor_snapshot, source)
            specs.append(
                {
                    "solved_snapshot_id": precursor_snapshot.id,
                    "request": CbamTrialCreate(
                        method_package_ref=str(source["method_package_ref"]),
                        reporting_period_id=self._source_period_id(
                            db, precursor_snapshot, period
                        ),
                        boundary_definition_id=entry.boundary_definition_id,
                    ),
                }
            )
        return specs

    def _verify_source_seed(
        self, db: Any, snapshot: SolvedSystemSnapshot, source: dict[str, Any]
    ) -> None:
        installation = db.scalars(
            select(SeedInstallation).where(
                SeedInstallation.system_revision_id == snapshot.system_revision_id
            )
        ).first()
        pinned = {
            "seed_id": source.get("source_seed_id"),
            "seed_version": source.get("source_seed_version"),
            "bundle_content_sha256": source.get("source_bundle_content_sha256"),
        }
        observed = (
            None
            if installation is None
            else {
                "seed_id": installation.seed_id,
                "seed_version": installation.seed_version,
                "bundle_content_sha256": installation.bundle_content_sha256,
            }
        )
        if observed is None or any(observed[key] != value for key, value in pinned.items()):
            raise DomainError(
                code="CBAM_TRIAL_PRECURSOR_RESULT_NOT_PINNED",
                message="a precursor snapshot was not produced by the seed version the method "
                "package pins, so its emissions would be inherited from another model",
                status_code=409,
                details={
                    "solved_snapshot_id": snapshot.id,
                    "pinned": pinned,
                    "installed": observed,
                },
            )

    def _source_period_id(
        self, db: Any, snapshot: SolvedSystemSnapshot, period: Period
    ) -> str:
        candidate = db.scalars(
            select(Period).where(
                Period.application_id == snapshot.application_id,
                Period.key == period.key,
            )
        ).first()
        if candidate is None:
            raise DomainError(
                code="REPORTING_PERIOD_NOT_FOUND",
                message="the precursor's own application holds no reporting period with the key "
                "the complex-good request names, so A-C20's same-period rule cannot be evidenced",
                status_code=409,
                details={
                    "solved_snapshot_id": snapshot.id,
                    "period_key": period.key,
                    "application_id": snapshot.application_id,
                },
            )
        return candidate.id

    def chart_svg(self, solved_snapshot_id: str, payload: CbamTrialCreate) -> str:
        result = self.analyze(solved_snapshot_id, payload)
        if result.get("schema_version") != V1_SCHEMA_VERSION:
            raise DomainError(
                code="CBAM_TRIAL_CHART_SCHEMA_UNSUPPORTED",
                message="the v1 CBAM trial chart cannot render a multi-process boundary result",
                status_code=422,
                details={"schema_version": result.get("schema_version")},
            )
        return render_cbam_trial_svg(result)

    def _derivation(
        self, db: Any, snapshot: SolvedSystemSnapshot
    ) -> PurposeDerivation | None:
        """Re-derive the purpose's calculation model this frozen answer was solved under.

        A CBAM answer reads solved exchanges, so it has to read them against the graph that was
        actually solved. That graph is not stored as a copy: it is reproduced from the stored model
        under the exact rule identity the run was accepted with, and anything that no longer
        reproduces the recorded basis refuses instead of answering from the whole stored model.
        """
        basis = derivation_basis_from_receipt(snapshot.provider_receipt)
        if basis is None:
            return None
        run_id = (snapshot.provider_receipt or {}).get("analysis_run_id")
        run = db.get(AnalysisRun, run_id) if isinstance(run_id, str) else None
        parameters = (run.parameters or {}) if run is not None else {}
        if run is None or parameters.get("calculation_basis") != basis:
            raise DomainError(
                code="CBAM_TRIAL_DERIVATION_UNRESOLVED",
                message="此结果记录的核算口径找不到它当时的计算依据，不能读取。",
                status_code=409,
                details={
                    "solved_snapshot_id": snapshot.id,
                    "analysis_run_id": run_id,
                    "basis_sha256": basis.get("basis_sha256"),
                },
            )
        revision = db.get(SystemRevision, snapshot.system_revision_id)
        model = None if revision is None else db.get(SystemModel, revision.system_model_id)
        if revision is None or model is None:
            raise DomainError(
                code="CBAM_TRIAL_FROZEN_MODEL_DRIFT",
                message="the solved snapshot has no resolvable frozen model identity",
                status_code=409,
                details={"system_revision_id": snapshot.system_revision_id},
            )
        purpose = str(parameters.get("calculation_purpose") or "")
        # A variant's narrowed basis folds a user_calculation_method identity the solve recorded, so
        # reading the answer back must re-derive under the very same overlay or the reproduction
        # drifts. It is rebuilt through the same shared execution contract the solve and worker
        # recovery use; a whole-model run named no version and so has no overlay (returns None).
        user_selection = recover_cbam_user_selection(
            db,
            application_id=model.application_id,
            system_revision_id=revision.id,
            purpose=purpose,
            parameters=parameters,
        )
        return resolve_purpose_derivation(
            db,
            revision=revision,
            application=db.get(Application, model.application_id),
            purpose=purpose,
            demand=parameters.get("demand") or [],
            background_process_pins=parameters.get("background_process_pins") or [],
            mapped_background_process_pins=parameters.get("mapped_background_process_pins")
            or [],
            project_background_pins=parameters.get("project_background_pins") or [],
            lcia_methods=parameters.get("lcia_methods"),
            pinned_basis=basis,
            user_selection=user_selection,
        )

    @staticmethod
    def _require_derivation_methods(
        derivation: PurposeDerivation | None,
        package: Any,
        snapshot: SolvedSystemSnapshot,
    ) -> None:
        """A purpose-derived answer may only be read by the method package it was derived under.

        Two purposes of one project solve the same stored model, so without this check a CBAM trial
        could read an answer that was calculated under the whole-model purpose and report its
        numbers as a CBAM boundary result.
        """
        if derivation is None:
            return
        cited = derivation.basis.get("method_packages") or []
        if not any(
            (item.get("package_id"), item.get("version"))
            == (package.package_id, package.version)
            for item in cited
        ):
            raise DomainError(
                code="CBAM_TRIAL_DERIVATION_METHOD_MISMATCH",
                message="此结果是在另一个核算口径下计算的，不能作为本次 CBAM 试算的输入；请用该口径重新计算。",
                status_code=409,
                details={
                    "solved_snapshot_id": snapshot.id,
                    "calculation_purpose": derivation.purpose,
                    "requested_method_package": f"{package.package_id}@{package.version}",
                    "derivation_method_packages": sorted(
                        f"{item.get('package_id')}@{item.get('version')}" for item in cited
                    ),
                },
            )

    @staticmethod
    def _require_recorded_selection(
        db: Any,
        snapshot: SolvedSystemSnapshot,
        flow_selection: dict[str, Any] | None,
    ) -> None:
        """Read the answer back under the emission selection the frozen solve itself recorded.

        The calculation basis pins the reviewed rules by content hash, so a re-derivation cannot pick a
        different set silently; the basis is deliberately not extended, because its hash is what already
        accepted runs replay against. The set itself is therefore read from the run's own solve receipt
        and compared with what this reading derives: a run that recorded no selection while its rules now
        classify exchanges was solved from a model that was never pruned, so its number describes a
        different boundary than the one this reading would report.
        """
        if derivation_basis_from_receipt(snapshot.provider_receipt) is None:
            # A pre-purpose answer recorded no derivation anywhere, and its frozen model identity is
            # the whole stored model, so there is no selection to agree on.
            return
        run_id = (snapshot.provider_receipt or {}).get("analysis_run_id")
        run = db.get(AnalysisRun, run_id) if isinstance(run_id, str) else None
        stamp = (run.provider_receipt or {}).get("model_derivation") if run else None
        if not isinstance(stamp, dict):
            # A derivation that cannot be reached is not a derivation that decided nothing: that is
            # exactly the case where a counted emission set could go missing.
            raise DomainError(
                code="CBAM_TRIAL_DERIVATION_UNRESOLVED",
                message="此结果找不到它当时求解记录的派生依据，无法核对它计入的排放集合，不能读取。",
                status_code=409,
                details={
                    "solved_snapshot_id": snapshot.id,
                    "analysis_run_id": run_id,
                },
            )
        recorded = stamp.get("flow_selection")
        if recorded != flow_selection:
            raise DomainError(
                code="CBAM_TRIAL_FLOW_SELECTION_UNRECORDED",
                message="此结果冻结时记录的排放选择与当前核算口径派生出的选择不一致，不能按本次口径读取；"
                "请用该口径重新计算。",
                status_code=409,
                details={
                    "solved_snapshot_id": snapshot.id,
                    "recorded_flow_selection": recorded,
                    "derived_flow_selection": flow_selection,
                },
            )

    def _frozen_graph(
        self,
        db: Any,
        snapshot: SolvedSystemSnapshot,
        derivation: PurposeDerivation | None = None,
    ) -> dict[str, Any]:
        revision = db.get(SystemRevision, snapshot.system_revision_id)
        if revision is None:
            raise DomainError(
                code="CBAM_TRIAL_FROZEN_MODEL_DRIFT",
                message="the solved snapshot points at a system revision that no longer exists",
                status_code=409,
                details={"system_revision_id": snapshot.system_revision_id},
            )
        if derivation is not None:
            return derivation.derived.graph
        return revision.graph_snapshot

    def _revision_identity(
        self,
        db: Any,
        snapshot: SolvedSystemSnapshot,
        derivation: PurposeDerivation | None = None,
    ) -> dict[str, Any]:
        revision = db.get(SystemRevision, snapshot.system_revision_id)
        model = None if revision is None else db.get(SystemModel, revision.system_model_id)
        if revision is None or model is None:
            raise DomainError(
                code="CBAM_TRIAL_FROZEN_MODEL_DRIFT",
                message="the solved snapshot has no resolvable frozen model identity",
                status_code=409,
                details={"system_revision_id": snapshot.system_revision_id},
            )
        identity = {
            "system_revision_id": revision.id,
            "graph_sha256": revision.graph_sha256,
            "upstream_project_id": model.upstream_project_id,
            "upstream_version": model.upstream_version,
        }
        if derivation is not None:
            if derivation.derived.source_graph_sha256 != revision.graph_sha256:
                raise DomainError(
                    code="CBAM_TRIAL_DERIVATION_UNRESOLVED",
                    message="此结果的计算依据不是由当前冻结模型派生的，不能读取。",
                    status_code=409,
                    details={
                        "solved_snapshot_id": snapshot.id,
                        "basis_source_graph_sha256": derivation.derived.source_graph_sha256,
                        "revision_graph_sha256": revision.graph_sha256,
                    },
                )
            # The frozen boundary was pinned to the stored project graph, so that pin keeps its own
            # field once graph_sha256 names the purpose's calculation model instead.
            identity["source_graph_sha256"] = revision.graph_sha256
            identity["graph_sha256"] = derivation.derived.derived_graph_sha256
            identity["calculation_purpose"] = derivation.purpose
            identity["model_derivation_basis_sha256"] = derivation.basis_sha256
        return identity

    def _boundary(
        self, db: Any, snapshot: SolvedSystemSnapshot, boundary_id: str | None
    ) -> dict[str, Any]:
        if not boundary_id:
            raise DomainError(
                code="CBAM_TRIAL_BOUNDARY_REFERENCE_REQUIRED",
                message="cbam.trial.v2 names the frozen boundary it computes against",
                status_code=422,
                details={"solved_snapshot_id": snapshot.id},
            )
        record = db.get(BoundaryDefinition, boundary_id)
        if record is None:
            raise DomainError(
                code="CBAM_TRIAL_BOUNDARY_NOT_FROZEN",
                message=f"boundary definition not found: {boundary_id}",
                status_code=404,
            )
        return {
            "id": record.id,
            "application_id": record.application_id,
            "name": record.name,
            "boundary_type": record.boundary_type,
            "included_entity_ids": record.included_entity_ids,
            "included_process_ids": record.included_process_ids,
            "included_flow_rules": record.included_flow_rules,
            "excluded_items": record.excluded_items,
            "consolidation_policy": record.consolidation_policy,
            "period_id": record.period_id,
            "geographic_scope": record.geographic_scope,
            "method_package_ref": record.method_package_ref,
            "content_sha256": record.content_sha256,
            "status": record.status,
            "frozen_at": record.frozen_at.isoformat() if record.frozen_at else None,
        }
