from __future__ import annotations

from dataclasses import dataclass

from .adapters.nebula_lca import NebulaLCAClient
from .blueprint import ProductBlueprint
from .config import Settings
from .database import Database
from .profiles import ApplicationProfiles
from .native_climate_contract import NativeClimateContract
from .services.analysis_runs import ANALYSIS_EXECUTE_TOPIC, AnalysisRunService
from .services.applications import ApplicationService
from .services.system_models import SystemModelService
from .services.model_sources import ModelSourceService
from .services.system_bindings import SystemBindingService
from .services.system_revisions import SystemRevisionService
from .services.inventory import InventoryService
from .services.registry import RegistryService
from .services.results import ResultService
from .services.energy_carrier import EnergyCarrierResultService
from .services.energy_flow import EnergyFlowService
from .services.water_balance import WaterBalanceService
from .services.casepack_materialization import CasePackMaterializationService
from .services.provider_solve import ProviderSolveService, SOLVE_AND_FREEZE_TOPIC
from .services.scenarios import ScenarioService
from .services.scenario_comparisons import (
    SCENARIO_COMPARISON_EXECUTE_TOPIC,
    ScenarioComparisonService,
)
from .services.solved_mfa import SolvedMFAService
from .services.parameter_bindings import ParameterBindingService
from .services.pcf import ProductCarbonFootprintService
from .services.native_climate import NativeClimateArtifactService
from .services.carbon_management import CarbonManagementService
from .services.cbam_trial import CbamTrialService
from .services.cbam_partial_review import CbamPartialReviewService
from .services.cbam_complex_trial import CbamComplexTrialService
from .services.spatial_aggregate import SpatialAggregateService
from .services.spatial_energy import SpatialEnergyService
from .services.spatial_energy_flow import SpatialEnergyFlowService
from .services.spatial_distribution import SpatialDistributionService
from .services.period_energy import PeriodEnergyComparisonService
from .services.period_energy_trend import PeriodEnergyTrendService
from .services.period_energy_total import PeriodEnergyTotalService
from .services.province_electricity import ProvinceElectricityService
from .services.organization_ghg_inventory import OrganizationGhgInventoryService
from .services.organization_period import OrganizationPeriodService
from .services.organization_lifecycle import OrganizationLifecycleService
from .services.outbox import OutboxService, OutboxWorker
from .services.seed_autoload import SeedAutoloadService
from .services.seed_installation import SeedInstallationService
from .casepacks.catalog import CasePackCatalog
from .release_catalog import ReleaseCatalog


@dataclass(slots=True)
class Container:
    settings: Settings
    database: Database
    client: NebulaLCAClient
    profiles: ApplicationProfiles
    blueprint: ProductBlueprint
    native_climate: NativeClimateContract
    applications: ApplicationService
    system_models: SystemModelService
    model_sources: ModelSourceService
    system_bindings: SystemBindingService
    system_revisions: SystemRevisionService
    analysis_runs: AnalysisRunService
    registry: RegistryService
    inventory: InventoryService
    scenarios: ScenarioService
    results: ResultService
    provider_solves: ProviderSolveService
    solved_mfa: SolvedMFAService
    energy_carrier_results: EnergyCarrierResultService
    energy_flows: EnergyFlowService
    water_balances: WaterBalanceService
    product_carbon_footprints: ProductCarbonFootprintService
    native_climate_artifacts: NativeClimateArtifactService
    carbon_management: CarbonManagementService
    cbam_trials: CbamTrialService
    cbam_partial_review: CbamPartialReviewService
    cbam_complex_trials: CbamComplexTrialService
    spatial_aggregate: SpatialAggregateService
    spatial_energy: SpatialEnergyService
    spatial_energy_flows: SpatialEnergyFlowService
    spatial_distribution: SpatialDistributionService
    period_energy_comparisons: PeriodEnergyComparisonService
    period_energy_trends: PeriodEnergyTrendService
    period_energy_totals: PeriodEnergyTotalService
    province_electricity: ProvinceElectricityService
    organization_ghg_inventory: OrganizationGhgInventoryService
    organization_period: OrganizationPeriodService
    organization_lifecycle: OrganizationLifecycleService
    scenario_comparisons: ScenarioComparisonService
    parameter_bindings: ParameterBindingService
    casepacks: CasePackCatalog
    casepack_materialization: CasePackMaterializationService
    outbox: OutboxService
    worker: OutboxWorker
    seed_installation: SeedInstallationService
    seed_autoload: SeedAutoloadService
    release_catalog: ReleaseCatalog


