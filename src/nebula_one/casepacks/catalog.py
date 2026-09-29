from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from ..errors import DomainError
from .contracts import StrictContract
from .loader import LoadedCasePack, load_casepack
from .runs import resolve_case


class CasePackApplicationSummary(StrictContract):
    editable_parameter_count: int = 0
    id: str
    version: str
    title: str
    case_type: str
    lifecycle_status: str
    study_frame_id: str
    study_frame_title: str
    study_frame_status: str
    demand_type: str
    demand: tuple[dict[str, Any], ...]
    capabilities: tuple[str, ...]
    blocked_capabilities: tuple[dict[str, str], ...]
    method_packages: tuple[dict[str, str], ...]
    resolved_case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CasePackProcessSummary(StrictContract):
    id: str
    name: str
    node_kind: str


class CasePackFlowSourceSummary(StrictContract):
    source_namespace: str
    flow_count: int = Field(ge=0)


class CasePackModelSummary(StrictContract):
    functional_unit: str
    process_count: int = Field(ge=0)
    flow_count: int = Field(ge=0)
    elementary_flow_count: int = Field(ge=0)
    connection_count: int = Field(ge=0)
    processes: tuple[CasePackProcessSummary, ...]
    flow_sources: tuple[CasePackFlowSourceSummary, ...]


class CasePackCatalogItem(StrictContract):
    id: str
    version: str
    title: str
    lifecycle_status: str
    claim_level: str
    provider: str | None
    provider_contract: str | None
    expected_graph_sha256: str | None
    case_pack_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    license_audit_status: str
    publication_gate: str
    system_summary: CasePackModelSummary | None
    showcase: dict[str, Any] | None
    applications: tuple[CasePackApplicationSummary, ...]


class CasePackCatalogIssue(StrictContract):
    code: str
    message: str
    source: str


class CasePackCatalogResponse(StrictContract):
    schema_version: Literal["nebula.casepack-catalog.v1"]
    items: tuple[CasePackCatalogItem, ...]
    issues: tuple[CasePackCatalogIssue, ...]


def _candidate_roots(configured_root: str) -> list[Path]:
    root = Path(configured_root).expanduser().resolve()
    if not root.is_dir():
        raise DomainError(
            code="CASEPACK_CATALOG_ROOT_NOT_FOUND",
            message="configured CasePack catalog root does not exist",
            status_code=503,
            details={"root": str(root)},
        )
    if (root / "casepack.json").is_file():
        return [root]
    return sorted(
        (child for child in root.iterdir() if (child / "casepack.json").is_file()),
        key=lambda item: item.name.casefold(),
    )


def _model_summary(loaded: LoadedCasePack) -> CasePackModelSummary | None:
    snapshot_path = getattr(loaded.case_pack.engine, "snapshot_path", None)
    if not snapshot_path:
        return None
    snapshot = next(
        (
            payload
            for source_path, payload in loaded.supporting_documents
            if source_path == snapshot_path
        ),
        None,
    )
    if not isinstance(snapshot, dict):
        return None
    graph = snapshot.get("graph") or {}
    nodes = [item for item in graph.get("nodes") or [] if isinstance(item, dict)]
    connections = [
        item for item in graph.get("exchanges") or [] if isinstance(item, dict)
    ]
    processes = tuple(
        CasePackProcessSummary(
            id=str(node.get("id") or ""),
            name=str(node.get("name") or node.get("id") or ""),
            node_kind=str(node.get("node_kind") or "process"),
        )
        for node in nodes
    )
    flows: dict[tuple[str, str, str], dict[str, Any]] = {}
    source_counts: Counter[str] = Counter()
    for node in nodes:
        for collection in ("inputs", "outputs", "emissions"):
            for flow in node.get(collection) or []:
                if not isinstance(flow, dict):
                    continue
                identity = (
                    str(flow.get("flowSourceNamespace") or "unspecified"),
                    str(flow.get("flowUuid") or flow.get("id") or ""),
                    str(flow.get("flowVersion") or "unspecified"),
                )
                flows.setdefault(identity, flow)
    for source_namespace, _, _ in flows:
        source_counts[source_namespace] += 1
    functional_unit = (
        (graph.get("metadata") or {}).get("functional_unit") or {}
    ).get("display_text") or graph.get("functionalUnit") or "Unspecified"
    return CasePackModelSummary(
        functional_unit=str(functional_unit),
        process_count=len(processes),
        flow_count=len(flows),
        elementary_flow_count=sum(
            1
            for flow in flows.values()
            if flow.get("type") in {"elementary", "biosphere"}
        ),
        connection_count=len(connections),
        processes=processes,
        flow_sources=tuple(
            CasePackFlowSourceSummary(
                source_namespace=source_namespace,
                flow_count=flow_count,
            )
            for source_namespace, flow_count in sorted(source_counts.items())
        ),
    )


