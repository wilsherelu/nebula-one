from __future__ import annotations

from fastapi import APIRouter, Query, Request, Response

from .container import Container
from .analysis.cbam_trial_v2 import SCHEMA_VERSION as CBAM_TRIAL_V2_SCHEMA_VERSION
from .exports.cbam_trial_report import render_cbam_trial_html
from .exports.cbam_partial_review import render_cbam_partial_review_markdown
from .exports.organization_period import render_organization_period_html
from .exports.organization_lifecycle import render_organization_lifecycle_html
from .analysis.pcf_visual import render_product_pcf_svg
from .analysis.carbon_management_visual import render_carbon_management_svg
from .organization_lifecycle_display import organization_lifecycle_display
from .errors import DomainError
from .schemas import AnalysisRunOut, OutboxEventOut, QueuedAnalysisRunOut
from .runtime_schemas import (
    AnalysisPlanCreate,
    AnalysisPlanOut,
    BoundaryDefinitionCreate,
    BoundaryDefinitionOut,
    ComparisonCreate,
    ComparisonOut,
    EntityCreate,
    EntityModelBindingCreate,
    EntityModelBindingOut,
    EntityOut,
    EnergyCarrierResultCreate,
    EnergyCarrierResultOut,
    EnergyFlowCreate,
    EnergyFlowOut,
    WaterBalanceCreate,
    WaterBalanceOut,
    EvidenceItemCreate,
    EvidenceItemOut,
    EvidencePackCreate,
    EvidencePackOut,
    InventoryDataPointCreate,
    InventoryDataPointOut,
    InventorySnapshotCreate,
    InventorySnapshotOut,
    MethodPackageCreate,
    MethodPackageOut,
    CarbonManagementCreate,
    CarbonManagementOut,
    CbamTrialCreate,
    CbamPartialReviewCreate,
    CbamTrialOut,
    CbamTrialV2Out,
    CbamComplexTrialCreate,
    CbamComplexTrialOut,
    ParameterSetCreate,
    ParameterSetOut,
    PeriodEnergyComparisonCreate,
    PeriodEnergyComparisonOut,
    PeriodEnergyTrendCreate,
    PeriodEnergyTrendOut,
    PeriodEnergyTotalCreate,
    PeriodEnergyTotalOut,
    ProvinceElectricityCreate,
    ProvinceElectricityOut,
    OrganizationGhgInventoryCreate,
    OrganizationGhgInventoryOut,
    OrganizationGhgInventoryV1Create,
    OrganizationGhgInventoryV1Out,
    OrganizationPeriodCreate,
    OrganizationPeriodOut,
    OrganizationLifecycleCreate,
    PeriodCreate,
    PeriodOut,
    ProductCarbonFootprintCreate,
    ClimateMethodResolutionOut,
    ProductCarbonFootprintOut,
    ProviderSolveAndFreezeCreate,
    QueuedScenarioComparisonRunOut,
    ResultSetCreate,
    ResultSetOut,
    ScenarioCreate,
    ScenarioComparisonExecuteCreate,
    ScenarioComparisonRunOut,
    ScenarioOut,
    SolvedSystemSnapshotCreate,
    SolvedSystemSnapshotOut,
    SpatialAggregateCreate,
    SpatialAggregateOut,
    SpatialEnergyCreate,
    SpatialEnergyFlowCreate,
    SpatialEnergyFlowOut,
    SpatialEnergyOut,
    SpatialDistributionCreate,
    SpatialDistributionOut,
)


router = APIRouter(prefix="/api/v1")


def _container(request: Request) -> Container:
    return request.app.state.container


@router.post("/method-packages", response_model=MethodPackageOut, status_code=201)
def register_method_package(
    payload: MethodPackageCreate, request: Request
) -> MethodPackageOut:
    return MethodPackageOut.model_validate(
        _container(request).registry.register_method_package(payload)
    )


@router.get("/method-packages", response_model=list[MethodPackageOut])
def list_method_packages(request: Request) -> list[MethodPackageOut]:
    return [
        MethodPackageOut.model_validate(record)
        for record in _container(request).registry.list_method_packages()
    ]


@router.get("/method-packages/organization-lifecycle-display")
def get_organization_lifecycle_display(method_package_ref: str, method_package_sha256: str,
                                       request: Request, lang: str = "en") -> dict:
    methods = _container(request).registry.list_method_packages()
    method = next((item for item in methods
                   if f"{item.package_id}@{item.version}" == method_package_ref), None)
    if method is None or method.content_sha256 != method_package_sha256:
        raise DomainError(code="ORGANIZATION_DISPLAY_METHOD_MISMATCH",
                          message="The requested exact method is not registered", status_code=409)
    return organization_lifecycle_display(method, lang)


@router.post(
    "/applications/{application_id}/entities",
    response_model=EntityOut,
    status_code=201,
)
def create_entity(
    application_id: str, payload: EntityCreate, request: Request
) -> EntityOut:
    return EntityOut.model_validate(
        _container(request).registry.create_entity(application_id, payload)
    )


@router.get(
    "/applications/{application_id}/entities", response_model=list[EntityOut]
)
def list_entities(application_id: str, request: Request) -> list[EntityOut]:
    return [
        EntityOut.model_validate(record)
        for record in _container(request).registry.list_entities(application_id)
    ]


@router.post(
    "/applications/{application_id}/periods",
    response_model=PeriodOut,
    status_code=201,
)
def create_period(
    application_id: str, payload: PeriodCreate, request: Request
) -> PeriodOut:
    return PeriodOut.model_validate(
        _container(request).registry.create_period(application_id, payload)
    )


