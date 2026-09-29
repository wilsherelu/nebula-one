from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, ValidationError

from ..errors import DomainError
from ..hashing import canonical_json_sha256
from .contracts import (
    ApplicationCaseDocument,
    CasePackDocument,
    DemandDefinitionDocument,
    InlineEnginePin,
    ReportingPeriodDocument,
    canonical_contract_sha256,
    parse_application_case,
    parse_casepack,
    parse_demand_definition,
    parse_reporting_period,
)
from .bindings import (
    CaseParameterSetDocument,
    ParameterBindingDocument,
    parse_case_parameter_set,
    parse_parameter_binding,
)
from .licenses import LicenseManifestDocument, parse_license_manifest
from .provider_candidates import (
    ProviderCandidateManifest,
    parse_provider_candidate_manifest,
)
from .physical_properties import (
    PhysicalPropertySetDocument,
    PhysicalPropertyValidationError,
    PublishedPhysicalPropertySourceRecord,
    parse_physical_property_set,
    parse_published_physical_property_source,
    validate_physical_property_source_records,
)
from .spatial import EntityRegistryDocument, parse_entity_registry


ContractT = TypeVar("ContractT", bound=BaseModel)


class CasePackLoadError(DomainError):
    pass


class SourceFileReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    file_sha256: str
    canonical_sha256: str
    schema_version: str
    object_kind: Literal[
        "case_pack",
        "application_case",
        "demand_definition",
        "parameter_binding",
        "parameter_set",
        "reporting_period",
        "license_manifest",
        "provider_candidate_manifest",
        "physical_property_set",
        "published_physical_property_source",
        "entity_registry",
        "supporting_document",
    ]
    object_id: str | None = None
    object_version: str | None = None


class CasePackLoadReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["nebula.casepack.load-receipt.v1"]
    case_pack_id: str
    case_pack_version: str
    case_pack_contract_sha256: str
    source_files: tuple[SourceFileReceipt, ...]
    issues: tuple[dict[str, Any], ...]
    case_pack_sha256: str


@dataclass(frozen=True, slots=True)
class LoadedCasePack:
    case_pack: CasePackDocument
    application_cases: tuple[ApplicationCaseDocument, ...]
    demand_definitions: tuple[DemandDefinitionDocument, ...]
    parameter_bindings: tuple[ParameterBindingDocument, ...]
    parameter_sets: tuple[CaseParameterSetDocument, ...]
    reporting_periods: tuple[ReportingPeriodDocument, ...]
    license_manifest: LicenseManifestDocument
    provider_candidate_manifests: tuple[ProviderCandidateManifest, ...]
    physical_property_sets: tuple[PhysicalPropertySetDocument, ...]
    published_physical_property_sources: tuple[
        PublishedPhysicalPropertySourceRecord, ...
    ]
    entity_registries: tuple[EntityRegistryDocument, ...]
    supporting_documents: tuple[tuple[str, dict[str, Any]], ...]
    receipt: CasePackLoadReceipt


def _fail(code: str, message: str, **details: Any) -> None:
    raise CasePackLoadError(
        code=code,
        message=message,
        status_code=422,
        details=details,
    )


def _resolve_root(root: str | Path) -> Path:
    requested = Path(root)
    try:
        resolved = requested.resolve(strict=True)
    except OSError as exc:
        raise CasePackLoadError(
            code="CASEPACK_ROOT_INVALID",
            message=f"CasePack root does not exist: {requested}",
            status_code=404,
        ) from exc
    if not resolved.is_dir():
        _fail("CASEPACK_ROOT_INVALID", "CasePack root must be a directory")
    return resolved


