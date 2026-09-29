from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Form, Request, Response, UploadFile

from . import __version__
from .container import Container
from .errors import UpstreamError
from .domain.operations import OPERATIONS, OPERATION_PAYLOAD_CONTRACTS
from .schemas import (
    AnalysisRunCreate,
    AnalysisRunOut,
    ApplicationCreate,
    ApplicationOut,
    ModelOperationCreate,
    ModelOperationBatchCreate,
    ModelOperationOut,
    OperationBatchOut,
    OperationApplyOut,
    OutboxEventOut,
    ParameterBindingApplyCreate,
    ParameterBindingApplyOut,
    PublishRevisionOut,
    PublishRevisionRequest,
    QueuedAnalysisRunOut,
    InlineSystemModelCreate,
    CasePackMaterializeCreate,
    CasePackMaterializeOut,
    SystemModelCreate,
    SystemModelOut,
    ModelSourceAttachCreate,
    ModelSourceAttachOut,
    ModelSourceOut,
    ModelSourcePreviewOut,
    NebulaProjectSourceCreate,
    SystemBindingCreate,
    SystemBindingOut,
    SystemBindingUpdate,
    SystemRevisionOut,
)
from .services.analysis_runs import capability_catalog
from .casepacks.bindings import ParameterBindingDocument, ResolvedOperationSet
from .casepacks.catalog import CasePackCatalogResponse
from .services.project_workspace import ProjectInputs, ProjectWorkspaceService
from .services.seed_projects import SeedProjectCreate, SeedProjectService
from .services.authored_project_templates import AuthoredProjectTemplateService, PublishAuthoredTemplate
from .models import AuthoredProjectTemplate
from .services.project_background import BackgroundSelection, ProjectBackgroundService
from .services.project_mapped_background import MappedBackgroundSelection, ProjectMappedBackgroundService
from .services.project_user_background import UserBackgroundSelection, ProjectUserBackgroundService
from .release_resources import display_name_of, read_language


router = APIRouter()

@router.get('/api/v1/project-templates')
def seed_project_templates(request: Request):
    container = _container(request)
    catalog = SeedProjectService(container).catalog()
    return {"items": [*catalog["items"], *AuthoredProjectTemplateService(container).catalog()]}


@router.post('/api/v1/project-templates/authored')
def publish_authored_project_template(payload: PublishAuthoredTemplate, request: Request):
    return AuthoredProjectTemplateService(_container(request)).publish(payload)


@router.post('/api/v1/project-templates/{installation_id}/projects')
def create_seed_project(installation_id: str, payload: SeedProjectCreate, request: Request):
    container = _container(request)
    with container.database.session() as db:
        authored = db.get(AuthoredProjectTemplate, installation_id) is not None
    if authored:
        return AuthoredProjectTemplateService(container).create(installation_id, payload)
    return SeedProjectService(container).create(installation_id, payload)

@router.get("/api/v1/applications/{application_id}/workspace/{revision_id}")
def project_workspace(application_id: str, revision_id: str, request: Request, lang: str | None = None):
    return ProjectWorkspaceService(_container(request)).read(application_id, revision_id, read_language(lang))


@router.post("/api/v1/applications/{application_id}/workspace/{revision_id}/reviewed-cbam")
def apply_reviewed_cbam(application_id: str, revision_id: str, request: Request, lang: str | None = None):
    container = _container(request)
    application, revision = ProjectWorkspaceService(container)._fillable_graph(application_id, revision_id)
    from .services.returned_projects import ReturnedProjectService
    return ReturnedProjectService(container).refresh_cbam_review(application, revision, read_language(lang))


@router.post('/api/v1/applications/{application_id}/workspace/{revision_id}/background/resolve')
def resolve_project_background(application_id: str, revision_id: str, payload: BackgroundSelection, request: Request):
    container = _container(request)
    _, revision = ProjectWorkspaceService(container)._fillable_graph(application_id, revision_id)
    return ProjectBackgroundService(container.client).resolve(revision.graph_snapshot, payload)


@router.post('/api/v1/applications/{application_id}/workspace/{revision_id}/background/user-project-resolve')
def resolve_user_project_background(application_id: str, revision_id: str, payload: UserBackgroundSelection, request: Request):
    container = _container(request)
    application, revision = ProjectWorkspaceService(container)._fillable_graph(application_id, revision_id)
    return ProjectUserBackgroundService(container.client).resolve(revision.graph_snapshot, payload,
                                                                  revision=revision, application=application)


