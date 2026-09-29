from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from ..errors import DomainError
from ..hashing import canonical_json_sha256
from .contracts import InlineEnginePin, StrictContract, canonical_contract_sha256
from .loader import LoadedCasePack


class ResolvedCase(StrictContract):
    schema_version: Literal["nebula.resolved-case.v1"]
    case_pack_id: str
    case_pack_version: str
    case_pack_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    application_case_id: str
    application_case_version: str
    application_case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    study_frame_id: str
    study_frame_version: str
    study_frame_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    demand_definition_id: str
    demand_definition_version: str
    demand_definition_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    demand_type: str
    demand: tuple[dict[str, Any], ...]
    reporting_period_id: str
    reporting_period_version: str
    reporting_period_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parameter_binding: dict[str, Any] | None
    parameter_sets: tuple[dict[str, Any], ...]
    capabilities: tuple[str, ...]
    blocked_capabilities: tuple[dict[str, str], ...]
    method_packages: tuple[dict[str, str], ...]
    engine: dict[str, Any]
    shared_releases: dict[str, Any]
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CaseRunRevisionRef(StrictContract):
    system_revision_id: str = Field(min_length=1, max_length=255)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    graph_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CaseCapabilityRun(StrictContract):
    capability: str = Field(min_length=1, max_length=255)
    status: Literal["passed", "blocked", "failed"]
    result_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    audit_status: str | None = None
    error: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_status_payload(self):
        if self.status == "passed" and self.result_sha256 is None:
            raise ValueError("passed capability requires result_sha256")
        if self.status != "passed" and self.error is None:
            raise ValueError("blocked or failed capability requires error")
        return self


class CaseArtifactReceipt(StrictContract):
    path: str = Field(min_length=1, max_length=1024)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CaseRunManifest(StrictContract):
    schema_version: Literal["nebula.case-run-manifest.v1"]
    run_id: str = Field(min_length=1, max_length=255)
    status: Literal["succeeded", "partial", "failed"]
    resolved_case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    study_frame_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    demand_definition_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    declared_capabilities: tuple[str, ...] = Field(min_length=1)
    revision_refs: tuple[CaseRunRevisionRef, ...] = Field(min_length=1)
    capability_runs: tuple[CaseCapabilityRun, ...] = Field(min_length=1)
    artifact_receipts: tuple[CaseArtifactReceipt, ...] = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def verify_content_hash(self):
        revision_ids = [item.system_revision_id for item in self.revision_refs]
        capabilities = [item.capability for item in self.capability_runs]
        artifact_paths = [item.path for item in self.artifact_receipts]
        if len(revision_ids) != len(set(revision_ids)):
            raise ValueError("CaseRun revision_refs must be unique")
        if len(capabilities) != len(set(capabilities)):
            raise ValueError("CaseRun capability_runs must be unique")
        if len(self.declared_capabilities) != len(set(self.declared_capabilities)):
            raise ValueError("CaseRun declared_capabilities must be unique")
        if set(capabilities) != set(self.declared_capabilities):
            raise ValueError(
                "CaseRun capability_runs must exactly match declared_capabilities"
            )
        if len(artifact_paths) != len(set(artifact_paths)):
            raise ValueError("CaseRun artifact_receipts paths must be unique")
        failed_or_blocked = [
            item for item in self.capability_runs if item.status != "passed"
        ]
        if self.status == "succeeded" and failed_or_blocked:
            raise ValueError("succeeded CaseRun cannot contain blocked or failed capabilities")
        if self.status == "partial" and not failed_or_blocked:
            raise ValueError("partial CaseRun requires a blocked or failed capability")
        if self.status == "partial" and len(failed_or_blocked) == len(self.capability_runs):
            raise ValueError("partial CaseRun requires at least one passed capability")
        if self.status == "failed" and not any(
            item.status == "failed" for item in self.capability_runs
        ):
            raise ValueError("failed CaseRun requires a failed capability")
        basis = self.model_dump(mode="json", exclude={"content_sha256"})
        if canonical_json_sha256(basis) != self.content_sha256:
            raise ValueError("CaseRun manifest content hash mismatch")
        return self