@router.get(
    "/applications/{application_id}/periods", response_model=list[PeriodOut]
)
def list_periods(application_id: str, request: Request) -> list[PeriodOut]:
    return [
        PeriodOut.model_validate(record)
        for record in _container(request).registry.list_periods(application_id)
    ]


@router.post(
    "/applications/{application_id}/boundaries",
    response_model=BoundaryDefinitionOut,
    status_code=201,
)
def create_boundary(
    application_id: str, payload: BoundaryDefinitionCreate, request: Request
) -> BoundaryDefinitionOut:
    return BoundaryDefinitionOut.model_validate(
        _container(request).registry.create_boundary(application_id, payload)
    )


@router.get(
    "/applications/{application_id}/boundaries",
    response_model=list[BoundaryDefinitionOut],
)
def list_boundaries(
    application_id: str, request: Request
) -> list[BoundaryDefinitionOut]:
    return [
        BoundaryDefinitionOut.model_validate(record)
        for record in _container(request).registry.list_boundaries(application_id)
    ]


@router.post(
    "/boundaries/{boundary_id}/freeze", response_model=BoundaryDefinitionOut
)
def freeze_boundary(boundary_id: str, request: Request) -> BoundaryDefinitionOut:
    return BoundaryDefinitionOut.model_validate(
        _container(request).registry.freeze_boundary(boundary_id)
    )


@router.post(
    "/applications/{application_id}/entity-model-bindings",
    response_model=EntityModelBindingOut,
    status_code=201,
)
def create_entity_model_binding(
    application_id: str, payload: EntityModelBindingCreate, request: Request
) -> EntityModelBindingOut:
    return EntityModelBindingOut.model_validate(
        _container(request).registry.create_binding(application_id, payload)
    )


@router.get(
    "/applications/{application_id}/entity-model-bindings",
    response_model=list[EntityModelBindingOut],
)
def list_entity_model_bindings(
    application_id: str, request: Request
) -> list[EntityModelBindingOut]:
    return [
        EntityModelBindingOut.model_validate(record)
        for record in _container(request).registry.list_bindings(application_id)
    ]


@router.post(
    "/applications/{application_id}/evidence-items",
    response_model=EvidenceItemOut,
    status_code=201,
)
def create_evidence_item(
    application_id: str, payload: EvidenceItemCreate, request: Request
) -> EvidenceItemOut:
    return EvidenceItemOut.model_validate(
        _container(request).inventory.create_evidence(application_id, payload)
    )


@router.get(
    "/applications/{application_id}/evidence-items",
    response_model=list[EvidenceItemOut],
)
def list_evidence_items(
    application_id: str, request: Request
) -> list[EvidenceItemOut]:
    return [
        EvidenceItemOut.model_validate(record)
        for record in _container(request).inventory.list_evidence(application_id)
    ]


@router.post(
    "/applications/{application_id}/inventory-snapshots",
    response_model=InventorySnapshotOut,
    status_code=201,
)
def create_inventory_snapshot(
    application_id: str, payload: InventorySnapshotCreate, request: Request
) -> InventorySnapshotOut:
    return InventorySnapshotOut.model_validate(
        _container(request).inventory.create_inventory(application_id, payload)
    )


@router.get(
    "/applications/{application_id}/inventory-snapshots",
    response_model=list[InventorySnapshotOut],
)
def list_inventory_snapshots(
    application_id: str, request: Request
) -> list[InventorySnapshotOut]:
    return [
        InventorySnapshotOut.model_validate(record)
        for record in _container(request).inventory.list_inventories(application_id)
    ]


@router.post(
    "/inventory-snapshots/{inventory_id}/data-points",
    response_model=InventoryDataPointOut,
    status_code=201,
)
def add_inventory_data_point(
    inventory_id: str, payload: InventoryDataPointCreate, request: Request
) -> InventoryDataPointOut:
    return InventoryDataPointOut.model_validate(
        _container(request).inventory.add_data_point(inventory_id, payload)
    )


@router.get(
    "/inventory-snapshots/{inventory_id}/data-points",
    response_model=list[InventoryDataPointOut],
)
def list_inventory_data_points(
    inventory_id: str, request: Request
) -> list[InventoryDataPointOut]:
    return [
        InventoryDataPointOut.model_validate(record)
        for record in _container(request).inventory.list_data_points(inventory_id)
    ]


@router.post(
    "/inventory-snapshots/{inventory_id}/freeze",
    response_model=InventorySnapshotOut,
)
def freeze_inventory_snapshot(
    inventory_id: str, request: Request
) -> InventorySnapshotOut:
    return InventorySnapshotOut.model_validate(
        _container(request).inventory.freeze_inventory(inventory_id)
    )


@router.post(
    "/applications/{application_id}/parameter-sets",
    response_model=ParameterSetOut,
    status_code=201,
)
def create_parameter_set(
    application_id: str, payload: ParameterSetCreate, request: Request
) -> ParameterSetOut:
    return ParameterSetOut.model_validate(
        _container(request).inventory.create_parameter_set(application_id, payload)
    )


@router.get(
    "/applications/{application_id}/parameter-sets",
    response_model=list[ParameterSetOut],
)
def list_parameter_sets(
    application_id: str, request: Request
) -> list[ParameterSetOut]:
    return [
        ParameterSetOut.model_validate(record)
        for record in _container(request).inventory.list_parameter_sets(application_id)
    ]