def _summary(loaded: LoadedCasePack) -> CasePackCatalogItem:
    document = loaded.case_pack
    engine = document.engine
    applications: list[CasePackApplicationSummary] = []
    for application in loaded.application_cases:
        resolved = resolve_case(loaded, application.application_case.id)
        applications.append(
            CasePackApplicationSummary(
                editable_parameter_count=sum(len(b.bindings) for b in loaded.parameter_bindings if application.scenario.parameter_binding_ref and b.parameter_binding.id == application.scenario.parameter_binding_ref.id and b.parameter_binding.version == application.scenario.parameter_binding_ref.version),
                id=application.application_case.id,
                version=application.application_case.version,
                title=application.application_case.title,
                case_type=application.application_case.case_type,
                lifecycle_status=application.application_case.lifecycle_status,
                study_frame_id=application.study_frame.study_frame.id,
                study_frame_title=application.study_frame.study_frame.title,
                study_frame_status=application.study_frame.study_frame.lifecycle_status,
                demand_type=resolved.demand_type,
                demand=resolved.demand,
                capabilities=resolved.capabilities,
                blocked_capabilities=resolved.blocked_capabilities,
                method_packages=resolved.method_packages,
                resolved_case_sha256=resolved.content_sha256,
            )
        )
    return CasePackCatalogItem(
        id=document.case_pack.id,
        version=document.case_pack.version,
        title=document.case_pack.title,
        lifecycle_status=document.case_pack.lifecycle_status,
        claim_level=document.case_pack.claim_level,
        provider=engine.provider if engine is not None else None,
        provider_contract=engine.api_contract if engine is not None else None,
        expected_graph_sha256=engine.expected_graph_sha256 if engine is not None else None,
        case_pack_sha256=loaded.receipt.case_pack_sha256,
        license_audit_status=loaded.license_manifest.audit_status,
        publication_gate=loaded.license_manifest.publication_gate,
        system_summary=_model_summary(loaded),
        showcase=(
            document.showcase.model_dump(mode="json")
            if document.showcase is not None
            else None
        ),
        applications=tuple(sorted(applications, key=lambda item: item.id)),
    )


class CasePackCatalog:
    def __init__(self, roots: tuple[str, ...], release_catalog=None) -> None:
        self.roots = roots
        self.release_catalog = release_catalog

    def list(self) -> CasePackCatalogResponse:
        items: list[CasePackCatalogItem] = []
        issues: list[CasePackCatalogIssue] = []
        identities: set[tuple[str, str]] = set()
        for configured_root in self.roots:
            source_label = Path(configured_root).name or "configured-root"
            try:
                candidates = _candidate_roots(configured_root)
            except DomainError as exc:
                issues.append(
                    CasePackCatalogIssue(
                        code=exc.code,
                        message=exc.message,
                        source=source_label,
                    )
                )
                continue
            for candidate in candidates:
                try:
                    item = _summary(load_casepack(candidate))
                except DomainError as exc:
                    issues.append(
                        CasePackCatalogIssue(
                            code=exc.code,
                            message=exc.message,
                            source=candidate.name,
                        )
                    )
                    continue
                if self.release_catalog and not self.release_catalog.allows_casepack(item.id, item.version):
                    continue
                identity = (item.id, item.version)
                if identity in identities:
                    issues.append(
                        CasePackCatalogIssue(
                            code="CASEPACK_CATALOG_IDENTITY_DUPLICATE",
                            message="duplicate CasePack id and version are configured",
                            source=candidate.name,
                        )
                    )
                    continue
                identities.add(identity)
                items.append(item)
        return CasePackCatalogResponse(
            schema_version="nebula.casepack-catalog.v1",
            items=tuple(sorted(items, key=lambda item: (item.title, item.version))),
            issues=tuple(issues),
        )

    def load_exact(self, case_pack_id: str, version: str) -> LoadedCasePack:
        if self.release_catalog and not self.release_catalog.allows_casepack(case_pack_id, version):
            raise DomainError(code="CASEPACK_NOT_FOUND", message="the exact CasePack id and version are not configured", status_code=404)
        matches: list[LoadedCasePack] = []
        for configured_root in self.roots:
            try:
                candidates = _candidate_roots(configured_root)
            except DomainError:
                continue
            for candidate in candidates:
                try:
                    loaded = load_casepack(candidate)
                except DomainError:
                    continue
                identity = loaded.case_pack.case_pack
                if identity.id == case_pack_id and identity.version == version:
                    matches.append(loaded)
        if not matches:
            raise DomainError(
                code="CASEPACK_NOT_FOUND",
                message="the exact CasePack id and version are not configured",
                status_code=404,
                details={"case_pack_id": case_pack_id, "version": version},
            )
        if len(matches) != 1:
            raise DomainError(
                code="CASEPACK_IDENTITY_DUPLICATE",
                message="the exact CasePack id and version are configured more than once",
                status_code=409,
                details={"case_pack_id": case_pack_id, "version": version},
            )
        return matches[0]