@router.get('/api/v1/applications/{application_id}/workspace/{revision_id}/background/user-projects')
def list_user_supply_projects(application_id: str, revision_id: str, request: Request):
    container = _container(request)
    ProjectWorkspaceService(container)._fillable_graph(application_id, revision_id)
    return {"items": container.client.list_provider_projects()}


@router.get('/api/v1/applications/{application_id}/workspace/{revision_id}/background/user-projects/{project_id}/versions')
def list_user_supply_project_versions(application_id: str, revision_id: str, project_id: str, request: Request):
    container = _container(request)
    ProjectWorkspaceService(container)._fillable_graph(application_id, revision_id)
    return {"items": container.client.list_provider_project_versions(project_id)}


@router.post("/api/v1/applications/{application_id}/workspace/inputs")
def save_project_inputs(application_id: str, payload: ProjectInputs, request: Request, lang: str | None = None):
    return ProjectWorkspaceService(_container(request)).save(application_id, payload, read_language(lang))


def _mapped_workspace(request, application_id, revision_id):
    container = _container(request)
    _, revision = ProjectWorkspaceService(container)._fillable_graph(application_id, revision_id)
    return ProjectMappedBackgroundService(container.client), revision.graph_snapshot


@router.get('/api/v1/applications/{application_id}/workspace/{revision_id}/background/mapped-candidates')
def mapped_background_candidates(application_id: str, revision_id: str, consumer_exchange_id: str, request: Request):
    service, graph = _mapped_workspace(request, application_id, revision_id)
    return service.candidates(graph, consumer_exchange_id)


@router.post('/api/v1/applications/{application_id}/workspace/{revision_id}/background/mapped-resolve')
def resolve_mapped_background(application_id: str, revision_id: str, payload: MappedBackgroundSelection, request: Request):
    service, graph = _mapped_workspace(request, application_id, revision_id)
    return service.resolve(graph, payload)


def _container(request: Request) -> Container:
    return request.app.state.container


def _application_out(record, language: str) -> ApplicationOut:
    """Show a release resource under the language the reader asked for, never under a guessed one.

    The stored name stays authoritative: only a resource that declares short display names is
    projected, so an ordinary project keeps exactly the name its owner typed.
    """
    shown = display_name_of(record, language)
    projected = ApplicationOut.model_validate(record)
    return projected if not shown or shown == projected.name else projected.model_copy(update={"name": shown})


@router.get("/health")
@router.get("/api/v1/health")
def health(request: Request) -> dict[str, Any]:
    container = _container(request)
    return {
        "status": "ok" if container.database.ping() else "error",
        "service": "nebula-one",
        "version": __version__,
        "database": "ready",
    }


@router.get("/api/v1/engine")
def engine_status(request: Request) -> dict[str, Any]:
    container = _container(request)
    try:
        return container.client.probe()
    except UpstreamError as exc:
        return {
            "provider": "nebula_lca",
            "base_url": container.client.base_url,
            "status": "unavailable",
            "contracts": {
                "exact_model_version": False,
                "lcia_run": False,
                "provider_model_snapshot": False,
                "provider_solve": False,
                "provider_catalog_resolve": False,
                "tidas_bundle_import": False,
                "native_bundle_restore": False,
                "native_bundle_export": False,
            },
            "error": {"code": exc.code, "message": exc.message, "details": exc.details},
        }


@router.get("/api/v1/capabilities")
def capabilities(request: Request) -> dict[str, Any]:
    return capability_catalog(engine_status(request))


@router.get("/api/v1/casepacks", response_model=CasePackCatalogResponse)
def list_casepacks(request: Request) -> CasePackCatalogResponse:
    return _container(request).casepacks.list()