@router.post(
    "/parameter-sets/{parameter_set_id}/freeze", response_model=ParameterSetOut
)
def freeze_parameter_set(
    parameter_set_id: str, request: Request
) -> ParameterSetOut:
    return ParameterSetOut.model_validate(
        _container(request).inventory.freeze_parameter_set(parameter_set_id)
    )


@router.post(
    "/applications/{application_id}/scenarios",
    response_model=ScenarioOut,
    status_code=201,
)
def create_scenario(
    application_id: str, payload: ScenarioCreate, request: Request
) -> ScenarioOut:
    return ScenarioOut.model_validate(
        _container(request).scenarios.create_scenario(application_id, payload)
    )


@router.get(
    "/applications/{application_id}/scenarios", response_model=list[ScenarioOut]
)
def list_scenarios(application_id: str, request: Request) -> list[ScenarioOut]:
    return [
        ScenarioOut.model_validate(record)
        for record in _container(request).scenarios.list_scenarios(application_id)
    ]


@router.post("/scenarios/{scenario_id}/freeze", response_model=ScenarioOut)
def freeze_scenario(scenario_id: str, request: Request) -> ScenarioOut:
    return ScenarioOut.model_validate(
        _container(request).scenarios.freeze_scenario(scenario_id)
    )


@router.post(
    "/applications/{application_id}/analysis-plans",
    response_model=AnalysisPlanOut,
    status_code=201,
)
def create_analysis_plan(
    application_id: str, payload: AnalysisPlanCreate, request: Request
) -> AnalysisPlanOut:
    return AnalysisPlanOut.model_validate(
        _container(request).scenarios.create_plan(application_id, payload)
    )


@router.get(
    "/applications/{application_id}/analysis-plans",
    response_model=list[AnalysisPlanOut],
)
def list_analysis_plans(
    application_id: str, request: Request
) -> list[AnalysisPlanOut]:
    return [
        AnalysisPlanOut.model_validate(record)
        for record in _container(request).scenarios.list_plans(application_id)
    ]


@router.post("/analysis-plans/{plan_id}/freeze", response_model=AnalysisPlanOut)
def freeze_analysis_plan(plan_id: str, request: Request) -> AnalysisPlanOut:
    return AnalysisPlanOut.model_validate(
        _container(request).scenarios.freeze_plan(plan_id)
    )


@router.post(
    "/applications/{application_id}/comparisons",
    response_model=ComparisonOut,
    status_code=201,
)
def create_comparison(
    application_id: str, payload: ComparisonCreate, request: Request
) -> ComparisonOut:
    return ComparisonOut.model_validate(
        _container(request).scenarios.create_comparison(application_id, payload)
    )


@router.get(
    "/applications/{application_id}/comparisons",
    response_model=list[ComparisonOut],
)
def list_comparisons(
    application_id: str, request: Request
) -> list[ComparisonOut]:
    return [
        ComparisonOut.model_validate(record)
        for record in _container(request).scenarios.list_comparisons(application_id)
    ]


@router.post(
    "/comparisons/{comparison_id}/execute",
    response_model=ScenarioComparisonRunOut,
    status_code=201,
)
def execute_scenario_comparison(
    comparison_id: str,
    payload: ScenarioComparisonExecuteCreate,
    request: Request,
) -> ScenarioComparisonRunOut:
    return ScenarioComparisonRunOut.model_validate(
        _container(request).scenario_comparisons.execute(comparison_id, payload)
    )


@router.post(
    "/comparisons/{comparison_id}/execute/queue",
    response_model=QueuedScenarioComparisonRunOut,
    status_code=202,
)
def queue_scenario_comparison(
    comparison_id: str,
    payload: ScenarioComparisonExecuteCreate,
    request: Request,
) -> QueuedScenarioComparisonRunOut:
    run, event, _ = _container(request).scenario_comparisons.submit(
        comparison_id, payload
    )
    return QueuedScenarioComparisonRunOut(
        run=ScenarioComparisonRunOut.model_validate(run),
        task=OutboxEventOut.model_validate(event),
    )


@router.get(
    "/scenario-comparison-runs/{run_id}",
    response_model=ScenarioComparisonRunOut,
)
def get_scenario_comparison_run(
    run_id: str, request: Request
) -> ScenarioComparisonRunOut:
    return ScenarioComparisonRunOut.model_validate(
        _container(request).scenario_comparisons.get(run_id)
    )


@router.get(
    "/applications/{application_id}/scenario-comparison-runs",
    response_model=list[ScenarioComparisonRunOut],
)
def list_scenario_comparison_runs(
    application_id: str, request: Request
) -> list[ScenarioComparisonRunOut]:
    return [
        ScenarioComparisonRunOut.model_validate(record)
        for record in _container(request).scenario_comparisons.list_for_application(
            application_id
        )
    ]


@router.get("/scenario-comparison-runs/{run_id}/chart.svg")
def render_scenario_comparison_chart(run_id: str, request: Request) -> Response:
    return Response(
        content=_container(request).scenario_comparisons.chart_svg(run_id),
        media_type="image/svg+xml",
    )


@router.post(
    "/applications/{application_id}/solved-system-snapshots",
    response_model=SolvedSystemSnapshotOut,
    status_code=201,
)
def import_solved_system_snapshot(
    application_id: str, payload: SolvedSystemSnapshotCreate, request: Request
) -> SolvedSystemSnapshotOut:
    return SolvedSystemSnapshotOut.model_validate(
        _container(request).results.import_solved_snapshot(application_id, payload)
    )