def _resolve_file(root: Path, reference: str) -> tuple[Path, str]:
    raw = reference.strip()
    if not raw:
        _fail("CASEPACK_PATH_INVALID", "CasePack file reference cannot be blank")
    relative = Path(raw)
    if relative.is_absolute() or relative.drive:
        _fail(
            "CASEPACK_PATH_ESCAPE",
            "CasePack file reference must be relative",
            reference=reference,
        )
    if ".." in relative.parts:
        _fail(
            "CASEPACK_PATH_TRAVERSAL",
            "CasePack file reference cannot contain parent traversal",
            reference=reference,
        )
    normalized = Path(*[part for part in relative.parts if part not in {"", "."}])
    if not normalized.parts or normalized.suffix.lower() != ".json":
        _fail(
            "CASEPACK_PATH_INVALID",
            "CasePack source files must be JSON files",
            reference=reference,
        )
    candidate = root / normalized
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise CasePackLoadError(
            code="CASEPACK_FILE_MISSING",
            message=f"CasePack source file does not exist: {normalized.as_posix()}",
            status_code=422,
            details={"reference": normalized.as_posix()},
        ) from exc
    try:
        resolved.relative_to(root)
    except ValueError:
        _fail(
            "CASEPACK_SYMLINK_ESCAPE",
            "CasePack source file resolves outside the CasePack root",
            reference=normalized.as_posix(),
        )
    if not resolved.is_file():
        _fail(
            "CASEPACK_FILE_INVALID",
            "CasePack source reference must resolve to a regular file",
            reference=normalized.as_posix(),
        )
    return resolved, normalized.as_posix()


def _read_json(root: Path, reference: str) -> tuple[dict[str, Any], bytes, str]:
    path, normalized = _resolve_file(root, reference)
    content = path.read_bytes()
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CasePackLoadError(
            code="CASEPACK_JSON_INVALID",
            message=f"CasePack source is not valid UTF-8 JSON: {normalized}",
            status_code=422,
            details={"reference": normalized},
        ) from exc
    if not isinstance(payload, dict):
        _fail(
            "CASEPACK_JSON_INVALID",
            "CasePack source root must be a JSON object",
            reference=normalized,
        )
    return payload, content, normalized


def _parse_contract(
    parser: Callable[[Any], ContractT], payload: dict[str, Any], reference: str
) -> ContractT:
    try:
        return parser(payload)
    except ValidationError as exc:
        raise CasePackLoadError(
            code="CASEPACK_CONTRACT_INVALID",
            message=f"CasePack contract validation failed: {reference}",
            status_code=422,
            details={"reference": reference, "errors": exc.errors(include_url=False)},
        ) from exc


def _source_receipt(
    *,
    reference: str,
    content: bytes,
    payload: dict[str, Any],
    object_kind: Literal[
        "case_pack",
        "application_case",
        "demand_definition",
        "parameter_binding",
        "license_manifest",
        "provider_candidate_manifest",
        "physical_property_set",
        "supporting_document",
    ],
    contract: (
        CasePackDocument
        | ApplicationCaseDocument
        | DemandDefinitionDocument
        | ParameterBindingDocument
        | LicenseManifestDocument
        | ProviderCandidateManifest
        | PhysicalPropertySetDocument
        | None
    ),
    object_id: str | None,
    object_version: str | None,
) -> SourceFileReceipt:
    return SourceFileReceipt(
        path=reference,
        file_sha256=hashlib.sha256(content).hexdigest(),
        canonical_sha256=(
            canonical_contract_sha256(contract)
            if contract is not None
            else canonical_json_sha256(payload)
        ),
        schema_version=str(payload.get("schema_version") or "unversioned"),
        object_kind=object_kind,
        object_id=object_id,
        object_version=object_version,
    )


def _register_path(registered: set[str], reference: str) -> None:
    normalized = Path(reference).as_posix()
    if normalized in registered:
        _fail(
            "CASEPACK_REFERENCE_DUPLICATE",
            "CasePack source file is registered more than once",
            reference=normalized,
        )
    registered.add(normalized)