@router.get("/api/v1/setup-status")
def setup_status(request: Request) -> dict[str, Any]:
    container = _container(request)
    catalog = container.casepacks.list()
    installed_templates = SeedProjectService(container).catalog()["items"]
    engine = engine_status(request)
    contracts = engine.get("contracts") if isinstance(engine, dict) else {}
    provider_ready = (
        engine.get("status") == "ready"
        and isinstance(contracts, dict)
        and contracts.get("provider_solve") is True
    )
    casepacks_ready = bool(catalog.items or installed_templates)
    database_backend = container.settings.database_url.split(":", 1)[0]
    return {
        "schema_version": "nebula_one.setup-status.v1",
        "status": (
            "blocked" if not casepacks_ready else "ready" if provider_ready else "degraded"
        ),
        "database": {
            "status": "ready",
            "backend": database_backend,
            "message": "本地数据存储已就绪。",
        },
        "casepacks": {
            "status": "ready" if casepacks_ready else "blocked",
            "count": len(catalog.items) + len(installed_templates),
            "issue_count": len(catalog.issues),
            "message": (
                "案例目录已就绪。"
                if casepacks_ready
                else "没有可用案例，请检查案例目录或钢铁模板安装状态。"
            ),
        },
        "provider": {
            "status": "ready" if provider_ready else "unavailable",
            "base_url": container.client.base_url,
            "message": (
                "Nebula LCA 已连接，可以执行求解。"
                if provider_ready
                else "Nebula LCA 暂不可用；仍可浏览和导入案例，求解前请启动算法服务。"
            ),
            "remediation": (
                None
                if provider_ready
                else "启动 Nebula LCA API，并确认 NEBULA_LCA_BASE_URL 指向其本机地址。"
            ),
            "error": engine.get("error") if isinstance(engine, dict) else None,
        },
    }


@router.post(
    "/api/v1/casepacks/{case_pack_id}/versions/{case_pack_version}/"
    "application-cases/{application_case_id}/versions/{application_case_version}/materialize",
    response_model=CasePackMaterializeOut,
)
def materialize_casepack_application(
    case_pack_id: str,
    case_pack_version: str,
    application_case_id: str,
    application_case_version: str,
    payload: CasePackMaterializeCreate,
    request: Request,
) -> CasePackMaterializeOut:
    status, application, model, revision, resolved = (
        _container(request).casepack_materialization.materialize(
            case_pack_id=case_pack_id,
            case_pack_version=case_pack_version,
            application_case_id=application_case_id,
            application_case_version=application_case_version,
            payload=payload,
        )
    )
    return CasePackMaterializeOut(
        status=status,
        application=ApplicationOut.model_validate(application),
        system_model=SystemModelOut.model_validate(model),
        base_revision=SystemRevisionOut.model_validate(revision),
        demand=list(resolved.demand),
        capabilities=list(resolved.capabilities),
        blocked_capabilities=list(resolved.blocked_capabilities),
        method_packages=list(resolved.method_packages),
        case_pack_sha256=resolved.case_pack_sha256,
        resolved_case_sha256=resolved.content_sha256,
    )


@router.get(
    "/api/v1/provider/models/{project_id}/versions/{version}/snapshot"
)
def provider_model_snapshot(
    project_id: str, version: int, request: Request
) -> dict[str, Any]:
    return _container(request).client.get_provider_model_snapshot(
        project_id, version
    ).payload


@router.post("/api/v1/provider/catalog/resolve")
def provider_catalog_resolve(
    payload: dict[str, Any], request: Request
) -> dict[str, Any]:
    return _container(request).client.resolve_provider_catalog(payload).payload


@router.get("/api/v1/application-profiles")
def application_profiles(request: Request) -> dict[str, Any]:
    return _container(request).profiles.list()


@router.get("/api/v1/product-blueprint")
def product_blueprint(request: Request) -> dict[str, Any]:
    return _container(request).blueprint.get()


@router.get("/api/v1/model-operation-contract")
def model_operation_contract() -> dict[str, Any]:
    return {
        "schema_version": "nebula_one.model_operation.v1",
        "supported_operations": sorted(OPERATIONS),
        "operation_payload_contracts": OPERATION_PAYLOAD_CONTRACTS,
        "batch_request_schema": ModelOperationBatchCreate.model_json_schema(),
        "invariants": [
            "the expected parent content hash must match",
            "all operations succeed or no revision is persisted",
            "the same idempotency key cannot represent different requests",
            "one batch creates one immutable child revision",
        ],
    }


@router.get("/api/v1/parameter-binding-contract")
def parameter_binding_contract() -> dict[str, Any]:
    return {
        "schema_version": "nebula.parameter-binding-contract.v1",
        "supported_binding_operations": [
            "scale_flow",
            "set_exchange_amount",
        ],
        "parameter_binding_schema": ParameterBindingDocument.model_json_schema(),
        "resolved_operation_set_schema": ResolvedOperationSet.model_json_schema(),
        "invariants": [
            "the ParameterSet and ParameterBinding must be frozen",
            "the parent revision content hash must match exactly",
            "parameter and target unit identities must match",
            "one resolved operation set maps to one idempotent operation batch",
            "expressions and unsupported binding operations are rejected",
        ],
    }