@router.post(
    "/applications/{application_id}/system-revisions/{system_revision_id}/solve",
    response_model=SolvedSystemSnapshotOut,
    status_code=201,
)
def solve_and_freeze_system_revision(
    application_id: str,
    system_revision_id: str,
    payload: ProviderSolveAndFreezeCreate,
    request: Request,
) -> SolvedSystemSnapshotOut:
    return SolvedSystemSnapshotOut.model_validate(
        _container(request).provider_solves.solve_and_freeze(
            application_id, system_revision_id, payload
        )
    )


@router.post(
    "/applications/{application_id}/system-revisions/{system_revision_id}/solve/queue",
    response_model=QueuedAnalysisRunOut,
    status_code=202,
)
def queue_solve_and_freeze_system_revision(
    application_id: str,
    system_revision_id: str,
    payload: ProviderSolveAndFreezeCreate,
    request: Request,
) -> QueuedAnalysisRunOut:
    run, event, _ = _container(request).provider_solves.submit_solve_and_freeze(
        application_id,
        system_revision_id,
        payload,
    )
    return QueuedAnalysisRunOut(
        run=AnalysisRunOut.model_validate(run),
        task=OutboxEventOut.model_validate(event),
    )


@router.get(
    "/applications/{application_id}/solved-system-snapshots",
    response_model=list[SolvedSystemSnapshotOut],
)
def list_solved_system_snapshots(
    application_id: str, request: Request
) -> list[SolvedSystemSnapshotOut]:
    return [
        SolvedSystemSnapshotOut.model_validate(record)
        for record in _container(request).results.list_solved_snapshots(application_id)
    ]


@router.get("/solved-system-snapshots/{solved_snapshot_id}/mfa")
def analyze_solved_mfa(
    solved_snapshot_id: str,
    request: Request,
    tolerance: float = Query(default=1e-9, ge=0),
) -> dict:
    return _container(request).solved_mfa.analyze(
        solved_snapshot_id, tolerance=tolerance
    )


@router.get("/solved-system-snapshots/{solved_snapshot_id}/mfa/sankey.svg")
def render_solved_mfa_sankey(
    solved_snapshot_id: str,
    request: Request,
    series_id: str | None = None,
    tolerance: float = Query(default=1e-9, ge=0),
) -> Response:
    svg = _container(request).solved_mfa.sankey_svg(
        solved_snapshot_id,
        series_id=series_id,
        tolerance=tolerance,
    )
    return Response(content=svg, media_type="image/svg+xml")


@router.get("/solved-system-snapshots/{solved_snapshot_id}/product-carbon-footprint/default-method",
            response_model=ClimateMethodResolutionOut)
def default_product_carbon_footprint_method(solved_snapshot_id: str, request: Request) -> ClimateMethodResolutionOut:
    return ClimateMethodResolutionOut.model_validate(
        _container(request).product_carbon_footprints.default_method(solved_snapshot_id)
    )


@router.post(
    "/solved-system-snapshots/{solved_snapshot_id}/product-carbon-footprint",
    response_model=ProductCarbonFootprintOut,
)
def analyze_product_carbon_footprint(
    solved_snapshot_id: str,
    payload: ProductCarbonFootprintCreate,
    request: Request,
) -> ProductCarbonFootprintOut:
    return ProductCarbonFootprintOut.model_validate(
        _container(request).product_carbon_footprints.analyze(
            solved_snapshot_id, payload
        )
    )


@router.post(
    "/solved-system-snapshots/{solved_snapshot_id}/product-carbon-footprint/chart.svg"
)
def render_product_carbon_footprint_chart(
    solved_snapshot_id: str,
    payload: ProductCarbonFootprintCreate,
    request: Request,
) -> Response:
    result = _container(request).product_carbon_footprints.analyze(
        solved_snapshot_id, payload
    )
    return Response(
        content=render_product_pcf_svg(result), media_type="image/svg+xml"
    )


@router.get(
    "/solved-system-snapshots/{solved_snapshot_id}/product-carbon-footprint/chart.svg"
)
def get_product_carbon_footprint_chart(
    solved_snapshot_id: str,
    request: Request,
    method_package_ref: str = Query(min_length=3, max_length=320),
) -> Response:
    result = _container(request).product_carbon_footprints.analyze(
        solved_snapshot_id,
        ProductCarbonFootprintCreate(method_package_ref=method_package_ref),
    )
    return Response(
        content=render_product_pcf_svg(result), media_type="image/svg+xml"
    )


@router.get(
    "/solved-system-snapshots/{solved_snapshot_id}/product-carbon-footprint/export.xlsx"
)
def export_product_carbon_footprint_xlsx(
    solved_snapshot_id: str,
    request: Request,
    method_package_ref: str = Query(min_length=3, max_length=320),
) -> Response:
    content, result = _container(request).product_carbon_footprints.export_xlsx(
        solved_snapshot_id,
        ProductCarbonFootprintCreate(method_package_ref=method_package_ref),
    )
    result_hash = result["content_sha256"]
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="nebula-one-pcf-{result_hash[:12]}.xlsx"',
            "ETag": f'"{result_hash}"',
            "X-Nebula-Result-SHA256": result_hash,
        },
    )