def create_case_run_manifest(**payload: Any) -> CaseRunManifest:
    basis = {
        "schema_version": "nebula.case-run-manifest.v1",
        **{
            key: value
            for key, value in payload.items()
            if key not in {"revision_refs", "capability_runs", "artifact_receipts"}
        },
        "revision_refs": [
            CaseRunRevisionRef.model_validate(item).model_dump(mode="json")
            for item in payload.get("revision_refs", [])
        ],
        "capability_runs": [
            CaseCapabilityRun.model_validate(item).model_dump(mode="json")
            for item in payload.get("capability_runs", [])
        ],
        "artifact_receipts": [
            CaseArtifactReceipt.model_validate(item).model_dump(mode="json")
            for item in payload.get("artifact_receipts", [])
        ],
    }
    return CaseRunManifest(
        **basis,
        content_sha256=canonical_json_sha256(basis),
    )


def _fail(code: str, message: str, **details: Any) -> None:
    raise DomainError(code=code, message=message, status_code=422, details=details)


def _inline_snapshot_has_elementary_refs(
    loaded: LoadedCasePack, engine: InlineEnginePin
) -> bool:
    snapshot = dict(loaded.supporting_documents).get(engine.snapshot_path)
    if not isinstance(snapshot, dict):
        return False
    graph = snapshot.get("graph")
    metadata = graph.get("metadata") if isinstance(graph, dict) else None
    refs = metadata.get("elementary_flow_refs") if isinstance(metadata, dict) else None
    return isinstance(refs, list) and bool(refs)