@router.post("/api/v1/applications", response_model=ApplicationOut, status_code=201)
def create_application(payload: ApplicationCreate, request: Request) -> ApplicationOut:
    return ApplicationOut.model_validate(_container(request).applications.create(payload))


@router.get("/api/v1/applications", response_model=list[ApplicationOut])
def list_applications(request: Request, lang: str | None = None) -> list[ApplicationOut]:
    language = read_language(lang)
    return [
        _application_out(record, language)
        for record in _container(request).applications.list()
    ]


@router.get("/api/v1/applications/{application_id}", response_model=ApplicationOut)
def get_application(application_id: str, request: Request, lang: str | None = None) -> ApplicationOut:
    return _application_out(_container(request).applications.get(application_id), read_language(lang))


@router.post(
    "/api/v1/applications/{application_id}/system-models",
    response_model=SystemModelOut,
    status_code=201,
)
def attach_system_model(
    application_id: str, payload: SystemModelCreate, request: Request
) -> SystemModelOut:
    return SystemModelOut.model_validate(
        _container(request).system_models.attach(application_id, payload)
    )


@router.get(
    "/api/v1/applications/{application_id}/system-models",
    response_model=list[SystemModelOut],
)
def list_system_models(application_id: str, request: Request) -> list[SystemModelOut]:
    return [
        SystemModelOut.model_validate(record)
        for record in _container(request).system_models.list_for_application(application_id)
    ]


@router.get("/api/v1/system-models/{system_model_id}", response_model=SystemModelOut)
def get_system_model(system_model_id: str, request: Request) -> SystemModelOut:
    return SystemModelOut.model_validate(
        _container(request).system_models.get(system_model_id)
    )


@router.post(
    "/api/v1/applications/{application_id}/system-models/inline",
    response_model=SystemModelOut,
    status_code=201,
)
def attach_inline_system_model(
    application_id: str, payload: InlineSystemModelCreate, request: Request
) -> SystemModelOut:
    return SystemModelOut.model_validate(
        _container(request).system_models.attach_inline(application_id, payload)
    )


@router.get(
    "/api/v1/applications/{application_id}/model-sources",
    response_model=list[ModelSourceOut],
)
def list_model_sources(application_id: str, request: Request) -> list[ModelSourceOut]:
    return [
        ModelSourceOut.model_validate(record)
        for record in _container(request).model_sources.list_for_application(application_id)
    ]


@router.post(
    "/api/v1/applications/{application_id}/model-sources/nebula-project",
    response_model=ModelSourceAttachOut,
    status_code=201,
)
def connect_nebula_project_source(
    application_id: str,
    payload: NebulaProjectSourceCreate,
    request: Request,
) -> ModelSourceAttachOut:
    source, model, revision = _container(request).model_sources.connect_project(
        application_id, payload
    )
    return ModelSourceAttachOut(
        source=ModelSourceOut.model_validate(source),
        system_model=SystemModelOut.model_validate(model),
        base_revision=SystemRevisionOut.model_validate(revision),
    )


@router.post(
    "/api/v1/model-sources/tidas/preview",
    response_model=ModelSourcePreviewOut,
)
async def preview_tidas_model_source(
    request: Request, file: UploadFile = File(...)
) -> ModelSourcePreviewOut:
    result = _container(request).model_sources.preview_tidas(
        file.filename, await file.read()
    )
    return ModelSourcePreviewOut.model_validate(result)


@router.post(
    "/api/v1/model-sources/native/inspect",
    response_model=ModelSourcePreviewOut,
)
async def inspect_native_model_source(
    request: Request, file: UploadFile = File(...)
) -> ModelSourcePreviewOut:
    result = _container(request).model_sources.inspect_native(
        file.filename, await file.read()
    )
    return ModelSourcePreviewOut.model_validate(result)


@router.post(
    "/api/v1/applications/{application_id}/model-sources/tidas/import",
    response_model=ModelSourceOut,
    status_code=201,
)
async def import_tidas_model_source(
    application_id: str,
    request: Request,
    file: UploadFile = File(...),
    name: str = Form(...),
    confirmed: bool = Form(...),
    expected_preview_sha256: str = Form(..., pattern=r"^[0-9a-f]{64}$"),
) -> ModelSourceOut:
    record = _container(request).model_sources.import_tidas(
        application_id,
        name=name,
        filename=file.filename,
        payload=await file.read(),
        confirmed=confirmed,
        expected_preview_sha256=expected_preview_sha256,
    )
    return ModelSourceOut.model_validate(record)