@router.get(
    "/solved-system-snapshots/{solved_snapshot_id}/product-carbon-footprint/report.html"
)
def report_product_carbon_footprint_html(
    solved_snapshot_id: str,
    request: Request,
    method_package_ref: str = Query(min_length=3, max_length=320),
) -> Response:
    content, result = _container(request).product_carbon_footprints.report_html(
        solved_snapshot_id,
        ProductCarbonFootprintCreate(method_package_ref=method_package_ref),
    )
    result_hash = result["content_sha256"]
    return Response(
        content=content,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Disposition": f'inline; filename="nebula-one-pcf-{result_hash[:12]}.html"',
            "ETag": f'"{result_hash}"',
            "X-Nebula-Result-SHA256": result_hash,
        },
    )


@router.get(
    "/solved-system-snapshots/{solved_snapshot_id}/native-background-climate/export.xlsx"
)
def export_native_background_climate_xlsx(
    solved_snapshot_id: str,
    request: Request,
) -> Response:
    content, snapshot_hash = (
        _container(request).native_climate_artifacts.export_xlsx(solved_snapshot_id)
    )
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="nebula-one-native-background-climate-{snapshot_hash[:12]}.xlsx"',
            "ETag": f'"{snapshot_hash}"',
            "X-Nebula-Result-SHA256": snapshot_hash,
        },
    )


@router.get(
    "/solved-system-snapshots/{solved_snapshot_id}/native-background-climate/report.html"
)
def report_native_background_climate_html(
    solved_snapshot_id: str,
    request: Request,
) -> Response:
    content, snapshot_hash = (
        _container(request).native_climate_artifacts.report_html(solved_snapshot_id)
    )
    return Response(
        content=content,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Disposition": f'inline; filename="nebula-one-native-background-climate-{snapshot_hash[:12]}.html"',
            "ETag": f'"{snapshot_hash}"',
            "X-Nebula-Result-SHA256": snapshot_hash,
        },
    )


@router.post(
    "/solved-system-snapshots/{solved_snapshot_id}/carbon-management",
    response_model=CarbonManagementOut,
)
def analyze_carbon_management(
    solved_snapshot_id: str,
    payload: CarbonManagementCreate,
    request: Request,
) -> CarbonManagementOut:
    return CarbonManagementOut.model_validate(
        _container(request).carbon_management.analyze(solved_snapshot_id, payload)
    )


@router.post(
    "/solved-system-snapshots/{solved_snapshot_id}/carbon-management/chart.svg"
)
def render_carbon_management_chart(
    solved_snapshot_id: str,
    payload: CarbonManagementCreate,
    request: Request,
) -> Response:
    result = _container(request).carbon_management.analyze(solved_snapshot_id, payload)
    return Response(content=render_carbon_management_svg(result), media_type="image/svg+xml")


@router.post(
    "/solved-system-snapshots/{solved_snapshot_id}/cbam-trial",
    response_model=CbamTrialOut | CbamTrialV2Out,
    # the two profiles share one route and one content hash; dumping a declared-but-unset field
    # would put a key on the wire that the analyzed content never contained
    response_model_exclude_unset=True,
)
def analyze_cbam_trial(
    solved_snapshot_id: str,
    payload: CbamTrialCreate,
    request: Request,
) -> CbamTrialOut | CbamTrialV2Out:
    result = _container(request).cbam_trials.analyze(solved_snapshot_id, payload)
    model = (
        CbamTrialV2Out
        if result.get("schema_version") == CBAM_TRIAL_V2_SCHEMA_VERSION
        else CbamTrialOut
    )
    return model.model_validate(result)


@router.post("/solved-system-snapshots/{solved_snapshot_id}/cbam-partial-review")
def analyze_cbam_partial_review(
    solved_snapshot_id: str, payload: CbamPartialReviewCreate, request: Request,
) -> dict:
    return _container(request).cbam_partial_review.analyze(solved_snapshot_id, payload)


@router.post("/solved-system-snapshots/{solved_snapshot_id}/cbam-partial-review/report.md")
def export_cbam_partial_review(
    solved_snapshot_id: str, payload: CbamPartialReviewCreate, request: Request,
) -> Response:
    result = _container(request).cbam_partial_review.analyze(solved_snapshot_id, payload)
    return Response(content=render_cbam_partial_review_markdown(result),
                    media_type="text/markdown; charset=utf-8",
                    headers={"ETag": f'"{result["content_sha256"]}"'})


@router.post("/solved-system-snapshots/{solved_snapshot_id}/cbam-trial/report.html")
def export_cbam_trial_report(
    solved_snapshot_id: str, payload: CbamTrialCreate, request: Request,
) -> Response:
    result = _container(request).cbam_trials.analyze(solved_snapshot_id, payload)
    if result.get("schema_version") != CBAM_TRIAL_V2_SCHEMA_VERSION:
        from .errors import DomainError
        raise DomainError(code="CBAM_TRIAL_REPORT_SCHEMA_UNSUPPORTED",
                          message="此导出只支持已冻结边界的 CBAM v2 试算。", status_code=422)
    return Response(
        content=render_cbam_trial_html(result), media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="cbam-trial-report.html"'},
    )


@router.post(
    "/solved-system-snapshots/{solved_snapshot_id}/cbam-trial/chart.svg"
)
def render_cbam_trial_chart(
    solved_snapshot_id: str,
    payload: CbamTrialCreate,
    request: Request,
) -> Response:
    return Response(
        content=_container(request).cbam_trials.chart_svg(solved_snapshot_id, payload),
        media_type="image/svg+xml",
    )


@router.post(
    "/solved-system-snapshots/{solved_snapshot_id}/cbam-complex-trial",
    response_model=CbamComplexTrialOut,
)
def analyze_cbam_complex_trial(
    solved_snapshot_id: str,
    payload: CbamComplexTrialCreate,
    request: Request,
) -> CbamComplexTrialOut:
    return CbamComplexTrialOut.model_validate(
        _container(request).cbam_complex_trials.analyze(
            solved_snapshot_id, payload
        )
    )