def build_container(
    settings: Settings,
    *,
    engine_transport=None,
) -> Container:
    database = Database(settings)
    profiles = ApplicationProfiles(settings.profile_file)
    blueprint = ProductBlueprint()
    native_climate = NativeClimateContract(settings.native_climate_contract_file)
    from .native_inventory_contract import NativeInventoryContract
    native_inventory = NativeInventoryContract(settings.native_inventory_contract_file)
    client = NebulaLCAClient(
        settings.nebula_lca_base_url,
        settings.nebula_lca_timeout_seconds,
        transport=engine_transport,
    )
    outbox = OutboxService(database)
    analysis_runs = AnalysisRunService(database, client, outbox)
    results = ResultService(database)
    provider_solves = ProviderSolveService(
        database, analysis_runs, results, native_climate, native_inventory
    )
    solved_mfa = SolvedMFAService(database, client, settings.casepack_roots)
    energy_carrier_results = EnergyCarrierResultService(database)
    energy_flows = EnergyFlowService(database)
    water_balances = WaterBalanceService(database)
    product_carbon_footprints = ProductCarbonFootprintService(database)
    native_climate_artifacts = NativeClimateArtifactService(database)
    carbon_management = CarbonManagementService(database)
    cbam_trials = CbamTrialService(database)
    cbam_complex_trials = CbamComplexTrialService(database)
    spatial_aggregate = SpatialAggregateService(database)
    spatial_energy = SpatialEnergyService(database, spatial_aggregate)
    spatial_energy_flows = SpatialEnergyFlowService(
        database, energy_flows, spatial_aggregate
    )
    spatial_distribution = SpatialDistributionService(database)
    period_energy_comparisons = PeriodEnergyComparisonService(database)
    period_energy_trends = PeriodEnergyTrendService(database)
    period_energy_totals = PeriodEnergyTotalService(database)
    province_electricity = ProvinceElectricityService(database)
    organization_ghg_inventory = OrganizationGhgInventoryService(database)
    organization_period = OrganizationPeriodService(database)
    release_catalog = ReleaseCatalog(settings.release_catalog_file)
    casepacks = CasePackCatalog(settings.casepack_roots, release_catalog)
    casepack_materialization = CasePackMaterializationService(
        database, client, profiles, casepacks
    )
    scenario_comparisons = ScenarioComparisonService(
        database,
        provider_solves,
        solved_mfa,
        product_carbon_footprints,
        outbox,
    )
    worker = OutboxWorker(
        outbox,
        {
            ANALYSIS_EXECUTE_TOPIC: analysis_runs.handle_outbox,
            SOLVE_AND_FREEZE_TOPIC: provider_solves.handle_outbox,
            SCENARIO_COMPARISON_EXECUTE_TOPIC: scenario_comparisons.handle_outbox,
        },
    )
    system_revisions = SystemRevisionService(database, client)
    system_models = SystemModelService(database, client)
    applications = ApplicationService(database, profiles)
    registry = RegistryService(database)
    seed_installation = SeedInstallationService(database, client, system_models)
    container = Container(
        settings=settings,
        database=database,
        client=client,
        profiles=profiles,
        blueprint=blueprint,
        native_climate=native_climate,
        applications=applications,
        system_models=system_models,
        model_sources=ModelSourceService(database, client, system_models),
        system_bindings=SystemBindingService(database),
        system_revisions=system_revisions,
        analysis_runs=analysis_runs,
        registry=registry,
        inventory=InventoryService(database),
        scenarios=ScenarioService(database),
        results=results,
        provider_solves=provider_solves,
        solved_mfa=solved_mfa,
        energy_carrier_results=energy_carrier_results,
        energy_flows=energy_flows,
        water_balances=water_balances,
        product_carbon_footprints=product_carbon_footprints,
        native_climate_artifacts=native_climate_artifacts,
        carbon_management=carbon_management,
        cbam_trials=cbam_trials,
        cbam_partial_review=CbamPartialReviewService(database),
        cbam_complex_trials=cbam_complex_trials,
        spatial_aggregate=spatial_aggregate,
        spatial_energy=spatial_energy,
        spatial_energy_flows=spatial_energy_flows,
        spatial_distribution=spatial_distribution,
        period_energy_comparisons=period_energy_comparisons,
        period_energy_trends=period_energy_trends,
        period_energy_totals=period_energy_totals,
        province_electricity=province_electricity,
        organization_ghg_inventory=organization_ghg_inventory,
        organization_period=organization_period,
        organization_lifecycle=OrganizationLifecycleService(database),
        scenario_comparisons=scenario_comparisons,
        parameter_bindings=ParameterBindingService(database, system_revisions),
        casepacks=casepacks,
        casepack_materialization=casepack_materialization,
        outbox=outbox,
        worker=worker,
        seed_installation=seed_installation,
        release_catalog=release_catalog,
        seed_autoload=SeedAutoloadService(
            applications, registry, seed_installation, settings.seed_autoload_file
        ),
    )
    from .services.seed_projects import SeedProjectService

    container.seed_autoload.seed_projects = SeedProjectService(container)
    return container