def resolve_case(loaded: LoadedCasePack, application_case_id: str) -> ResolvedCase:
    applications = [
        item
        for item in loaded.application_cases
        if item.application_case.id == application_case_id
    ]
    if len(applications) != 1:
        _fail(
            "CASE_APPLICATION_NOT_FOUND",
            "ApplicationCase identity must resolve exactly once",
            application_case_id=application_case_id,
        )
    application = applications[0]
    if application.application_case.lifecycle_status != "executable":
        _fail(
            "CASE_APPLICATION_NOT_EXECUTABLE",
            "ApplicationCase must be executable before resolution",
            application_case_id=application_case_id,
        )
    frame = application.study_frame
    if frame.study_frame.lifecycle_status != "frozen":
        _fail(
            "CASE_STUDY_FRAME_NOT_FROZEN",
            "StudyFrame must be frozen before resolution",
            study_frame_id=frame.study_frame.id,
        )
    demand_ref = frame.demand_definition_ref
    demands = [
        item
        for item in loaded.demand_definitions
        if (item.demand_definition.id, item.demand_definition.version)
        == (demand_ref.id, demand_ref.version)
    ]
    if len(demands) != 1:
        _fail(
            "CASE_DEMAND_NOT_FOUND",
            "DemandDefinition identity must resolve exactly once",
            demand_definition_id=demand_ref.id,
            demand_definition_version=demand_ref.version,
        )
    demand = demands[0]
    if demand.execution_status != "supported":
        _fail(
            "CASE_DEMAND_NOT_SUPPORTED",
            "DemandDefinition is not executable by this release",
            demand_type=demand.demand_type,
        )

    reporting_period_ref = frame.reporting_period_ref
    periods = [
        item
        for item in loaded.reporting_periods
        if (item.reporting_period.id, item.reporting_period.version)
        == (reporting_period_ref.id, reporting_period_ref.version)
    ]
    if len(periods) != 1:
        _fail(
            "CASE_REPORTING_PERIOD_NOT_FOUND",
            "ReportingPeriod identity must resolve exactly once",
            reporting_period_id=reporting_period_ref.id,
            reporting_period_version=reporting_period_ref.version,
        )
    reporting_period = periods[0]

    binding_receipt: dict[str, Any] | None = None
    binding_ref = application.scenario.parameter_binding_ref
    if binding_ref is not None:
        bindings = [
            item
            for item in loaded.parameter_bindings
            if (item.parameter_binding.id, item.parameter_binding.version)
            == (binding_ref.id, binding_ref.version)
        ]
        if len(bindings) != 1:
            _fail(
                "CASE_PARAMETER_BINDING_NOT_FOUND",
                "ParameterBinding identity must resolve exactly once",
                parameter_binding_id=binding_ref.id,
            )
        binding_receipt = {
            "id": binding_ref.id,
            "version": binding_ref.version,
            "content_sha256": canonical_contract_sha256(bindings[0]),
        }
    parameter_set_receipts: list[dict[str, Any]] = []
    for parameter_set_ref in application.scenario.parameter_set_refs:
        parameter_sets = [
            item
            for item in loaded.parameter_sets
            if (item.parameter_set.id, item.parameter_set.version)
            == (parameter_set_ref.id, parameter_set_ref.version)
        ]
        if len(parameter_sets) != 1:
            _fail(
                "CASE_PARAMETER_SET_NOT_FOUND",
                "Case ParameterSet identity must resolve exactly once",
                parameter_set_id=parameter_set_ref.id,
            )
        parameter_set_receipts.append(
            {
                "id": parameter_set_ref.id,
                "version": parameter_set_ref.version,
                "content_sha256": parameter_sets[0].content_sha256,
            }
        )

    engine = loaded.case_pack.engine
    if engine is None:
        _fail("CASE_ENGINE_PIN_MISSING", "executable case requires an engine pin")
    blocked_capabilities: list[dict[str, str]] = []
    if (
        isinstance(engine, InlineEnginePin)
        and "lcia.nebula.v1" in application.analysis_plan.capabilities
        and not _inline_snapshot_has_elementary_refs(loaded, engine)
    ):
        blocked_capabilities.append(
            {
                "capability": "lcia.nebula.v1",
                "code": "ELEMENTARY_FLOW_REFERENCE_REQUIRED",
                "reason": "inline LCIA requires exact elementary Flow references",
            }
        )

    supporting_documents = dict(loaded.supporting_documents)
    method_packages: list[dict[str, str]] = []
    for reference in application.analysis_plan.method_package_refs:
        package = supporting_documents.get(reference.path)
        if not isinstance(package, dict):
            _fail(
                "CASE_METHOD_PACKAGE_NOT_FOUND",
                "ApplicationCase method package is not registered as a supporting document",
                reference=reference.path,
            )
        if (
            str(package.get("package_id") or "").strip() != reference.id
            or str(package.get("version") or "").strip() != reference.version
        ):
            _fail(
                "CASE_METHOD_PACKAGE_IDENTITY_MISMATCH",
                "ApplicationCase method package identity differs from its reference",
                reference=reference.path,
            )
        method_packages.append(
            {
                "path": reference.path,
                "package_id": reference.id,
                "version": reference.version,
                "content_sha256": canonical_json_sha256(package),
            }
        )

    demand_payload = tuple(
        {
            "reference_flow_uuid": item.reference_flow_uuid,
            "reference_exchange_id": item.reference_exchange_id,
            "amount": item.amount,
            "unit": item.unit,
            "unit_group_uuid": item.unit_group_uuid,
            "unit_group_version": item.unit_group_version,
        }
        for item in demand.demands
    )
    application_hash = canonical_contract_sha256(application)
    demand_hash = canonical_contract_sha256(demand)
    reporting_period_hash = canonical_contract_sha256(reporting_period)
    study_frame_basis = {
        "study_frame": frame.model_dump(mode="json"),
        "demand_definition_sha256": demand_hash,
        "reporting_period_sha256": reporting_period_hash,
        "parameter_binding": binding_receipt,
        "parameter_sets": parameter_set_receipts,
        "engine": engine.model_dump(mode="json"),
        "shared_releases": loaded.case_pack.shared_releases.model_dump(mode="json"),
    }
    study_frame_hash = canonical_json_sha256(study_frame_basis)
    basis = {
        "schema_version": "nebula.resolved-case.v1",
        "case_pack_id": loaded.case_pack.case_pack.id,
        "case_pack_version": loaded.case_pack.case_pack.version,
        "case_pack_sha256": loaded.receipt.case_pack_sha256,
        "application_case_id": application.application_case.id,
        "application_case_version": application.application_case.version,
        "application_case_sha256": application_hash,
        "study_frame_id": frame.study_frame.id,
        "study_frame_version": frame.study_frame.version,
        "study_frame_sha256": study_frame_hash,
        "demand_definition_id": demand.demand_definition.id,
        "demand_definition_version": demand.demand_definition.version,
        "demand_definition_sha256": demand_hash,
        "demand_type": demand.demand_type,
        "demand": demand_payload,
        "reporting_period_id": reporting_period.reporting_period.id,
        "reporting_period_version": reporting_period.reporting_period.version,
        "reporting_period_sha256": reporting_period_hash,
        "parameter_binding": binding_receipt,
        "parameter_sets": tuple(parameter_set_receipts),
        "capabilities": application.analysis_plan.capabilities,
        "blocked_capabilities": tuple(blocked_capabilities),
        "method_packages": tuple(method_packages),
        "engine": engine.model_dump(mode="json"),
        "shared_releases": loaded.case_pack.shared_releases.model_dump(mode="json"),
    }
    return ResolvedCase(**basis, content_sha256=canonical_json_sha256(basis))