def load_casepack(root: str | Path) -> LoadedCasePack:
    resolved_root = _resolve_root(root)
    source_receipts: list[SourceFileReceipt] = []
    registered_paths: set[str] = set()
    supporting_documents: list[tuple[str, dict[str, Any]]] = []

    casepack_payload, casepack_content, casepack_path = _read_json(
        resolved_root, "casepack.json"
    )
    casepack = _parse_contract(parse_casepack, casepack_payload, casepack_path)
    _register_path(registered_paths, casepack_path)
    source_receipts.append(
        _source_receipt(
            reference=casepack_path,
            content=casepack_content,
            payload=casepack_payload,
            object_kind="case_pack",
            contract=casepack,
            object_id=casepack.case_pack.id,
            object_version=casepack.case_pack.version,
        )
    )

    license_payload, license_content, license_path = _read_json(
        resolved_root, casepack.licenses.manifest
    )
    _register_path(registered_paths, license_path)
    license_manifest = _parse_contract(
        parse_license_manifest, license_payload, license_path
    )
    if license_manifest.case_pack_id != casepack.case_pack.id:
        _fail(
            "CASEPACK_LICENSE_ID_MISMATCH",
            "license manifest belongs to a different CasePack",
            expected=casepack.case_pack.id,
            actual=license_manifest.case_pack_id,
        )
    if (
        casepack.case_pack.lifecycle_status == "executable"
        and license_manifest.publication_gate != "eligible"
    ):
        _fail(
            "CASEPACK_LICENSE_GATE_BLOCKED",
            "an executable CasePack requires an eligible license manifest",
        )
    source_receipts.append(
        _source_receipt(
            reference=license_path,
            content=license_content,
            payload=license_payload,
            object_kind="license_manifest",
            contract=license_manifest,
            object_id=license_manifest.case_pack_id,
            object_version=license_manifest.manifest_version,
        )
    )
    licensed_paths: set[str] = set()
    for asset in license_manifest.assets:
        for evidence in asset.files:
            evidence_path, normalized = _resolve_file(resolved_root, evidence.path)
            actual_sha256 = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
            if actual_sha256 != evidence.file_sha256:
                _fail(
                    "CASEPACK_LICENSE_HASH_MISMATCH",
                    "license evidence hash does not match the source file",
                    reference=normalized,
                    expected=evidence.file_sha256,
                    actual=actual_sha256,
                )
            licensed_paths.add(normalized)

    provider_candidate_manifests: list[ProviderCandidateManifest] = []
    physical_property_sets: list[PhysicalPropertySetDocument] = []
    published_physical_property_sources: list[
        PublishedPhysicalPropertySourceRecord
    ] = []
    entity_registries: list[EntityRegistryDocument] = []
    generic_refs = casepack.supporting_file_refs
    for reference in generic_refs:
        payload, content, normalized = _read_json(resolved_root, reference)
        _register_path(registered_paths, normalized)
        if payload.get("schema_version") == "nebula.provider-candidate-manifest.v1":
            manifest = _parse_contract(
                parse_provider_candidate_manifest, payload, normalized
            )
            if manifest.case_pack_id != casepack.case_pack.id:
                _fail(
                    "CASEPACK_REFERENCE_MISMATCH",
                    "provider candidate manifest belongs to a different CasePack",
                    reference=normalized,
                )
            provider_candidate_manifests.append(manifest)
            source_receipts.append(
                _source_receipt(
                    reference=normalized,
                    content=content,
                    payload=payload,
                    object_kind="provider_candidate_manifest",
                    contract=manifest,
                    object_id=manifest.case_pack_id,
                    object_version=None,
                )
            )
            continue
        if payload.get("schema_version") == "nebula.physical-property-set.v1":
            property_set = _parse_contract(
                parse_physical_property_set, payload, normalized
            )
            if property_set.case_pack_id != casepack.case_pack.id:
                _fail(
                    "CASEPACK_REFERENCE_MISMATCH",
                    "physical property set belongs to a different CasePack",
                    reference=normalized,
                )
            physical_property_sets.append(property_set)
            source_receipts.append(
                _source_receipt(
                    reference=normalized,
                    content=content,
                    payload=payload,
                    object_kind="physical_property_set",
                    contract=property_set,
                    object_id=property_set.physical_property_set.id,
                    object_version=property_set.physical_property_set.version,
                )
            )
            continue
        if (
            payload.get("schema_version")
            == "nebula.published-physical-property-source.v1"
        ):
            source_record = _parse_contract(
                parse_published_physical_property_source,
                payload,
                normalized,
            )
            published_physical_property_sources.append(source_record)
            source_receipts.append(
                _source_receipt(
                    reference=normalized,
                    content=content,
                    payload=payload,
                    object_kind="published_physical_property_source",
                    contract=source_record,
                    object_id=source_record.source_record_id,
                    object_version=source_record.source_version,
                )
            )
            continue
        if payload.get("schema_version") == "nebula.entity-registry.v2":
            registry = _parse_contract(parse_entity_registry, payload, normalized)
            entity_registries.append(registry)
            supporting_documents.append((normalized, payload))
            source_receipts.append(
                _source_receipt(
                    reference=normalized,
                    content=content,
                    payload=payload,
                    object_kind="entity_registry",
                    contract=registry,
                    object_id=registry.registry.id,
                    object_version=registry.registry.version,
                )
            )
            continue
        supporting_documents.append((normalized, payload))
        source_receipts.append(
            _source_receipt(
                reference=normalized,
                content=content,
                payload=payload,
                object_kind="supporting_document",
                contract=None,
                object_id=None,
                object_version=None,
            )
        )

    try:
        validate_physical_property_source_records(
            physical_property_sets,
            published_physical_property_sources,
        )
    except PhysicalPropertyValidationError as exc:
        _fail(exc.code, exc.message, **exc.details)

    if isinstance(casepack.engine, InlineEnginePin):
        snapshot_path = Path(casepack.engine.snapshot_path).as_posix()
        snapshot_payload = dict(supporting_documents).get(snapshot_path)
        if snapshot_payload is None:
            _fail(
                "CASEPACK_INLINE_SNAPSHOT_UNREGISTERED",
                "inline engine snapshot must be listed in supporting_file_refs",
                reference=snapshot_path,
            )
        if snapshot_payload.get("schema_version") != "provider.snapshot.v1":
            _fail(
                "CASEPACK_INLINE_SNAPSHOT_INVALID",
                "inline engine snapshot must use provider.snapshot.v1",
                reference=snapshot_path,
            )
        snapshot_graph = snapshot_payload.get("graph")
        if not isinstance(snapshot_graph, dict):
            _fail(
                "CASEPACK_INLINE_SNAPSHOT_INVALID",
                "inline engine snapshot must contain a graph object",
                reference=snapshot_path,
            )
        actual_graph_sha256 = canonical_json_sha256(snapshot_graph)
        declared_graph_sha256 = snapshot_payload.get("graph_hash")
        expected_graph_sha256 = casepack.engine.expected_graph_sha256
        if (
            declared_graph_sha256 != expected_graph_sha256
            or actual_graph_sha256 != expected_graph_sha256
        ):
            _fail(
                "CASEPACK_INLINE_SNAPSHOT_HASH_MISMATCH",
                "inline engine snapshot graph hash does not match the CasePack pin",
                reference=snapshot_path,
                expected=expected_graph_sha256,
                declared=declared_graph_sha256,
                actual=actual_graph_sha256,
            )

    application_cases: list[ApplicationCaseDocument] = []
    application_identities: set[tuple[str, str]] = set()
    study_frame_identities: set[tuple[str, str]] = set()
    demand_refs: dict[str, tuple[str, str]] = {}
    binding_refs: dict[str, tuple[str, str]] = {}
    parameter_set_refs: dict[str, tuple[str, str]] = {}
    reporting_period_refs: dict[str, tuple[str, str]] = {}
    for expected_ref in casepack.application_case_refs:
        payload, content, normalized = _read_json(resolved_root, expected_ref.path)
        _register_path(registered_paths, normalized)
        application = _parse_contract(parse_application_case, payload, normalized)
        actual_identity = (
            application.application_case.id,
            application.application_case.version,
        )
        expected_identity = (expected_ref.id, expected_ref.version)
        if actual_identity != expected_identity:
            _fail(
                "CASEPACK_REFERENCE_MISMATCH",
                "ApplicationCase identity does not match its registered reference",
                reference=normalized,
                expected=list(expected_identity),
                actual=list(actual_identity),
            )
        if actual_identity in application_identities:
            _fail(
                "CASEPACK_IDENTITY_DUPLICATE",
                "duplicate ApplicationCase identity",
                identity=list(actual_identity),
            )
        application_identities.add(actual_identity)
        frame_identity = (
            application.study_frame.study_frame.id,
            application.study_frame.study_frame.version,
        )
        if frame_identity in study_frame_identities:
            _fail(
                "CASEPACK_IDENTITY_DUPLICATE",
                "duplicate StudyFrame identity",
                identity=list(frame_identity),
            )
        study_frame_identities.add(frame_identity)
        demand_ref = application.study_frame.demand_definition_ref
        demand_identity = (demand_ref.id, demand_ref.version)
        previous_identity = demand_refs.get(demand_ref.path)
        if previous_identity is not None and previous_identity != demand_identity:
            _fail(
                "CASEPACK_REFERENCE_MISMATCH",
                "one demand path is registered with conflicting identities",
                reference=demand_ref.path,
            )
        demand_refs[demand_ref.path] = demand_identity
        reporting_period_ref = application.study_frame.reporting_period_ref
        reporting_period_identity = (
            reporting_period_ref.id,
            reporting_period_ref.version,
        )
        previous_reporting_period_identity = reporting_period_refs.get(
            reporting_period_ref.path
        )
        if (
            previous_reporting_period_identity is not None
            and previous_reporting_period_identity != reporting_period_identity
        ):
            _fail(
                "CASEPACK_REFERENCE_MISMATCH",
                "one ReportingPeriod path is registered with conflicting identities",
                reference=reporting_period_ref.path,
            )
        reporting_period_refs[reporting_period_ref.path] = reporting_period_identity
        binding_ref = application.scenario.parameter_binding_ref
        if binding_ref is not None:
            binding_identity = (binding_ref.id, binding_ref.version)
            previous_binding_identity = binding_refs.get(binding_ref.path)
            if (
                previous_binding_identity is not None
                and previous_binding_identity != binding_identity
            ):
                _fail(
                    "CASEPACK_REFERENCE_MISMATCH",
                    "one ParameterBinding path is registered with conflicting identities",
                    reference=binding_ref.path,
                )
            binding_refs[binding_ref.path] = binding_identity
        for parameter_set_ref in application.scenario.parameter_set_refs:
            parameter_set_identity = (
                parameter_set_ref.id,
                parameter_set_ref.version,
            )
            previous_parameter_set_identity = parameter_set_refs.get(
                parameter_set_ref.path
            )
            if (
                previous_parameter_set_identity is not None
                and previous_parameter_set_identity != parameter_set_identity
            ):
                _fail(
                    "CASEPACK_REFERENCE_MISMATCH",
                    "one Case ParameterSet path is registered with conflicting identities",
                    reference=parameter_set_ref.path,
                )
            parameter_set_refs[parameter_set_ref.path] = parameter_set_identity
        application_cases.append(application)
        source_receipts.append(
            _source_receipt(
                reference=normalized,
                content=content,
                payload=payload,
                object_kind="application_case",
                contract=application,
                object_id=actual_identity[0],
                object_version=actual_identity[1],
            )
        )

    parameter_bindings: list[ParameterBindingDocument] = []
    binding_identities: set[tuple[str, str]] = set()
    for reference, expected_identity in sorted(binding_refs.items()):
        payload, content, normalized = _read_json(resolved_root, reference)
        _register_path(registered_paths, normalized)
        binding = _parse_contract(parse_parameter_binding, payload, normalized)
        actual_identity = (
            binding.parameter_binding.id,
            binding.parameter_binding.version,
        )
        if actual_identity != expected_identity:
            _fail(
                "CASEPACK_REFERENCE_MISMATCH",
                "ParameterBinding identity does not match its Scenario reference",
                reference=normalized,
                expected=list(expected_identity),
                actual=list(actual_identity),
            )
        if actual_identity in binding_identities:
            _fail(
                "CASEPACK_IDENTITY_DUPLICATE",
                "duplicate ParameterBinding identity",
                identity=list(actual_identity),
            )
        binding_identities.add(actual_identity)
        parameter_bindings.append(binding)
        source_receipts.append(
            _source_receipt(
                reference=normalized,
                content=content,
                payload=payload,
                object_kind="parameter_binding",
                contract=binding,
                object_id=actual_identity[0],
                object_version=actual_identity[1],
            )
        )

    parameter_sets: list[CaseParameterSetDocument] = []
    parameter_set_identities: set[tuple[str, str]] = set()
    for reference, expected_identity in sorted(parameter_set_refs.items()):
        payload, content, normalized = _read_json(resolved_root, reference)
        _register_path(registered_paths, normalized)
        parameter_set = _parse_contract(parse_case_parameter_set, payload, normalized)
        actual_identity = (
            parameter_set.parameter_set.id,
            parameter_set.parameter_set.version,
        )
        if actual_identity != expected_identity:
            _fail(
                "CASEPACK_REFERENCE_MISMATCH",
                "Case ParameterSet identity does not match its Scenario reference",
                reference=normalized,
                expected=list(expected_identity),
                actual=list(actual_identity),
            )
        if actual_identity in parameter_set_identities:
            _fail(
                "CASEPACK_IDENTITY_DUPLICATE",
                "duplicate Case ParameterSet identity",
                identity=list(actual_identity),
            )
        parameter_set_identities.add(actual_identity)
        parameter_sets.append(parameter_set)
        source_receipts.append(
            _source_receipt(
                reference=normalized,
                content=content,
                payload=payload,
                object_kind="parameter_set",
                contract=parameter_set,
                object_id=actual_identity[0],
                object_version=actual_identity[1],
            )
        )

    demand_definitions: list[DemandDefinitionDocument] = []
    demand_identities: set[tuple[str, str]] = set()
    for reference, expected_identity in sorted(demand_refs.items()):
        payload, content, normalized = _read_json(resolved_root, reference)
        _register_path(registered_paths, normalized)
        demand = _parse_contract(parse_demand_definition, payload, normalized)
        actual_identity = (
            demand.demand_definition.id,
            demand.demand_definition.version,
        )
        if actual_identity != expected_identity:
            _fail(
                "CASEPACK_REFERENCE_MISMATCH",
                "DemandDefinition identity does not match its StudyFrame reference",
                reference=normalized,
                expected=list(expected_identity),
                actual=list(actual_identity),
            )
        if actual_identity in demand_identities:
            _fail(
                "CASEPACK_IDENTITY_DUPLICATE",
                "duplicate DemandDefinition identity",
                identity=list(actual_identity),
            )
        demand_identities.add(actual_identity)
        demand_definitions.append(demand)
        source_receipts.append(
            _source_receipt(
                reference=normalized,
                content=content,
                payload=payload,
                object_kind="demand_definition",
                contract=demand,
                object_id=actual_identity[0],
                object_version=actual_identity[1],
            )
        )

    reporting_periods: list[ReportingPeriodDocument] = []
    reporting_period_identities: set[tuple[str, str]] = set()
    for reference, expected_identity in sorted(reporting_period_refs.items()):
        payload, content, normalized = _read_json(resolved_root, reference)
        _register_path(registered_paths, normalized)
        reporting_period = _parse_contract(
            parse_reporting_period, payload, normalized
        )
        actual_identity = (
            reporting_period.reporting_period.id,
            reporting_period.reporting_period.version,
        )
        if actual_identity != expected_identity:
            _fail(
                "CASEPACK_REFERENCE_MISMATCH",
                "ReportingPeriod identity does not match its StudyFrame reference",
                reference=normalized,
                expected=list(expected_identity),
                actual=list(actual_identity),
            )
        if actual_identity in reporting_period_identities:
            _fail(
                "CASEPACK_IDENTITY_DUPLICATE",
                "duplicate ReportingPeriod identity",
                identity=list(actual_identity),
            )
        reporting_period_identities.add(actual_identity)
        reporting_periods.append(reporting_period)
        source_receipts.append(
            _source_receipt(
                reference=normalized,
                content=content,
                payload=payload,
                object_kind="reporting_period",
                contract=reporting_period,
                object_id=actual_identity[0],
                object_version=actual_identity[1],
            )
        )

    discovered_paths: set[str] = set()
    for candidate in resolved_root.rglob("*"):
        if candidate.suffix.lower() != ".json":
            continue
        _, normalized = _resolve_file(
            resolved_root, candidate.relative_to(resolved_root).as_posix()
        )
        discovered_paths.add(normalized)
    unregistered = sorted(discovered_paths.difference(registered_paths))
    if unregistered:
        _fail(
            "CASEPACK_UNREGISTERED_DOCUMENT",
            "CasePack contains JSON documents that are not registered",
            references=unregistered,
        )
    expected_licensed_paths = discovered_paths.difference({license_path})
    missing_license_evidence = sorted(expected_licensed_paths.difference(licensed_paths))
    extra_license_evidence = sorted(licensed_paths.difference(expected_licensed_paths))
    if missing_license_evidence or extra_license_evidence:
        _fail(
            "CASEPACK_LICENSE_COVERAGE_MISMATCH",
            "license evidence must cover every CasePack JSON source exactly once",
            missing=missing_license_evidence,
            extra=extra_license_evidence,
        )

    ordered_sources = tuple(sorted(source_receipts, key=lambda item: item.path))
    casepack_contract_hash = canonical_contract_sha256(casepack)
    receipt_basis = {
        "schema_version": "nebula.casepack.load-receipt.v1",
        "case_pack_id": casepack.case_pack.id,
        "case_pack_version": casepack.case_pack.version,
        "case_pack_contract_sha256": casepack_contract_hash,
        "source_files": [item.model_dump(mode="json") for item in ordered_sources],
        "issues": [],
    }
    receipt = CasePackLoadReceipt(
        **receipt_basis,
        case_pack_sha256=canonical_json_sha256(receipt_basis),
    )
    return LoadedCasePack(
        case_pack=casepack,
        application_cases=tuple(
            sorted(application_cases, key=lambda item: item.application_case.id)
        ),
        demand_definitions=tuple(
            sorted(demand_definitions, key=lambda item: item.demand_definition.id)
        ),
        parameter_bindings=tuple(
            sorted(parameter_bindings, key=lambda item: item.parameter_binding.id)
        ),
        parameter_sets=tuple(
            sorted(parameter_sets, key=lambda item: item.parameter_set.id)
        ),
        reporting_periods=tuple(
            sorted(reporting_periods, key=lambda item: item.reporting_period.id)
        ),
        license_manifest=license_manifest,
        provider_candidate_manifests=tuple(
            sorted(
                provider_candidate_manifests,
                key=lambda item: item.audit_date,
            )
        ),
        physical_property_sets=tuple(
            sorted(
                physical_property_sets,
                key=lambda item: (
                    item.physical_property_set.id,
                    item.physical_property_set.version,
                ),
            )
        ),
        published_physical_property_sources=tuple(
            sorted(
                published_physical_property_sources,
                key=lambda item: (
                    item.source_namespace,
                    item.source_record_id,
                    item.source_version,
                ),
            )
        ),
        entity_registries=tuple(
            sorted(
                entity_registries,
                key=lambda item: (item.registry.id, item.registry.version),
            )
        ),
        supporting_documents=tuple(sorted(supporting_documents)),
        receipt=receipt,
    )