@router.post(
    "/solved-system-snapshots/{solved_snapshot_id}/cbam-complex-trial/chart.svg"
)
def render_cbam_complex_trial_chart(
    solved_snapshot_id: str,
    payload: CbamComplexTrialCreate,
    request: Request,
) -> Response:
    return Response(
        content=_container(request).cbam_complex_trials.chart_svg(
            solved_snapshot_id, payload
        ),
        media_type="image/svg+xml",
    )


@router.post(
    "/solved-system-snapshots/{solved_snapshot_id}/spatial-aggregate",
    response_model=SpatialAggregateOut,
)
def analyze_spatial_aggregate(
    solved_snapshot_id: str, payload: SpatialAggregateCreate, request: Request
) -> SpatialAggregateOut:
    return SpatialAggregateOut.model_validate(
        _container(request).spatial_aggregate.analyze(solved_snapshot_id, payload)
    )


@router.post(
    "/solved-system-snapshots/{solved_snapshot_id}/spatial-aggregate/sankey.svg"
)
def render_spatial_aggregate_chart(
    solved_snapshot_id: str, payload: SpatialAggregateCreate, request: Request
) -> Response:
    return Response(
        content=_container(request).spatial_aggregate.sankey_svg(
            solved_snapshot_id, payload
        ),
        media_type="image/svg+xml",
    )


@router.post(
    "/solved-system-snapshots/{solved_snapshot_id}/spatial-energy",
    response_model=SpatialEnergyOut,
)
def analyze_spatial_energy(
    solved_snapshot_id: str, payload: SpatialEnergyCreate, request: Request
) -> SpatialEnergyOut:
    return SpatialEnergyOut.model_validate(
        _container(request).spatial_energy.analyze(solved_snapshot_id, payload)
    )


@router.post(
    "/solved-system-snapshots/{solved_snapshot_id}/spatial-energy/sankey.svg"
)
def render_spatial_energy_chart(
    solved_snapshot_id: str, payload: SpatialEnergyCreate, request: Request
) -> Response:
    return Response(
        content=_container(request).spatial_energy.sankey_svg(
            solved_snapshot_id, payload
        ),
        media_type="image/svg+xml",
    )


@router.post(
    "/solved-system-snapshots/{solved_snapshot_id}/spatial-energy-flow",
    response_model=SpatialEnergyFlowOut,
)
def analyze_spatial_energy_flow(
    solved_snapshot_id: str,
    payload: SpatialEnergyFlowCreate,
    request: Request,
) -> SpatialEnergyFlowOut:
    return SpatialEnergyFlowOut.model_validate(
        _container(request).spatial_energy_flows.analyze(solved_snapshot_id, payload)
    )


@router.post(
    "/solved-system-snapshots/{solved_snapshot_id}/spatial-energy-flow/sankey.svg"
)
def render_spatial_energy_flow_chart(
    solved_snapshot_id: str,
    payload: SpatialEnergyFlowCreate,
    request: Request,
) -> Response:
    return Response(
        content=_container(request).spatial_energy_flows.sankey_svg(
            solved_snapshot_id, payload
        ),
        media_type="image/svg+xml",
    )


@router.post(
    "/solved-system-snapshots/{solved_snapshot_id}/spatial-distribution",
    response_model=SpatialDistributionOut,
)
def analyze_spatial_distribution(
    solved_snapshot_id: str,
    payload: SpatialDistributionCreate,
    request: Request,
) -> SpatialDistributionOut:
    return SpatialDistributionOut.model_validate(
        _container(request).spatial_distribution.analyze(solved_snapshot_id, payload)
    )


@router.post(
    "/solved-system-snapshots/{solved_snapshot_id}/spatial-distribution/map.svg"
)
def render_spatial_distribution_map(
    solved_snapshot_id: str,
    payload: SpatialDistributionCreate,
    request: Request,
) -> Response:
    return Response(
        content=_container(request).spatial_distribution.map_svg(
            solved_snapshot_id, payload
        ),
        media_type="image/svg+xml",
    )


@router.post(
    "/scenario-comparison-runs/{run_id}/period-energy-comparison",
    response_model=PeriodEnergyComparisonOut,
)
def analyze_period_energy_comparison(
    run_id: str,
    payload: PeriodEnergyComparisonCreate,
    request: Request,
) -> PeriodEnergyComparisonOut:
    return PeriodEnergyComparisonOut.model_validate(
        _container(request).period_energy_comparisons.analyze(run_id, payload)
    )


@router.post(
    "/scenario-comparison-runs/{run_id}/period-energy-comparison/chart.svg"
)
def render_period_energy_comparison_chart(
    run_id: str,
    payload: PeriodEnergyComparisonCreate,
    request: Request,
) -> Response:
    return Response(
        content=_container(request).period_energy_comparisons.chart_svg(
            run_id, payload
        ),
        media_type="image/svg+xml",
    )


@router.post(
    "/applications/{application_id}/period-energy-trend",
    response_model=PeriodEnergyTrendOut,
)
def analyze_period_energy_trend(
    application_id: str,
    payload: PeriodEnergyTrendCreate,
    request: Request,
) -> PeriodEnergyTrendOut:
    return PeriodEnergyTrendOut.model_validate(
        _container(request).period_energy_trends.analyze(application_id, payload)
    )