@router.post(
    "/api/v1/applications/{application_id}/model-sources/native/restore",
    response_model=ModelSourceOut,
    status_code=201,
)
async def restore_native_model_source(
    application_id: str,
    request: Request,
    file: UploadFile = File(...),
    name: str = Form(...),
    confirmed: bool = Form(...),
    expected_preview_sha256: str = Form(..., pattern=r"^[0-9a-f]{64}$"),
    conflict_policy: str = Form("rename", pattern=r"^(rename|fail)$"),
) -> ModelSourceOut:
    record = _container(request).model_sources.restore_native(
        application_id,
        name=name,
        filename=file.filename,
        payload=await file.read(),
        confirmed=confirmed,
        expected_preview_sha256=expected_preview_sha256,
        conflict_policy=conflict_policy,
    )
    return ModelSourceOut.model_validate(record)


@router.post(
    "/api/v1/model-sources/{source_id}/attach",
    response_model=ModelSourceAttachOut,
)
def attach_imported_model_source(
    source_id: str,
    payload: ModelSourceAttachCreate,
    request: Request,
) -> ModelSourceAttachOut:
    source, model, revision = _container(request).model_sources.attach(
        source_id, payload
    )
    return ModelSourceAttachOut(
        source=ModelSourceOut.model_validate(source),
        system_model=SystemModelOut.model_validate(model),
        base_revision=SystemRevisionOut.model_validate(revision),
    )


@router.get(
    "/api/v1/system-models/{system_model_id}/revisions",
    response_model=list[SystemRevisionOut],
)
def list_system_revisions(
    system_model_id: str, request: Request
) -> list[SystemRevisionOut]:
    return [
        SystemRevisionOut.model_validate(record)
        for record in _container(request).system_revisions.list_for_system_model(
            system_model_id
        )
    ]


@router.post(
    "/api/v1/applications/{application_id}/system-bindings",
    response_model=SystemBindingOut,
    status_code=201,
)
def create_system_binding(
    application_id: str, payload: SystemBindingCreate, request: Request
) -> SystemBindingOut:
    return SystemBindingOut.model_validate(
        _container(request).system_bindings.create(application_id, payload)
    )


@router.get(
    "/api/v1/applications/{application_id}/system-bindings",
    response_model=list[SystemBindingOut],
)
def list_system_bindings(
    application_id: str, request: Request
) -> list[SystemBindingOut]:
    return [
        SystemBindingOut.model_validate(record)
        for record in _container(request).system_bindings.list_for_application(
            application_id
        )
    ]


@router.get(
    "/api/v1/applications/{application_id}/system-bindings/{binding_id}",
    response_model=SystemBindingOut,
)
def get_system_binding(
    application_id: str, binding_id: str, request: Request
) -> SystemBindingOut:
    return SystemBindingOut.model_validate(
        _container(request).system_bindings.get(application_id, binding_id)
    )


@router.put(
    "/api/v1/applications/{application_id}/system-bindings/{binding_id}",
    response_model=SystemBindingOut,
)
def update_system_binding(
    application_id: str,
    binding_id: str,
    payload: SystemBindingUpdate,
    request: Request,
) -> SystemBindingOut:
    return SystemBindingOut.model_validate(
        _container(request).system_bindings.update(application_id, binding_id, payload)
    )


@router.delete(
    "/api/v1/applications/{application_id}/system-bindings/{binding_id}",
    status_code=204,
)
def delete_system_binding(
    application_id: str, binding_id: str, request: Request
) -> Response:
    _container(request).system_bindings.delete(application_id, binding_id)
    return Response(status_code=204)


@router.get("/api/v1/system-revisions/{revision_id}", response_model=SystemRevisionOut)
def get_system_revision(revision_id: str, request: Request) -> SystemRevisionOut:
    return SystemRevisionOut.model_validate(
        _container(request).system_revisions.get(revision_id)
    )


@router.post(
    "/api/v1/system-models/{system_model_id}/operations",
    response_model=OperationApplyOut,
    status_code=201,
)
def apply_model_operation(
    system_model_id: str, payload: ModelOperationCreate, request: Request
) -> OperationApplyOut:
    revision, operation = _container(request).system_revisions.apply(
        system_model_id, payload
    )
    return OperationApplyOut(
        revision=SystemRevisionOut.model_validate(revision),
        operation=ModelOperationOut.model_validate(operation),
    )


