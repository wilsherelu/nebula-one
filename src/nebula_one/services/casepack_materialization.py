from __future__ import annotations

from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..adapters.nebula_lca import NebulaLCAClient
from ..casepacks.catalog import CasePackCatalog
from ..casepacks.contracts import EnginePin, InlineEnginePin
from ..casepacks.runs import resolve_case
from ..database import Database
from ..errors import DomainError
from ..hashing import (
    canonical_content_sha256,
    canonical_graph_sha256,
    canonical_json_sha256,
)
from ..models import Application, SystemModel, SystemRevision, new_id
from ..runtime_models import (
    BoundaryDefinition,
    Entity,
    EntityModelBinding,
    MethodPackage,
    Period,
)
from ..runtime_schemas import MethodPackageCreate
from ..profiles import ApplicationProfiles
from ..schemas import CasePackMaterializeCreate


class CasePackMaterializationService:
    def __init__(
        self,
        database: Database,
        client: NebulaLCAClient,
        profiles: ApplicationProfiles,
        catalog: CasePackCatalog,
    ) -> None:
        self.database = database
        self.client = client
        self.profiles = profiles
        self.catalog = catalog

    @staticmethod
    def _application_case(loaded, application_case_id: str, version: str):
        matches = [
            item
            for item in loaded.application_cases
            if item.application_case.id == application_case_id
            and item.application_case.version == version
        ]
        if len(matches) != 1:
            raise DomainError(
                code="CASEPACK_APPLICATION_CASE_NOT_FOUND",
                message="the exact ApplicationCase id and version are not in the CasePack",
                status_code=404,
                details={
                    "application_case_id": application_case_id,
                    "application_case_version": version,
                },
            )
        application_case = matches[0]
        if application_case.application_case.lifecycle_status != "executable":
            raise DomainError(
                code="CASEPACK_APPLICATION_CASE_NOT_EXECUTABLE",
                message="the selected ApplicationCase is not executable",
                status_code=422,
            )
        return application_case

    def _graph_and_receipt(
        self, loaded, resolved, application_case
    ) -> tuple[dict, dict]:
        engine = loaded.case_pack.engine
        if engine is None:
            raise DomainError(
                code="CASEPACK_ENGINE_PIN_MISSING",
                message="the selected CasePack has no executable Nebula LCA engine pin",
                status_code=422,
            )
        supporting_documents = dict(loaded.supporting_documents)
        application_snapshot = supporting_documents.get(
            application_case.study_frame.base_revision_ref
        )
        if (
            isinstance(application_snapshot, dict)
            and application_snapshot.get("schema_version") == "provider.snapshot.v1"
        ):
            graph = application_snapshot.get("graph")
            if not isinstance(graph, dict):
                raise DomainError(
                    code="CASEPACK_APPLICATION_SNAPSHOT_INVALID",
                    message="the ApplicationCase inline provider snapshot has no graph",
                    status_code=422,
                )
            graph_sha256 = canonical_graph_sha256(graph)
            if graph_sha256 != application_snapshot.get("graph_hash"):
                raise DomainError(
                    code="CASEPACK_APPLICATION_SNAPSHOT_HASH_MISMATCH",
                    message="the ApplicationCase inline provider snapshot graph hash differs",
                    status_code=409,
                    details={
                        "reference": application_case.study_frame.base_revision_ref,
                        "expected_graph_sha256": application_snapshot.get("graph_hash"),
                        "actual_graph_sha256": graph_sha256,
                    },
                )
            receipt = {
                "provider": "nebula_lca",
                "source_kind": "application_case_inline_snapshot",
                "source_id": (
                    f"casepack:{loaded.case_pack.case_pack.id}:"
                    f"application-case:{application_case.application_case.id}"
                ),
                "source_version": engine.source_version
                if isinstance(engine, InlineEnginePin)
                else engine.version,
                "application_case_version": (
                    application_case.application_case.version
                ),
                "snapshot_path": application_case.study_frame.base_revision_ref,
                "provider_contract": engine.api_contract,
            }
            expected_graph_sha256 = application_snapshot["graph_hash"]
        elif isinstance(engine, InlineEnginePin):
            snapshots = [
                payload
                for source_path, payload in loaded.supporting_documents
                if source_path == engine.snapshot_path
            ]
            if len(snapshots) != 1 or not isinstance(snapshots[0].get("graph"), dict):
                raise DomainError(
                    code="CASEPACK_INLINE_SNAPSHOT_INVALID",
                    message="the exact inline provider snapshot is missing or invalid",
                    status_code=422,
                )
            graph = snapshots[0]["graph"]
            receipt = {
                "provider": "nebula_lca",
                "source_kind": "inline_casepack",
                "source_id": engine.source_id,
                "source_version": engine.source_version,
                "provider_contract": engine.api_contract,
            }
            expected_graph_sha256 = engine.expected_graph_sha256
        elif isinstance(engine, EnginePin):
            upstream = self.client.get_model_version(engine.project_id, engine.version)
            graph = upstream.payload["graph"]
            receipt = {
                "provider": "nebula_lca",
                "source_kind": "provider_model_version",
                "source_id": engine.project_id,
                "source_version": engine.version,
                "provider_contract": engine.api_contract,
                "etag": upstream.etag,
            }
            expected_graph_sha256 = engine.expected_graph_sha256
        else:  # pragma: no cover - exhaustive Pydantic contract guard
            raise DomainError(
                code="CASEPACK_ENGINE_PIN_UNSUPPORTED",
                message="the selected CasePack engine pin is unsupported",
                status_code=422,
            )
        graph_sha256 = canonical_graph_sha256(graph)
        if graph_sha256 != expected_graph_sha256:
            raise DomainError(
                code="CASEPACK_ENGINE_GRAPH_HASH_MISMATCH",
                message="the materialized graph does not match the CasePack engine pin",
                status_code=409,
                details={
                    "expected_graph_sha256": expected_graph_sha256,
                    "actual_graph_sha256": graph_sha256,
                },
            )
        receipt.update(
            {
                "graph_sha256": graph_sha256,
                "case_pack_sha256": loaded.receipt.case_pack_sha256,
                "resolved_case_sha256": resolved.content_sha256,
                "node_count": len(graph.get("nodes") or []),
                "exchange_count": len(graph.get("exchanges") or []),
            }
        )
        return graph, receipt

    @staticmethod
    def _method_packages(loaded, resolved) -> list[tuple[MethodPackageCreate, str]]:
        supporting_documents = dict(loaded.supporting_documents)
        packages: list[tuple[MethodPackageCreate, str]] = []
        for reference in resolved.method_packages:
            payload = supporting_documents.get(reference["path"])
            if not isinstance(payload, dict):
                raise DomainError(
                    code="CASE_METHOD_PACKAGE_NOT_FOUND",
                    message="resolved CasePack method package is unavailable",
                    status_code=422,
                    details={"reference": reference["path"]},
                )
            package = MethodPackageCreate.model_validate(payload)
            content_sha256 = canonical_json_sha256(package.model_dump(mode="json"))
            if (
                package.package_id != reference["package_id"]
                or package.version != reference["version"]
                or content_sha256 != reference["content_sha256"]
            ):
                raise DomainError(
                    code="CASE_METHOD_PACKAGE_CONTENT_MISMATCH",
                    message="resolved CasePack method package content has drifted",
                    status_code=409,
                    details={"reference": reference["path"]},
                )
            packages.append((package, content_sha256))
        return packages

    @staticmethod
    def _materialize_spatial_runtime(
        db,
        *,
        loaded,
        application: Application,
        revision: SystemRevision,
        resolved,
    ) -> None:
        if "spatial.aggregate.v1" not in resolved.capabilities:
            return
        registries = list(loaded.entity_registries)
        if len(registries) != 1:
            raise DomainError(
                code="CASEPACK_SPATIAL_REGISTRY_REQUIRED",
                message="spatial ApplicationCase requires exactly one entity registry",
                status_code=422,
            )
        registry = registries[0]
        expected_release = (
            f"{registry.registry.id}-{registry.registry.version}"
        )
        if loaded.case_pack.shared_releases.entity_registry != expected_release:
            raise DomainError(
                code="CASEPACK_SPATIAL_REGISTRY_RELEASE_MISMATCH",
                message="entity registry does not match the CasePack shared release pin",
                status_code=409,
            )
        boundaries = [
            item
            for item in registry.park_boundaries
            if item.reporting_period_id == resolved.reporting_period_id
        ]
        if len(boundaries) != 1:
            raise DomainError(
                code="CASEPACK_SPATIAL_BOUNDARY_AMBIGUOUS",
                message="spatial ApplicationCase must resolve one park boundary",
                status_code=422,
            )
        boundary_template = boundaries[0]
        period_documents = [
            item
            for item in loaded.reporting_periods
            if item.reporting_period.id == resolved.reporting_period_id
            and item.reporting_period.version == resolved.reporting_period_version
        ]
        if len(period_documents) != 1:
            raise DomainError(
                code="CASEPACK_REPORTING_PERIOD_NOT_FOUND",
                message="spatial ApplicationCase reporting period cannot be resolved exactly",
                status_code=422,
            )
        period_document = period_documents[0]

        graph_nodes = {
            str(item.get("id") or "").strip(): str(
                item.get("process_uuid") or item.get("processUuid") or item.get("id") or ""
            ).strip()
            for item in revision.graph_snapshot.get("nodes") or []
            if isinstance(item, dict)
        }
        for binding in registry.process_bindings:
            if graph_nodes.get(binding.graph_node_id) != binding.process_uuid:
                raise DomainError(
                    code="CASEPACK_SPATIAL_PROCESS_PIN_MISMATCH",
                    message="entity registry process binding does not match the frozen graph",
                    status_code=409,
                    details={"graph_node_id": binding.graph_node_id},
                )

        period_key = (
            f"{period_document.reporting_period.id}"
            f"@{period_document.reporting_period.version}"
        )
        period = db.scalar(
            select(Period).where(
                Period.application_id == application.id,
                Period.key == period_key,
            )
        )
        if period is None:
            period = Period(
                application_id=application.id,
                key=period_key,
                name=period_document.reporting_period.title,
                start_date=period_document.start_date,
                end_date=period_document.end_date,
                resolution="year",
            )
            db.add(period)
            db.flush()
        elif (
            period.start_date != period_document.start_date
            or period.end_date != period_document.end_date
        ):
            raise DomainError(
                code="CASEPACK_SPATIAL_PERIOD_CONFLICT",
                message="existing reporting period differs from the CasePack pin",
                status_code=409,
            )

        runtime_entities: dict[str, Entity] = {}
        ordered_entities = sorted(
            registry.entities,
            key=lambda item: (item.parent_entity_id is not None, item.entity_id),
        )
        for item in ordered_entities:
            parent = (
                runtime_entities.get(item.parent_entity_id)
                if item.parent_entity_id is not None
                else None
            )
            existing = db.scalar(
                select(Entity).where(
                    Entity.application_id == application.id,
                    Entity.external_id == item.entity_id,
                )
            )
            attributes = {
                "spatial_unit": item.spatial_unit.model_dump(mode="json")
            }
            if existing is None:
                existing = Entity(
                    application_id=application.id,
                    parent_id=parent.id if parent is not None else None,
                    entity_type=item.entity_type,
                    name=item.name,
                    external_id=item.entity_id,
                    attributes=attributes,
                )
                db.add(existing)
                db.flush()
            elif (
                existing.parent_id != (parent.id if parent is not None else None)
                or existing.entity_type != item.entity_type
                or existing.name != item.name
                or existing.attributes != attributes
            ):
                raise DomainError(
                    code="CASEPACK_SPATIAL_ENTITY_CONFLICT",
                    message="existing spatial entity differs from the CasePack pin",
                    status_code=409,
                    details={"entity_id": item.entity_id},
                )
            runtime_entities[item.entity_id] = existing

        grouped_processes: dict[str, list[str]] = {}
        for binding in registry.process_bindings:
            grouped_processes.setdefault(binding.entity_id, []).append(
                binding.graph_node_id
            )
        for external_id, process_ids in sorted(grouped_processes.items()):
            entity = runtime_entities[external_id]
            process_ids = sorted(process_ids)
            content = {
                "entity_id": entity.id,
                "system_revision_id": revision.id,
                "process_ids": process_ids,
                "flow_selectors": [],
                "period_id": period.id,
                "allocation_rule_ref": None,
            }
            content_sha256 = canonical_json_sha256(content)
            existing_bindings = list(
                db.scalars(
                    select(EntityModelBinding).where(
                        EntityModelBinding.entity_id == entity.id,
                        EntityModelBinding.system_revision_id == revision.id,
                    )
                )
            )
            if not existing_bindings:
                db.add(
                    EntityModelBinding(
                        **content,
                        content_sha256=content_sha256,
                    )
                )
            elif len(existing_bindings) != 1 or existing_bindings[0].content_sha256 != content_sha256:
                raise DomainError(
                    code="CASEPACK_SPATIAL_BINDING_CONFLICT",
                    message="existing facility binding differs from the CasePack pin",
                    status_code=409,
                    details={"entity_id": external_id},
                )
        db.flush()

        park_entity = runtime_entities[boundary_template.park_entity_id]
        park_spatial = park_entity.attributes["spatial_unit"]
        geographic_scope = {
            "boundary_external_id": boundary_template.boundary_id,
            "spatial_unit_ref": (
                f"{park_spatial['spatial_unit_id']}@{park_spatial['version']}"
            ),
            "spatial_unit_sha256": park_spatial["content_sha256"],
            "reporting_period_ref": (
                f"{resolved.reporting_period_id}@{resolved.reporting_period_version}"
            ),
            "reporting_period_sha256": resolved.reporting_period_sha256,
        }
        included_entity_ids = [
            runtime_entities[item].id for item in boundary_template.included_entity_ids
        ]
        boundary_content = {
            "name": boundary_template.name,
            "boundary_type": "park",
            "included_entity_ids": included_entity_ids,
            "included_process_ids": [],
            "included_flow_rules": [],
            "excluded_items": [],
            "consolidation_policy": boundary_template.consolidation_policy,
            "period_id": period.id,
            "geographic_scope": geographic_scope,
            "method_package_ref": None,
        }
        boundary_sha256 = canonical_json_sha256(boundary_content)
        existing_boundary = db.scalar(
            select(BoundaryDefinition).where(
                BoundaryDefinition.application_id == application.id,
                BoundaryDefinition.name == boundary_template.name,
            )
        )
        if existing_boundary is None:
            db.add(
                BoundaryDefinition(
                    application_id=application.id,
                    **boundary_content,
                    content_sha256=boundary_sha256,
                    status="frozen",
                    frozen_at=datetime.now(timezone.utc),
                )
            )
        elif (
            existing_boundary.status != "frozen"
            or existing_boundary.content_sha256 != boundary_sha256
        ):
            raise DomainError(
                code="CASEPACK_SPATIAL_BOUNDARY_CONFLICT",
                message="existing park boundary differs from the CasePack pin",
                status_code=409,
            )
        db.flush()

    def materialize(
        self,
        *,
        case_pack_id: str,
        case_pack_version: str,
        application_case_id: str,
        application_case_version: str,
        payload: CasePackMaterializeCreate,
    ) -> tuple[str, Application, SystemModel, SystemRevision, object]:
        loaded = self.catalog.load_exact(case_pack_id, case_pack_version)
        if loaded.receipt.case_pack_sha256 != payload.expected_case_pack_sha256:
            raise DomainError(
                code="CASEPACK_CONTENT_HASH_MISMATCH",
                message="the configured CasePack content differs from the selected catalog item",
                status_code=409,
            )
        application_case = self._application_case(
            loaded, application_case_id, application_case_version
        )
        resolved = resolve_case(loaded, application_case_id)
        if resolved.content_sha256 != payload.expected_resolved_case_sha256:
            raise DomainError(
                code="CASEPACK_RESOLVED_CASE_HASH_MISMATCH",
                message="the resolved ApplicationCase differs from the selected catalog item",
                status_code=409,
            )
        self.profiles.require("system_analysis")
        graph, receipt = self._graph_and_receipt(
            loaded, resolved, application_case
        )
        method_packages = self._method_packages(loaded, resolved)
        engine = loaded.case_pack.engine
        source_id = receipt["source_id"]
        source_version = receipt["source_version"]
        context = {
            "case_pack_id": case_pack_id,
            "case_pack_version": case_pack_version,
            "case_pack_sha256": loaded.receipt.case_pack_sha256,
            "application_case_id": application_case_id,
            "application_case_version": application_case_version,
            "resolved_case_sha256": resolved.content_sha256,
            "study_frame_sha256": resolved.study_frame_sha256,
            "demand_definition_sha256": resolved.demand_definition_sha256,
            "reporting_period_id": resolved.reporting_period_id,
            "reporting_period_version": resolved.reporting_period_version,
            "reporting_period_sha256": resolved.reporting_period_sha256,
            "claim_level": loaded.case_pack.case_pack.claim_level,
            "method_package_refs": [
                f"{package.package_id}@{package.version}"
                for package, _ in method_packages
            ],
        }
        if payload.project_key is not None:
            context["project_key"] = payload.project_key
            context["template_locked"] = True
            context["project_capabilities"] = list(resolved.capabilities)
        with self.database.session() as db:
            for package, content_sha256 in method_packages:
                existing_package = db.scalar(
                    select(MethodPackage).where(
                        MethodPackage.package_id == package.package_id,
                        MethodPackage.version == package.version,
                    )
                )
                if existing_package is not None:
                    if existing_package.content_sha256 != content_sha256:
                        raise DomainError(
                            code="METHOD_PACKAGE_VERSION_CONFLICT",
                            message="CasePack method package version binds different content",
                            status_code=409,
                            details={
                                "reference": f"{package.package_id}@{package.version}"
                            },
                        )
                    continue
                db.add(
                    MethodPackage(
                        package_id=package.package_id,
                        version=package.version,
                        package_kind=package.package_kind,
                        jurisdiction=package.jurisdiction,
                        valid_from=package.valid_from,
                        valid_to=package.valid_to,
                        manifest=package.manifest,
                        content_sha256=content_sha256,
                        status="registered",
                    )
                )
            db.flush()
            existing_apps = [
                item
                for item in db.scalars(select(Application)).all()
                if item.context.get("resolved_case_sha256") == resolved.content_sha256
                and item.context.get("case_pack_id") == case_pack_id
                and item.context.get("project_key") == payload.project_key
            ]
            if len(existing_apps) > 1:
                raise DomainError(
                    code="CASEPACK_MATERIALIZATION_AMBIGUOUS",
                    message="more than one application already represents the exact CasePack case",
                    status_code=409,
                )
            if existing_apps:
                application = existing_apps[0]
                if payload.project_name is not None and application.name != payload.project_name:
                    raise DomainError(code="PROJECT_CREATE_CONFLICT", message="项目创建标识已用于另一个名称。", status_code=409)
                models = list(
                    db.scalars(
                        select(SystemModel).where(
                            SystemModel.application_id == application.id,
                            SystemModel.upstream_project_id == source_id,
                            SystemModel.upstream_version == source_version,
                        )
                    )
                )
                if len(models) != 1 or models[0].graph_sha256 != receipt["graph_sha256"]:
                    raise DomainError(
                        code="CASEPACK_MATERIALIZATION_INCOMPLETE",
                        message="the existing application does not contain the exact CasePack model pin",
                        status_code=409,
                    )
                model = models[0]
                revisions = list(
                    db.scalars(
                        select(SystemRevision).where(
                            SystemRevision.system_model_id == model.id,
                            SystemRevision.parent_revision_id.is_(None),
                        )
                    )
                )
                if len(revisions) != 1:
                    raise DomainError(
                        code="CASEPACK_MATERIALIZATION_INCOMPLETE",
                        message="the existing CasePack model has no unique base revision",
                        status_code=409,
                    )
                self._materialize_spatial_runtime(
                    db,
                    loaded=loaded,
                    application=application,
                    revision=revisions[0],
                    resolved=resolved,
                )
                db.commit()
                return "existing", application, model, revisions[0], resolved

            application_id = str(uuid5(NAMESPACE_URL, f"nebula-one:project:{case_pack_id}:{resolved.content_sha256}:{payload.project_key}")) if payload.project_key else new_id()
            model_id = new_id()
            revision_id = new_id()
            receipt.update(
                {
                    "base_revision_id": revision_id,
                    "materialized_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            application = Application(
                id=application_id,
                name=payload.project_name or application_case.application_case.title,
                application_type="system_analysis",
                description=f"CasePack {case_pack_id}@{case_pack_version}",
                context=context,
            )
            model = SystemModel(
                id=model_id,
                application_id=application_id,
                name=loaded.case_pack.case_pack.title,
                provider="nebula_lca",
                provider_base_url=self.client.base_url,
                upstream_project_id=source_id,
                upstream_version=source_version,
                graph_sha256=receipt["graph_sha256"],
                graph_snapshot=graph,
                upstream_receipt=receipt,
            )
            revision = SystemRevision(
                id=revision_id,
                system_model_id=model_id,
                parent_revision_id=None,
                revision_number=1,
                label=f"CasePack {case_pack_version} base",
                revision_kind="base",
                graph_sha256=receipt["graph_sha256"],
                content_sha256=canonical_content_sha256(graph, context),
                graph_snapshot=graph,
                application_context=context,
                status="draft",
            )
            db.add_all((application, model, revision))
            try:
                db.flush()
            except IntegrityError as exc:
                db.rollback()
                raise DomainError(code="PROJECT_CREATE_CONCURRENT", message="该项目正在创建，请重试以读取已创建的项目。", status_code=409) from exc
            self._materialize_spatial_runtime(
                db,
                loaded=loaded,
                application=application,
                revision=revision,
                resolved=resolved,
            )
            try:
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                raise DomainError(code="PROJECT_CREATE_CONCURRENT", message="该项目正在创建，请重试以读取已创建的项目。", status_code=409) from exc
            for record in (application, model, revision):
                db.refresh(record)
            return "created", application, model, revision, resolved