@router.post("/applications/{application_id}/period-energy-trend/chart.svg")
def render_period_energy_trend_chart(
    application_id: str,
    payload: PeriodEnergyTrendCreate,
    request: Request,
) -> Response:
    return Response(
        content=_container(request).period_energy_trends.chart_svg(
            application_id, payload
        ),
        media_type="image/svg+xml",
    )


@router.post(
    "/applications/{application_id}/period-energy-total",
    response_model=PeriodEnergyTotalOut,
)
def analyze_period_energy_total(
    application_id: str,
    payload: PeriodEnergyTotalCreate,
    request: Request,
) -> PeriodEnergyTotalOut:
    return PeriodEnergyTotalOut.model_validate(
        _container(request).period_energy_totals.analyze(application_id, payload)
    )


@router.post("/applications/{application_id}/period-energy-total/chart.svg")
def render_period_energy_total_chart(
    application_id: str,
    payload: PeriodEnergyTotalCreate,
    request: Request,
) -> Response:
    return Response(
        content=_container(request).period_energy_totals.chart_svg(
            application_id, payload
        ),
        media_type="image/svg+xml",
    )


@router.post(
    "/applications/{application_id}/province-electricity-scenarios",
    response_model=ProvinceElectricityOut,
)
def analyze_province_electricity_scenarios(
    application_id: str,
    payload: ProvinceElectricityCreate,
    request: Request,
) -> ProvinceElectricityOut:
    return ProvinceElectricityOut.model_validate(
        _container(request).province_electricity.analyze(application_id, payload)
    )


@router.post(
    "/applications/{application_id}/province-electricity-scenarios/chart.svg"
)
def render_province_electricity_scenarios_chart(
    application_id: str,
    payload: ProvinceElectricityCreate,
    request: Request,
) -> Response:
    return Response(
        content=_container(request).province_electricity.chart_svg(
            application_id, payload
        ),
        media_type="image/svg+xml",
    )


@router.post(
    "/applications/{application_id}/organization-ghg-inventory-trial",
    response_model=OrganizationGhgInventoryOut,
)
def analyze_organization_ghg_inventory(
    application_id: str,
    payload: OrganizationGhgInventoryCreate,
    request: Request,
) -> OrganizationGhgInventoryOut:
    return OrganizationGhgInventoryOut.model_validate(
        _container(request).organization_ghg_inventory.analyze(
            application_id, payload
        )
    )


@router.post(
    "/applications/{application_id}/organization-period-inventories",
    response_model=OrganizationPeriodOut, status_code=201,
)
def create_organization_period_inventory(
    application_id: str, payload: OrganizationPeriodCreate, request: Request,
) -> OrganizationPeriodOut:
    return OrganizationPeriodOut.model_validate(
        _container(request).organization_period.create(application_id, payload)
    )


@router.get(
    "/applications/{application_id}/organization-period-inventories",
    response_model=list[OrganizationPeriodOut],
)
def list_organization_period_inventories(
    application_id: str, request: Request,
) -> list[OrganizationPeriodOut]:
    return [OrganizationPeriodOut.model_validate(item) for item in
            _container(request).organization_period.list(application_id)]


@router.get(
    "/applications/{application_id}/organization-period-inventories/{record_id}",
    response_model=OrganizationPeriodOut,
)
def get_organization_period_inventory(
    application_id: str, record_id: str, request: Request,
) -> OrganizationPeriodOut:
    return OrganizationPeriodOut.model_validate(
        _container(request).organization_period.get(application_id, record_id)
    )


@router.get("/applications/{application_id}/organization-period-inventories/{record_id}/report.html")
def report_organization_period_inventory(application_id: str, record_id: str, request: Request) -> Response:
    record = _container(request).organization_period.get(application_id, record_id)
    return Response(content=render_organization_period_html(record), media_type="text/html; charset=utf-8",
                    headers={"ETag": f'"{record["content_sha256"]}"',
                             "X-Nebula-Result-SHA256": record["content_sha256"]})


@router.post("/applications/{application_id}/organization-lifecycle-inventories", status_code=201)
def create_organization_lifecycle_inventory(
    application_id: str, payload: OrganizationLifecycleCreate, request: Request,
) -> dict:
    return _container(request).organization_lifecycle.create(application_id, payload)


@router.get("/applications/{application_id}/organization-lifecycle-inventories")
def list_organization_lifecycle_inventories(application_id: str, request: Request) -> list[dict]:
    return _container(request).organization_lifecycle.list(application_id)


@router.get("/applications/{application_id}/organization-lifecycle-inventories/{record_id}")
def get_organization_lifecycle_inventory(application_id: str, record_id: str, request: Request) -> dict:
    return _container(request).organization_lifecycle.get(application_id, record_id)


@router.get("/applications/{application_id}/organization-lifecycle-inventories/{record_id}/report.html")
def report_organization_lifecycle_inventory(application_id: str, record_id: str, request: Request) -> Response:
    record = _container(request).organization_lifecycle.get(application_id, record_id)
    return Response(content=render_organization_lifecycle_html(record), media_type="text/html; charset=utf-8",
                    headers={"ETag": f'"{record["content_sha256"]}"'})


@router.post(
    "/applications/{application_id}/organization-ghg-inventory",
    response_model=OrganizationGhgInventoryV1Out,
)
def aggregate_organization_ghg_inventory(
    application_id: str,
    payload: OrganizationGhgInventoryV1Create,
    request: Request,
) -> OrganizationGhgInventoryV1Out:
    return OrganizationGhgInventoryV1Out.model_validate(
        _container(request).organization_ghg_inventory.aggregate(
            application_id, payload
        )
    )