@router.post(
    "/api/v1/system-models/{system_model_id}/operation-batches",
    response_model=OperationBatchOut,
    status_code=201,
)
def apply_model_operation_batch(
    system_model_id: str, payload: ModelOperationBatchCreate, request: Request
) -> OperationBatchOut:
    batch, revision, operations, replay = (
        _container(request).system_revisions.apply_batch(system_model_id, payload)
    )
    return OperationBatchOut(
        batch_id=batch.id,
        idempotency_key=batch.idempotency_key,
        idempotent_replay=replay,
        revision=SystemRevisionOut.model_validate(revision),
        operations=[ModelOperationOut.model_validate(item) for item in operations],
    )


@router.post(
    "/api/v1/system-models/{system_model_id}/parameter-bindings/apply",
    response_model=ParameterBindingApplyOut,
    status_code=201,
)
def apply_parameter_binding(
    system_model_id: str,
    payload: ParameterBindingApplyCreate,
    request: Request,
) -> ParameterBindingApplyOut:
    resolved, batch, revision, operations, replay = (
        _container(request).parameter_bindings.resolve_and_apply(
            system_model_id, payload
        )
    )
    return ParameterBindingApplyOut(
        resolved_operation_set=resolved,
        operation_batch=OperationBatchOut(
            batch_id=batch.id,
            idempotency_key=batch.idempotency_key,
            idempotent_replay=replay,
            revision=SystemRevisionOut.model_validate(revision),
            operations=[
                ModelOperationOut.model_validate(item) for item in operations
            ],
        ),
    )


@router.get(
    "/api/v1/system-revisions/{revision_id}/operations",
    response_model=list[ModelOperationOut],
)
def list_model_operations(
    revision_id: str, request: Request
) -> list[ModelOperationOut]:
    return [
        ModelOperationOut.model_validate(record)
        for record in _container(request).system_revisions.list_operations(revision_id)
    ]


@router.post(
    "/api/v1/system-revisions/{revision_id}/publish",
    response_model=PublishRevisionOut,
)
def publish_system_revision(
    revision_id: str, payload: PublishRevisionRequest, request: Request
) -> PublishRevisionOut:
    revision = _container(request).system_revisions.publish(revision_id, payload)
    return PublishRevisionOut(
        revision_id=revision.id,
        status=revision.status,
        publish_receipt=revision.publish_receipt,
    )


@router.post(
    "/api/v1/system-models/{system_model_id}/analysis-runs",
    response_model=AnalysisRunOut,
    status_code=201,
)
def run_analysis(
    system_model_id: str, payload: AnalysisRunCreate, request: Request
) -> AnalysisRunOut:
    return AnalysisRunOut.model_validate(
        _container(request).analysis_runs.run(system_model_id, payload)
    )


@router.post(
    "/api/v1/system-models/{system_model_id}/analysis-runs/queue",
    response_model=QueuedAnalysisRunOut,
    status_code=202,
)
def queue_analysis(
    system_model_id: str, payload: AnalysisRunCreate, request: Request
) -> QueuedAnalysisRunOut:
    run, event, _ = _container(request).analysis_runs.submit(system_model_id, payload)
    return QueuedAnalysisRunOut(
        run=AnalysisRunOut.model_validate(run),
        task=OutboxEventOut.model_validate(event),
    )


@router.get(
    "/api/v1/system-models/{system_model_id}/analysis-runs",
    response_model=list[AnalysisRunOut],
)
def list_analysis_runs(system_model_id: str, request: Request) -> list[AnalysisRunOut]:
    return [
        AnalysisRunOut.model_validate(record)
        for record in _container(request).analysis_runs.list_for_system_model(system_model_id)
    ]


@router.get("/api/v1/analysis-runs/{run_id}", response_model=AnalysisRunOut)
def get_analysis_run(run_id: str, request: Request) -> AnalysisRunOut:
    return AnalysisRunOut.model_validate(_container(request).analysis_runs.get(run_id))


@router.get("/api/v1/outbox-events/{event_id}", response_model=OutboxEventOut)
def get_outbox_event(event_id: str, request: Request) -> OutboxEventOut:
    return OutboxEventOut.model_validate(_container(request).outbox.get(event_id))