@router.post(
    "/applications/{application_id}/organization-ghg-inventory/chart.svg"
)
def render_organization_ghg_inventory_v1_chart(
    application_id: str,
    payload: OrganizationGhgInventoryV1Create,
    request: Request,
) -> Response:
    return Response(
        content=_container(request).organization_ghg_inventory.aggregate_chart_svg(
            application_id, payload
        ),
        media_type="image/svg+xml",
    )


@router.post(
    "/applications/{application_id}/organization-ghg-inventory-trial/chart.svg"
)
def render_organization_ghg_inventory_chart(
    application_id: str,
    payload: OrganizationGhgInventoryCreate,
    request: Request,
) -> Response:
    return Response(
        content=_container(request).organization_ghg_inventory.chart_svg(
            application_id, payload
        ),
        media_type="image/svg+xml",
    )


@router.post(
    "/solved-system-snapshots/{solved_snapshot_id}/energy-carrier-results",
    response_model=EnergyCarrierResultOut,
    status_code=201,
)
def create_energy_carrier_result(
    solved_snapshot_id: str,
    payload: EnergyCarrierResultCreate,
    request: Request,
) -> EnergyCarrierResultOut:
    return EnergyCarrierResultOut.model_validate(
        _container(request).energy_carrier_results.create(solved_snapshot_id, payload)
    )


@router.get(
    "/solved-system-snapshots/{solved_snapshot_id}/energy-carrier-results",
    response_model=list[EnergyCarrierResultOut],
)
def list_energy_carrier_results(
    solved_snapshot_id: str,
    request: Request,
) -> list[EnergyCarrierResultOut]:
    return [
        EnergyCarrierResultOut.model_validate(record)
        for record in _container(request).energy_carrier_results.list_for_snapshot(
            solved_snapshot_id
        )
    ]


@router.get(
    "/energy-carrier-results/{result_id}",
    response_model=EnergyCarrierResultOut,
)
def get_energy_carrier_result(
    result_id: str,
    request: Request,
) -> EnergyCarrierResultOut:
    return EnergyCarrierResultOut.model_validate(
        _container(request).energy_carrier_results.get(result_id)
    )


@router.get("/energy-carrier-results/{result_id}/chart.svg")
def render_energy_carrier_chart(result_id: str, request: Request) -> Response:
    return Response(
        content=_container(request).energy_carrier_results.chart_svg(result_id),
        media_type="image/svg+xml",
    )


@router.post(
    "/solved-system-snapshots/{solved_snapshot_id}/energy-flow",
    response_model=EnergyFlowOut,
)
def analyze_energy_flow(
    solved_snapshot_id: str,
    payload: EnergyFlowCreate,
    request: Request,
) -> EnergyFlowOut:
    return EnergyFlowOut.model_validate(
        _container(request).energy_flows.analyze(solved_snapshot_id, payload)
    )


@router.post("/solved-system-snapshots/{solved_snapshot_id}/energy-flow/sankey.svg")
def render_energy_flow_sankey(
    solved_snapshot_id: str,
    payload: EnergyFlowCreate,
    request: Request,
) -> Response:
    return Response(
        content=_container(request).energy_flows.sankey_svg(solved_snapshot_id, payload),
        media_type="image/svg+xml",
    )


@router.post(
    "/solved-system-snapshots/{solved_snapshot_id}/water-balance",
    response_model=WaterBalanceOut,
)
def analyze_water_balance(
    solved_snapshot_id: str,
    payload: WaterBalanceCreate,
    request: Request,
) -> WaterBalanceOut:
    return WaterBalanceOut.model_validate(
        _container(request).water_balances.analyze(solved_snapshot_id, payload)
    )


@router.post(
    "/solved-system-snapshots/{solved_snapshot_id}/water-balance/sankey.svg"
)
def render_water_balance_sankey(
    solved_snapshot_id: str,
    payload: WaterBalanceCreate,
    request: Request,
) -> Response:
    return Response(
        content=_container(request).water_balances.sankey_svg(
            solved_snapshot_id, payload
        ),
        media_type="image/svg+xml",
    )


@router.post(
    "/applications/{application_id}/result-sets",
    response_model=ResultSetOut,
    status_code=201,
)
def create_result_set(
    application_id: str, payload: ResultSetCreate, request: Request
) -> ResultSetOut:
    return ResultSetOut.model_validate(
        _container(request).results.create_result_set(application_id, payload)
    )


@router.get(
    "/applications/{application_id}/result-sets",
    response_model=list[ResultSetOut],
)
def list_result_sets(
    application_id: str, request: Request
) -> list[ResultSetOut]:
    return [
        ResultSetOut.model_validate(record)
        for record in _container(request).results.list_result_sets(application_id)
    ]


@router.post(
    "/applications/{application_id}/evidence-packs",
    response_model=EvidencePackOut,
    status_code=201,
)
def create_evidence_pack(
    application_id: str, payload: EvidencePackCreate, request: Request
) -> EvidencePackOut:
    return EvidencePackOut.model_validate(
        _container(request).results.create_evidence_pack(application_id, payload)
    )


@router.get(
    "/applications/{application_id}/evidence-packs",
    response_model=list[EvidencePackOut],
)
def list_evidence_packs(
    application_id: str, request: Request
) -> list[EvidencePackOut]:
    return [
        EvidencePackOut.model_validate(record)
        for record in _container(request).results.list_evidence_packs(application_id)
    ]
