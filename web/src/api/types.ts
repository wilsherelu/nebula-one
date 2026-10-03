export interface Application {
  id: string;
  name: string;
  application_type: string;
  description: string | null;
  context: Record<string, unknown>;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface BackgroundProcessPin {
  schema_version: 'provider.background-process-pin.v1';
  consumer_exchange_id: string;
  source_namespace: 'tiangong_open_data';
  process_uuid: string;
  version: string;
  expected_process_content_hash: string;
  expected_process_snapshot_hash: string;
  quantitative_reference_exchange_internal_id: string;
  claim_role: 'partial_background_leaf';
}

export interface MappedBackgroundProcessPin {
  schema_version: 'provider.mapped-background-process-pin.v1';
  consumer_exchange_id: string; source_flow_namespace: string; source_flow_uuid: string; source_flow_version: string;
  target_flow_uuid: string; source_unit: string; target_unit: string; amount_factor: number;
  mapping_level: 'L1' | 'L2'; mapping_status: 'auto' | 'user_confirmed'; mapping_rule_id: string;
  mapping_package_id: string; mapping_package_version: string; mapping_package_hash: string;
  database_release: string; process_uuid: string; expected_process_content_hash: string; expected_vector_checksum: string;
  claim_role: 'partial_background_leaf';
}

export interface ProjectBackgroundPin {
  schema_version: 'provider.project-background-pin.v1'; consumer_exchange_id: string;
  project_id: string; version: number; expected_graph_hash: string;
  source_node_id: string; reference_port_id: string;
  provider_amount_per_consumer_unit: number;
  claim_role: 'user_declared_partial_background_leaf';
}

export interface ModelProcessingRulesRef {
  package_id: string; version: string; content_sha256: string;
}

export interface ProjectWorkspace {
  frozen_identity?: Record<string, unknown>;
  mapped_background_process_pins?: MappedBackgroundProcessPin[];
  project_background_pins?: ProjectBackgroundPin[];
  model_processing_rules_ref?: ModelProcessingRulesRef | null;
  application_id: string;
  revision_id: string;
  content_sha256: string;
  template_title: string | null;
  fields: Array<{ key: string; label: string; process: string; unit: string; value: number; process_id?: string; port_id?: string; group?: string; flow_type?: string; flow_uuid?: string; linked?: boolean; reference_product?: boolean }>;
  /** Read-only process topology of the selected revision: nodes are processes, edges are the
   * exchanges the graph actually declares (never inferred from array order). */
  process_graph?: { nodes: Array<{ id: string; name: string }>; edges: Array<{ source: string; target: string; label: string }> };
  inventory_editing?: boolean;
  background_ports?: Array<{exchange_id: string; process: string; label: string; unit: string; flow_uuid: string; version: string; source_namespace: string; exact_binding_supported: boolean}>;
  background_process_pins?: BackgroundProcessPin[];
  demand: Array<{ reference_flow_uuid: string; amount: number; unit: string; unit_group_uuid?: string; unit_group_version?: string }>;
  demand_mode?: 'explicit' | 'reference_output';
  source: string;
  saved: boolean;
  capabilities: string[];
  blocked_capabilities: Array<{ capability: string; reason?: string }>;
  /** Present only once the data version has mapped background providers: the pinned native climate
   * contract answers for one shared provider, so an ambiguous binding cannot produce the task. */
  native_climate?: { available: boolean; provider_count: number } | null;
  native_inventory?: { available: boolean; provider_count: number } | null;
  background_options: unknown[];
  background_note: string;
}

export interface SystemModel {
  id: string;
  application_id: string;
  name: string;
  provider: string;
  provider_base_url: string;
  upstream_project_id: string;
  upstream_version: number;
  graph_sha256: string;
  upstream_receipt: Record<string, unknown>;
  created_at: string;
}

export type ModelSourceType = 'nebula_project_version' | 'tidas_bundle' | 'nebula_native_bundle';

export interface ModelSource {
  id: string;
  application_id: string;
  system_model_id: string | null;
  name: string;
  source_type: ModelSourceType;
  provider: 'nebula_lca';
  provider_base_url: string;
  status: string;
  file_name: string | null;
  file_sha256: string | null;
  upstream_project_id: string | null;
  upstream_version: number | null;
  graph_sha256: string | null;
  import_receipt: Record<string, unknown>;
  candidate_versions: Array<{ project_id: string; version: number; graph_hash?: string | null; created_at?: string | null }>;
  external_dependencies: Array<Record<string, unknown>>;
  issues: Array<Record<string, unknown>>;
  content_sha256: string;
  created_at: string;
  attached_at: string | null;
}

export interface ModelSourcePreview {
  schema_version: 'nebula_one.model-source-preview.v1';
  source_type: Extract<ModelSourceType, 'tidas_bundle' | 'nebula_native_bundle'>;
  file_name: string;
  file_sha256: string;
  status: 'ready' | 'blocked';
  preview_sha256: string;
  summary: Record<string, unknown>;
  external_dependencies: Array<Record<string, unknown>>;
  issues: Array<Record<string, unknown>>;
}

export interface ModelSourceAttachResult {
  source: ModelSource;
  system_model: SystemModel;
  base_revision: SystemRevision;
}

export interface SystemRevision {
  id: string;
  system_model_id: string;
  parent_revision_id: string | null;
  revision_number: number;
  label: string | null;
  revision_kind: string;
  graph_sha256: string;
  content_sha256: string;
  status: string;
  created_at: string;
  published_at: string | null;
}

export interface Scenario {
  id: string;
  application_id: string;
  name: string;
  base_revision_id: string;
  system_revision_id: string;
  inventory_snapshot_id: string | null;
  parameter_set_id: string | null;
  status: string;
  content_sha256: string | null;
  created_at: string;
  frozen_at: string | null;
}

export interface Comparison {
  id: string;
  application_id: string;
  name: string;
  scenario_ids: string[];
  comparability: { compatible?: boolean; reasons?: unknown[] } & Record<string, unknown>;
  content_sha256: string;
  created_at: string;
}

export interface DemandItem {
  reference_flow_uuid: string;
  amount: number;
  unit: string;
  unit_group_uuid?: string;
  unit_group_version?: string;
}

export interface SolveAndFreezeRequest {
  analysis_task?: 'mfa' | 'pcf' | 'cbam' | 'organization';
  mapped_background_process_pins?: MappedBackgroundProcessPin[];
  background_process_pins?: BackgroundProcessPin[];
  project_background_pins?: ProjectBackgroundPin[];
  demand: DemandItem[];
  idempotency_key?: string;
  scenario_id?: string;
  lcia_methods?: string[];
  native_background_climate?: boolean;
  native_background_inventory?: boolean;
  climate_default?: boolean;
}

export interface ClimateMethodResolution {
  schema_version: 'nebula_one.climate-method-resolution.v1';
  status: 'ready' | 'unavailable';
  reference: string | null;
  content_sha256: string | null;
  reason_code: string | null;
  method: { lcia_method: string; total_indicator_key: string; result_unit: string;
    source_contract: string | null; source_method: { id: string; version: string; content_sha256: string } | null } | null;
}

/** The exact EF v3.1 climate-total pin Nebula LCA was asked to answer against. */
export interface NativeClimateRequestPin {
  schema_version: 'provider.native-background-climate-total.request.v1';
  database_release: string;
  method_package_id: string;
  method_package_version: string;
  method_package_sha256: string;
  runtime_manifest_sha256: string;
  flow_snapshot_hash: string;
  reference_dependency_snapshot_hash: string;
}

export interface NativeClimateTerm {
  exchange_id: string;
  process_uuid: string;
  source_namespace: string;
  flow_uuid: string;
  flow_version: string;
  direction: 'input' | 'output';
  compartment: string;
  subcompartment: string | null;
  amount: number;
  amount_unit: string;
  cf_presence: 'explicit_nonzero' | 'explicit_zero' | 'no_cf';
  cf_value: number | null;
  cf_source: string;
  cf_method: string;
  cf_database_release: string;
  method_package_sha256: string;
  contribution_value: number | null;
}

/** One domain's answer. `coverage` only lists the states the solve actually met. */
export interface NativeClimateDomain {
  source_namespace: string;
  contribution_value: number;
  indicator_unit: string;
  coverage: Record<string, number>;
  negative_cf_exchange_count: number;
  terms: NativeClimateTerm[];
}

export interface NativeClimateAnswer {
  schema_version: 'provider.native-background-climate-total.response.v1';
  method_package_id: string;
  method_package_version: string;
  method_package_sha256: string;
  runtime_manifest_sha256: string;
  indicator: { method: string; category: string; name: string; unit: string };
  merge_status: 'merged' | 'split_diagnostic';
  merge_blockers: Array<Record<string, unknown>>;
  unified_climate_total: number | null;
  domains: Record<string, NativeClimateDomain>;
  provider_system_model_evidence: string;
  carbon_storage_permanence: string;
  claim_limit: string;
}

export interface NativeClimateEnvelope {
  schema_version: 'nebula_one.native-background-climate.v1';
  source_contract: { repository: string; commit: string; document: string; document_sha256: string };
  request: NativeClimateRequestPin;
  response: NativeClimateAnswer;
}

export interface SolvedSystemSnapshot {
  id: string;
  application_id: string;
  system_revision_id: string;
  inventory_snapshot_id: string | null;
  parameter_set_id: string | null;
  solve_hash: string;
  provider: string;
  provider_receipt: Record<string, unknown>;
  functional_unit: unknown;
  database_release: string;
  solver_version: string;
  activity_vector: Array<Record<string, unknown>>;
  scaled_technosphere_exchanges: Array<Record<string, unknown>>;
  scaled_elementary_exchanges: Array<Record<string, unknown>>;
  internal_transfers: Array<Record<string, unknown>>;
  boundary_flows: Array<Record<string, unknown>>;
  process_balance_residuals: Array<Record<string, unknown>>;
  contribution_graph: Record<string, unknown>;
  lcia_results: Record<string, unknown>;
  /** Set only for a snapshot frozen through the pinned native climate contract. */
  native_background_climate?: NativeClimateEnvelope | null;
  content_sha256: string;
  created_at: string;
}

export interface MethodPackage {
  id: string;
  package_id: string;
  version: string;
  package_kind: string;
  jurisdiction: string | null;
  valid_from: string | null;
  valid_to: string | null;
  manifest: Record<string, unknown>;
  content_sha256: string;
  status: string;
  created_at: string;
}

export interface OrganizationLifecycleDisplay {
  schema_version: 'nebula_one.organization-lifecycle-display.v1';
  version: string;
  language: 'zh' | 'en';
  method_package: { package_id: string; version: string; content_sha256: string };
  projection_sha256: string;
  labels: {
    input_basis: Record<string, string>;
    group_status: Record<string, string>;
    categories: Record<string, string>;
    exchanges: Record<string, string>;
  };
}

export interface ProductCarbonFootprint {
  schema_version: 'nebula_one.pcf.product.v1';
  capability_key: 'pcf.product.v1';
  method_package: {
    reference: string;
    content_sha256: string;
    lcia_method: string;
    total_indicator_key: string;
  };
  source_snapshot: { id: string; content_sha256: string };
  functional_unit: {
    reference_flow_uuid?: string;
    amount: number;
    unit: string;
    unit_group_uuid?: string;
    unit_group_version?: string;
  };
  total_footprint: { value: number; unit: string; indicator_key: string };
  component_results: Array<{ indicator_key: string; value: number; unit: string }>;
  contribution_analysis: {
    status: 'available' | 'unavailable';
    coverage: 'exact_exchange_contributions' | 'total_only';
    reason: string | null;
    indicator_receipt: null | {
      content_hash: string;
      contribution_receipts_hash: string;
      solve_hash: string;
      provider_commit: string | null;
      runtime_assets_hash: string;
      term_count: number;
    };
    hotspots: Array<{
      rank: number;
      process_id: string;
      exchange_id: string;
      flow_identity: { source_namespace: string; flow_uuid: string; version: string };
      amount: number;
      amount_unit: string;
      contribution_value: number;
      contribution_unit: string;
      share_of_total: number | null;
      cf_hash: string;
    }>;
  };
  boundary_claim: {
    claim_scope: string;
    coverage: string;
    complete_product_declaration: boolean;
  };
  data_quality: {
    database_release?: string;
    solver_version?: string;
    elementary_flow_receipt_count?: number;
    background_process_receipt_count?: number;
  } & Record<string, unknown>;
  audit: {
    status: string;
    checks?: Record<string, boolean>;
    limitations?: string[];
  } & Record<string, unknown>;
  provenance: Record<string, unknown>;
  content_sha256: string;
}

export interface OrganizationSupplierActivity {
  activity_id: string;
  category: string;
  consumer_exchange_id: string;
  quantity: number;
  activity_unit: string;
  factor_value: number;
  factor_unit: string;
  factor_version: string;
  factor_source: string;
  factor_boundary: string;
  evidence_sha256: string;
  evidence_role: 'supplier_specific' | 'demonstration_proxy';
  outside_model: boolean;
}

export interface OrganizationPeriodRequest {
  solved_snapshot_id: string;
  method_package_ref: string;
  reporting_period_id: string;
  facility: string;
  controlled_process_ids: string[];
  period_product_output: number;
  scope3_activities: OrganizationSupplierActivity[];
  category_statuses: Record<string, 'missing_activity' | 'not_applicable' | 'excluded_by_boundary'>;
}

export interface OrganizationPeriodResult {
  id: string;
  application_id: string;
  system_revision_id: string;
  solved_snapshot_id: string;
  period_id: string;
  request_sha256: string;
  result: {
    reporting_period: { name: string; start_date: string; end_date: string };
    organizational_boundary: { facility: string; controlled_process_ids: string[] };
    activity_basis: { baseline_output: number; period_output: number; output_unit: string; scale_factor: number };
    method_package: { reference: string; content_sha256: string };
    scopes: {
      scope_1: { value: number; unit: string; status: string };
      scope_2: { value: number | null; unit: string; status: string };
      scope_3: { value: number | null; unit: string; status: string; categories: Array<{ category: string; name: string; status: string; value: number | null; unit: string; activities: OrganizationSupplierActivity[] }> };
    };
    unclassified_background_reference?: { value: number; unit: string; status: string };
    combined_total: number | null;
    coverage: { status: string; missing_activity_categories: string[]; demonstration_proxy_activity_ids: string[]; missing_scope2_generation_evidence?: boolean; not_a_complete_corporate_inventory: boolean };
    content_sha256: string;
  };
  content_sha256: string;
  created_at: string;
}

export interface OrganizationLifecycleRequest {
  solved_snapshot_id: string;
  method_package_ref: string;
  reporting_period_id: string;
  facility: string;
  controlled_process_ids: string[];
  input_basis: 'per_unit_product' | 'annual_total' | 'current_model_total';
  period_product_output: number;
  other_activities: OrganizationLifecycleActivity[];
}

export interface OrganizationLifecycleActivity extends OrganizationSupplierActivity {
  factor_package_ref?: string | null;
  factor_method_id?: string | null;
  factor_method_version?: string | null;
  factor_method_sha256?: string | null;
  factor_reference_product?: string | null;
}

export interface OrganizationLifecycleResult {
  id: string;
  created_at: string;
  application_id: string;
  solved_snapshot_id: string;
  content_sha256: string;
  result: {
    climate_source?: { unassigned_suppliers?: Array<{ consumer_exchange_id: string; contribution_value: number | null; project_id: string; version: number }>; uncharacterized_terms?: Array<{process_uuid: string; exchange_id: string; flow_uuid: string; flow_version: string | null; amount: number; amount_unit: string; status: string; numeric_contribution: null}> };
    reporting_period: { name: string; start_date?: string; end_date?: string };
    facility: string;
    activity_basis: { mode: string; baseline_output: number; period_output: number; unit: string; scale_factor: number };
    method_package: { reference: string; content_sha256: string };
    groups: {
      on_site_direct: { value: number; unit: string; status: string };
      purchased_energy_lifecycle: { value: number; unit: string; status: string; exchange_ids: string[] };
      other_value_chain: { value: number | null; unit: string; status: string; categories: Array<{ category: string; name: string; value: number | null; status: string; boundary_status?: string; activities: OrganizationLifecycleActivity[]; proxy_reference_value?: number | null; proxy_activities?: OrganizationLifecycleActivity[]; supply_receipts?: Array<{consumer_exchange_id: string; contribution_value: number | null; project_id: string; version: number; source_graph_hash: string; status: string}>; missing_exchange_ids?: string[] }> };
    };
    combined_total: number | null;
    coverage: { status: string; missing_categories: string[]; not_in_boundary_categories?: string[]; demonstration_proxy_activity_ids: string[] };
    source_snapshot: { id: string; content_sha256: string };
  };
}

export interface CbamTrialRequest {
  method_package_ref: string;
  reporting_period_id: string;
  /** cbam.trial.v2 computes against a named frozen boundary; a v1 package accepts none. */
  boundary_definition_id?: string;
}

export interface CbamPartialReviewRequest {
  method_package_ref: string;
  reporting_period_id: string;
  boundary_definition_id: string;
  eligible_electricity_factor_ref?: string;
  condition_declarations?: Record<string, { status: string; evidence_sha256: string }>;
}

export interface CbamPartialReviewResult {
  schema_version: 'nebula_one.cbam.partial-review.v1' | 'nebula_one.cbam.partial-review.v2';
  method_package: { reference: string; content_sha256: string };
  source_snapshot: { id: string; content_sha256: string; system_revision_id: string };
  source_direct_result_sha256: string;
  components: {
    direct: { value: string; unit: string; status: string; exchanges: Array<{ exchange_id: string; amount: string | null; unit: string; clause: string | null }> };
    sinter_precursor_indirect: {
      electricity_activity: { value: string; unit: string; source_value: string; source_unit: string; consumer_exchange_id: string };
      eligible_factor: null | { value: string; unit: string; package_reference: string; package_content_sha256: string };
      value: string | null;
      unit: string;
      status: string;
    };
    user_supply_electricity_trial?: {
      value: string; unit: string; source_amount: string; source_unit: string;
      source_project_id: string; source_version: number; source_graph_hash: string;
      exchange_id: string; status: 'user_declared_trial_not_eligible_cbam_factor';
    };
  };
  specific_embedded_emissions: { value: string | null; unit: string; status: string; partial_direct_value: string };
  coverage: { status: string; missing: string[]; default_values: string; source_streams?: { item: string; state: string; effect?: string }[] };
  content_sha256: string;
}

export interface CbamComplexTrialRequest extends CbamTrialRequest {
  precursors: Array<{
    solved_snapshot_id: string;
    method_package_ref: string;
  }>;
}

/** v2 echoes the boundary ledger the trial computed against: every port classified, plus open limits. */
export interface CbamBoundaryCoverage {
  schema: 'nebula_one.cbam.boundary-coverage.v1';
  universe_sources: { boundary_definition_id: string; boundary_name: string; boundary_content_sha256: string } & Record<string, unknown>;
  totals: { ports: number; counted_kg_co2e: string } & Record<string, unknown>;
  open_items: Array<{ clause: string; item: string; effect: string; gap_ref?: string; state: string }>;
  refusals: unknown[];
  exchanges?: Array<{
    exchange_id: string;
    process_uuid: string;
    disposition: string;
    clause: string | null;
    basis: string | null;
    amount: string | null;
    unit: string;
  }>;
}

export interface CbamTrialResult {
  schema_version: 'nebula_one.cbam.trial.v1' | 'nebula_one.cbam.trial.v2';
  capability_key: 'cbam.trial.v1' | 'cbam.trial.v2';
  method_package: {
    ref: string;
    content_sha256: string;
    jurisdiction: string;
    rule_source_sha256: string;
  };
  source_snapshot: { id: string; content_sha256: string; application_id: string };
  reporting_period: { id: string; key: string; name: string; start_date: string; end_date: string; resolution: string };
  goods: { cn_code: string; aggregated_goods_category: string; production_process_uuid: string };
  activity_level: { value: string; unit: string; source_value: string; source_unit: string };
  attributed_emissions: {
    direct: { value: string; unit: string; source_value: string; source_unit: string };
    indirect: null | {
      state: string;
      value: string | null;
      unit: string | null;
      activity: { value: string; unit: string } | null;
      missing_factor_package: string | null;
    };
    precursors: unknown[];
  };
  specific_embedded_emissions: { value: string | null; unit: string; formula: string; partial_result?: boolean; partial_value?: string };
  nitrogen_basis?: null | { applies: boolean; label: string; value: string; unit: string };
  coverage?: CbamBoundaryCoverage;
  status: 'trial_passed' | 'partial_calculated';
  audit: Record<string, unknown>;
  claim_boundary: Record<string, boolean>;
  content_sha256: string;
}

export interface CbamComplexTrialResult {
  schema_version: 'nebula_one.cbam.complex-trial.v1';
  capability_key: 'cbam.complex-trial.v1';
  method_package: CbamTrialResult['method_package'];
  source_snapshot: CbamTrialResult['source_snapshot'];
  reporting_period: CbamTrialResult['reporting_period'];
  goods: CbamTrialResult['goods'];
  activity_level: CbamTrialResult['activity_level'];
  attributed_emissions: {
    final_process_direct: { value: string; unit: string; source_value: string; source_unit: string };
    precursor_embedded_direct: { value: string; unit: string };
    total_direct_component: { value: string; unit: string };
    indirect: null;
  };
  precursors: Array<{
    exchange_id: string;
    method_package_ref: string;
    mass: { value: string; unit: string; source_value: string; source_unit: string };
    specific_mass_consumption: { value: string; unit: string };
    specific_embedded_emissions: { value: string; unit: string };
    embedded_emissions: { value: string; unit: string };
    result_content_sha256: string;
  }>;
  specific_embedded_emissions: { value: string; unit: string; component: 'direct'; formula: string; regulatory_equation: string };
  status: 'trial_passed';
  audit: Record<string, unknown>;
  claim_boundary: Record<string, boolean>;
  content_sha256: string;
}

export interface EnergyCarrierBasis {
  energy_convention: 'declared_energy' | 'lower_heating_value' | 'higher_heating_value';
  material_condition: 'not_applicable' | 'as_received' | 'dry' | 'dry_ash_free';
}

export interface EnergyCarrierSeries {
  series_id: string;
  unit_symbol: 'MJ';
  unit_identity_sha256: string;
  basis: EnergyCarrierBasis;
  entries: Array<Record<string, unknown>>;
  total_amount: string;
  content_sha256: string;
}

export interface EnergyCarrierResult {
  id: string;
  application_id: string;
  solved_snapshot_id: string;
  request_sha256: string;
  result: {
    schema_version: 'nebula.energy.carrier.solved.v1';
    solved_snapshot_ref: { id: string; content_sha256: string; solve_hash: string };
    series: EnergyCarrierSeries[];
    issues: Array<{ code: string; severity: 'warning'; message: string }>;
    status: 'passed' | 'passed_with_warnings';
    content_sha256: string;
  };
  content_sha256: string;
  created_at: string;
}

export interface ReportingPeriod {
  id: string;
  application_id: string;
  key: string;
  name: string;
  start_date: string;
  end_date: string;
  resolution: string;
  created_at: string;
}

export interface InventorySnapshot {
  id: string;
  application_id: string;
  name: string;
  system_revision_id: string;
  boundary_id: string;
  period_id: string;
  status: 'draft' | 'frozen';
  content_sha256: string | null;
  created_at: string;
  frozen_at: string | null;
}

export interface InventoryDataPoint {
  id: string;
  inventory_snapshot_id: string;
  entity_id: string | null;
  process_id: string | null;
  flow_uuid: string | null;
  metric_key: string;
  quantity: number;
  unit: string;
  source_type: string;
  evidence_id: string;
  mapping_target: Record<string, unknown>;
  quality_status: string;
  review_status: string;
  uncertainty: Record<string, unknown>;
  created_at: string;
}

export interface PeriodEnergyTrendRequest {
  observations: Array<{ period_id: string; energy_result_id: string }>;
  baseline_period_id?: string;
}

export interface PeriodEnergyTrendResult {
  schema_version: 'nebula_one.period-energy-trend.v1';
  capability_key: 'energy.period-trend.v1';
  application_id: string;
  system_model_id: string;
  value_semantics: {
    kind: 'functional_unit_intensity';
    functional_unit: unknown;
    functional_unit_sha256: string;
    aggregation: 'none';
  };
  baseline_period_id: string;
  observations: Array<{
    period: ReportingPeriod & { content_sha256: string };
    source: Record<string, string>;
    energy_result_content_sha256: string;
  }>;
  metrics: Array<{
    metric_key: string;
    label: string;
    unit_symbol: 'MJ';
    basis: EnergyCarrierBasis;
    values: Record<string, string>;
    deltas_from_baseline: Record<string, { absolute: string; relative: string | null }>;
    deltas_from_previous: Record<string, { absolute: string; relative: string | null } | null>;
    summary: { minimum: string; maximum: string; arithmetic_mean: string };
    content_sha256: string;
  }>;
  issues: Array<{ code: string; severity: 'warning'; message: string; period_ids: string[] }>;
  status: 'passed' | 'passed_with_warnings';
  audit: {
    status: string;
    checks: Record<string, boolean>;
    counts: Record<string, number>;
    limitations: string[];
  };
  content_sha256: string;
}

export interface PeriodEnergyTotalRequest {
  observations: Array<{
    period_id: string;
    energy_result_id: string;
    inventory_snapshot_id: string;
    production_data_point_id: string;
  }>;
  baseline_period_id?: string;
}

export interface PeriodEnergyTotalResult {
  schema_version: 'nebula_one.period-energy-total.v1';
  capability_key: 'energy.period-total.v1';
  application_id: string;
  system_model_id: string;
  source_intensity_trend: { content_sha256: string; baseline_period_id: string };
  value_semantics: {
    kind: 'evidence_scaled_period_total';
    formula: string;
    aggregation: 'sum_of_non_overlapping_periods';
    functional_output_unit: string;
  };
  baseline_period_id: string;
  observations: PeriodEnergyTrendResult['observations'];
  activities: Array<{
    period_id: string;
    inventory_snapshot: Record<string, unknown>;
    data_point: InventoryDataPoint & { content_sha256: string };
    evidence: Record<string, unknown>;
    functional_output: Record<string, unknown>;
    scale_factor: string;
  }>;
  metrics: Array<{
    metric_key: string;
    label: string;
    unit_symbol: string;
    unit_identity_sha256: string;
    basis: EnergyCarrierBasis;
    intensity_values: Record<string, string>;
    period_total_values: Record<string, string>;
    deltas_from_baseline: Record<string, { absolute: string; relative: string | null }>;
    deltas_from_previous: Record<string, { absolute: string; relative: string | null } | null>;
    covered_period_total: string;
    content_sha256: string;
  }>;
  issues: Array<{ code: string; severity: 'warning'; message: string; period_ids: string[] }>;
  status: 'passed' | 'passed_with_warnings';
  audit: PeriodEnergyTrendResult['audit'];
  content_sha256: string;
}

export interface CarbonManagementResult {
  schema_version: 'nebula_one.carbon.management.v1';
  capability_key: 'carbon.management.v1';
  method_package: { reference: string; content_sha256: string };
  source_snapshot: { id: string; content_sha256: string };
  reporting_period: { id: string; version: string; content_sha256: string };
  energy_result: {
    id: string;
    content_sha256: string;
    series: Array<{
      series_id: string;
      basis: EnergyCarrierBasis;
      unit: string;
      unit_identity_sha256: string;
      categories: Array<{ category: string; amount: string }>;
      entries: Array<Record<string, unknown>>;
      total_amount: string;
    }>;
  };
  direct_emission_inventory: Array<{
    exchange_id: string;
    process_id?: string;
    flow_identity: { source_namespace: string; flow_uuid: string; version: string };
    category: string;
    amount: number;
    unit: string;
    direction: string;
    factor_hash?: string;
  }>;
  climate_change_total: { indicator_key: string; value: number; unit: string } | null;
  carbon_attribution: {
    coverage: string;
    categories: Array<{ category: string; value: number | null; unit: string | null; reason?: string }>;
    scope_1_2_3_statement: boolean;
  };
  audit: {
    status: string;
    checks: Record<string, boolean>;
    issues: Array<{ code: string; message: string }>;
    limitations: string[];
  };
  content_sha256: string;
}

export interface ProvinceElectricityRequest {
  method_package_ref: string;
  period_energy_total: PeriodEnergyTotalRequest;
}

export interface OrganizationGhgInventoryRequest {
  method_package_ref: string;
  carbon_method_package_ref: string;
  province_electricity: ProvinceElectricityRequest;
  scope_2_scenario_id: string;
}

export interface OrganizationGhgInventoryResult {
  schema_version: 'nebula_one.organization-ghg-inventory-trial.v1';
  capability_key: 'ghg.inventory.trial.v1';
  application_id: string;
  method_package: { ref: string; content_sha256: string };
  source_period_energy_total: { content_sha256: string; period_ids: string[] };
  reporting_period: {
    id: string;
    version: string;
    content_sha256: string;
    covered_start_date: string;
    covered_end_date: string;
  };
  inventory_boundary: {
    status: string;
    organizational_boundary_complete: boolean;
    combined_total_available: boolean;
    reason: string;
  };
  scopes: Array<{
    scope: 'scope_1' | 'scope_2' | 'scope_3';
    status: string;
    value: string | null;
    unit: string | null;
    label: string;
    accounting_method?: string;
    reason?: string;
    source?: Record<string, unknown>;
  }>;
  combined_total: null;
  issues: Array<Record<string, unknown> & { code?: string; message?: string }>;
  status: 'passed_with_warnings';
  audit: {
    status: string;
    checks: Record<string, boolean>;
    limitations: string[];
  };
  content_sha256: string;
}

export interface SystemBinding {
  id: string;
  application_id: string;
  binding_id: string;
  role: string;
  system_model_id: string;
  system_revision_id: string | null;
  solved_snapshot_id: string | null;
  study_frame_id: string;
  reporting_period_id: string;
  organizational_boundary_id: string;
  demand: Array<Record<string, unknown>>;
  capabilities: string[];
  dependencies: string[];
  content_sha256: string;
  status: 'draft' | 'active' | 'retired' | string;
  created_at: string;
  updated_at: string;
}

export interface OrganizationGhgInventoryV1Request {
  method_package_ref: string;
  pcf_method_package_ref: string;
  binding_ids: string[];
}

export interface OrganizationGhgInventoryV1Result {
  schema_version: 'nebula_one.organization-ghg-inventory.v1';
  capability_key: 'organization.ghg-inventory.v1';
  application_id: string;
  reporting_period_id: string;
  organizational_boundary_id: string;
  method_package: { reference: string; content_sha256: string };
  comparability: { lcia_method: string; unit: string; database_release: string };
  scopes: Array<{
    scope: 'scope_1' | 'scope_2' | 'scope_3';
    total: { value: number; unit: string };
    categories: Array<{
      category: string;
      total: { value: number; unit: string };
      sources: Array<Record<string, unknown>>;
    }>;
  }>;
  total: { value: number; unit: string };
  audit: { status: string; source_binding_count: number; checks: Record<string, boolean> };
  content_sha256: string;
}

export interface SolvedMfaResult {
  schema_version: 'nebula_one.mfa.solved.v1';
  solved_snapshot_id: string;
  solve_hash: string;
  series: Array<{
    series_id: string;
    unit_group: string;
    unit_group_uuid?: string;
    unit_group_label: string;
    is_mass?: boolean;
    conservation?: {
      status: string;
      error_count: number;
      warning_count: number;
      open_boundary_count: number;
    };
    unit: string;
    nodes: Array<Record<string, unknown>>;
    links: Array<Record<string, unknown>>;
    totals: { internal: number; boundary_input: number; boundary_output: number };
  }>;
  audit: Record<string, unknown>;
}

export interface BoundaryDefinition {
  id: string;
  application_id: string;
  name: string;
  boundary_type: string;
  included_entity_ids: string[];
  included_process_ids: string[];
  included_flow_rules: Array<Record<string, unknown>>;
  excluded_items: Array<Record<string, unknown>>;
  consolidation_policy: Record<string, unknown>;
  period_id: string | null;
  geographic_scope: Record<string, unknown>;
  method_package_ref: string | null;
  content_sha256: string | null;
  status: string;
  created_at: string;
  frozen_at: string | null;
}

export interface SpatialAggregateResult {
  schema_version: 'nebula_one.spatial.aggregate.v1';
  capability_key: 'spatial.aggregate.v1';
  source_snapshot: {
    id: string;
    content_sha256: string;
    solve_hash: string;
    system_revision_id: string;
  };
  park: {
    entity_id: string;
    external_id: string | null;
    name: string;
    spatial_unit: Record<string, unknown> & { content_sha256: string };
  };
  facilities: Array<{
    entity_id: string;
    external_id: string | null;
    name: string;
    spatial_unit: Record<string, unknown> & { content_sha256: string };
    process_uuids: string[];
  }>;
  series: Array<{
    series_id: string;
    unit_group: string;
    unit_group_label: string;
    unit: string;
    nodes: Array<Record<string, unknown>>;
    links: Array<Record<string, unknown>>;
    totals: {
      external_input: number;
      external_output: number;
      inter_facility: number;
      eliminated_intra_facility: number;
    };
    facility_metrics: Array<{
      entity_id: string;
      external_input: number;
      external_output: number;
      inter_facility_input: number;
      inter_facility_output: number;
    }>;
    external_flow_metrics: Array<Record<string, unknown>>;
  }>;
  audit: {
    status: string;
    checks: Record<string, boolean>;
    counts: Record<string, number>;
    issues: Array<Record<string, unknown>>;
    provenance: Record<string, unknown>;
  };
  content_sha256: string;
}

export interface SpatialEnergyResult {
  schema_version: 'nebula_one.spatial.energy.v1';
  capability_key: 'spatial.energy.v1';
  source_snapshot: { id: string; content_sha256: string; solve_hash: string; system_revision_id: string };
  source_energy_result: { id: string; record_content_sha256: string; result_content_sha256: string };
  source_spatial_result: { content_sha256: string; boundary_id: string };
  park: SpatialAggregateResult['park'];
  facilities: SpatialAggregateResult['facilities'];
  series: Array<{
    series_id: string;
    unit_group: string;
    unit_group_label: string;
    unit: string;
    basis: EnergyCarrierBasis;
    nodes: Array<Record<string, unknown>>;
    links: Array<Record<string, unknown>>;
    total_amount: string;
    facility_metrics: Array<{ entity_id: string; amount: string; share: string | null }>;
    carrier_metrics: Array<{ flow_uuid: string; flow_name: string; amount: string }>;
  }>;
  audit: {
    status: string;
    checks: Record<string, boolean>;
    counts: Record<string, number>;
    issues: Array<Record<string, unknown>>;
    limitations: string[];
    provenance: Record<string, unknown>;
  };
  content_sha256: string;
}

export interface SpatialDistributionResult {
  schema_version: 'nebula_one.spatial.distribution.v1';
  capability_key: 'spatial.distribution.v1';
  source_snapshot: { id: string; system_revision_id: string; solve_hash: string; content_sha256: string };
  method_package: { ref: string; content_sha256: string };
  source_flow: {
    name: string;
    selector: Record<string, string>;
    amount: number;
    unit: string;
    provider_flow_receipt: Record<string, unknown> | null;
  };
  destination: {
    spatial_unit: Record<string, unknown> & { content_sha256: string };
    longitude: number;
    latitude: number;
  };
  baseline_scenario_id: string;
  scenarios: Array<{
    scenario_id: string;
    name: string;
    description: string | null;
    content_sha256: string;
    regions: Array<{
      region: Record<string, unknown> & { region_id: string; name: string; content_sha256: string };
      share: number;
      amount: number;
      baseline_amount: number;
      amount_delta_from_baseline: number;
      relative_delta_from_baseline: number | null;
    }>;
    total_allocated: number;
    allocation_residual: number;
  }>;
  audit: {
    status: string;
    checks: Record<string, boolean>;
    counts: Record<string, number>;
    limitations: string[];
  };
  content_sha256: string;
}

export interface ComparisonExecuteRequest {
  baseline_scenario_id: string;
  demand: DemandItem[];
  lcia_methods?: string[];
}

export interface ComparisonMetric {
  metric_key: string;
  metric_kind?: 'boundary_flow' | 'lcia_indicator';
  subject_id?: string | null;
  subject_name?: string | null;
  flow_uuid?: string | null;
  flow_name?: string | null;
  indicator_key?: string | null;
  method?: string | null;
  database_release?: string | null;
  indicator_metadata_hash?: string | null;
  direction?: 'input' | 'output' | null;
  exchange_type?: string | null;
  unit: string;
  unit_group: string;
  unit_group_label?: string | null;
  series_id: string;
  baseline_value: number;
  scenario_values: Record<string, number>;
  deltas: Record<string, { absolute: number; relative: number | null }>;
}

export interface ScenarioResult {
  scenario_id: string;
  scenario_name: string;
  scenario_hash: string;
  system_revision_id: string;
  solved_snapshot_id: string;
  solved_snapshot_hash: string;
  solve_hash: string;
  provider_receipt: Record<string, unknown>;
  lcia_results?: Record<string, unknown>;
  elementary_flow_receipts?: Record<string, unknown>[];
  mfa_audit: Record<string, unknown> & { status?: string };
  mfa_series?: Array<{
    series_id: string;
    unit_group?: string;
    unit_group_label?: string;
    unit?: string;
  }>;
  sankey_url: string;
}

export interface ComparisonRun {
  id: string;
  application_id: string;
  comparison_id: string;
  baseline_scenario_id: string;
  status: 'running' | 'succeeded' | 'failed' | string;
  request: ComparisonExecuteRequest;
  scenario_results: ScenarioResult[];
  metrics: ComparisonMetric[];
  audit: Record<string, unknown> & { status?: string; issues?: unknown[]; provenance?: Record<string, unknown> };
  error: Record<string, unknown> & { code?: string; message?: string };
  content_sha256: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface PeriodEnergyComparisonResult {
  schema_version: 'nebula_one.period-energy-scenario-comparison.v1';
  capability_key: 'energy.scenario-comparison.v1';
  reporting_period: { id: string; version: string; content_sha256: string };
  source_comparison_run: { id: string; content_sha256: string };
  comparison: {
    schema_version: 'nebula.energy-scenario-comparison.v1';
    baseline_scenario_id: string;
    base_revision_id: string;
    scenarios: Array<{
      scenario_id: string;
      scenario_name: string;
      system_revision_id: string;
      energy_result_content_sha256: string;
    }>;
    metrics: Array<{
      metric_key: string;
      label: string;
      unit_symbol: 'MJ';
      values: Record<string, string>;
      deltas: Record<string, { absolute: string; relative: string | null }>;
      content_sha256: string;
    }>;
    issues: Array<{ code: string; message: string; scenario_ids: string[] }>;
    status: 'passed' | 'passed_with_warnings';
    content_sha256: string;
  };
  audit: {
    status: string;
    checks: Record<string, boolean>;
    counts: Record<string, number>;
    issues: Array<Record<string, unknown>>;
    limitations: string[];
  };
  content_sha256: string;
}

export interface ApiProblem {
  code?: string;
  message?: string;
  details?: Record<string, unknown>;
  detail?: string | { code?: string; message?: string; details?: Record<string, unknown> };
  error?: { code?: string; message?: string; details?: Record<string, unknown> };
}

export interface CasePackApplication {
  editable_parameter_count?: number;
  id: string;
  version: string;
  title: string;
  case_type: string;
  lifecycle_status: string;
  study_frame_id: string;
  study_frame_title: string;
  study_frame_status: string;
  demand_type: string;
  demand: Array<Record<string, unknown> & { amount?: number; unit?: string; reference_flow_uuid?: string }>;
  capabilities: string[];
  blocked_capabilities: Array<{ capability: string; reason: string }>;
  method_packages: Array<{ path: string; package_id: string; version: string; content_sha256: string }>;
  resolved_case_sha256: string;
}

export interface CasePackCatalogItem {
  id: string;
  version: string;
  title: string;
  lifecycle_status: string;
  claim_level: string;
  provider: string | null;
  provider_contract: string | null;
  expected_graph_sha256: string | null;
  case_pack_sha256: string;
  license_audit_status: string;
  publication_gate: string;
  system_summary: {
    functional_unit: string;
    process_count: number;
    flow_count: number;
    elementary_flow_count: number;
    connection_count: number;
    processes: Array<{ id: string; name: string; node_kind: string }>;
    flow_sources: Array<{ source_namespace: string; flow_count: number }>;
  } | null;
  showcase?: {
    title: string;
    description: string;
    modules: Array<{
      key: string;
      title: string;
      description: string;
      application_case_id: string;
      capability_keys: string[];
    }>;
  } | null;
  applications: CasePackApplication[];
}

export interface CasePackCatalogResponse {
  schema_version: 'nebula.casepack-catalog.v1';
  items: CasePackCatalogItem[];
  issues: Array<{ code: string; message: string; source: string }>;
}

export interface SetupStatus {
  schema_version: 'nebula_one.setup-status.v1';
  status: 'ready' | 'degraded' | 'blocked';
  database: { status: 'ready'; backend: string; message: string };
  casepacks: { status: 'ready' | 'blocked'; count: number; issue_count: number; message: string };
  provider: {
    status: 'ready' | 'unavailable';
    base_url: string;
    message: string;
    remediation: string | null;
    error: Record<string, unknown> | null;
  };
}

export interface EngineStatus {
  provider: 'nebula_lca';
  base_url: string;
  status: 'ready' | 'degraded' | 'unavailable';
  contracts: Record<string, boolean>;
  error?: Record<string, unknown>;
}

export interface CasePackMaterializeRequest {
  project_name?: string;
  project_key?: string;
  expected_case_pack_sha256: string;
  expected_resolved_case_sha256: string;
}

export interface CasePackMaterializeResult {
  status: 'created' | 'existing';
  application: Application;
  system_model: SystemModel;
  base_revision: SystemRevision;
  demand: Array<Record<string, unknown>>;
  capabilities: string[];
  blocked_capabilities: Array<{ capability: string; reason: string }>;
  method_packages: Array<{ path: string; package_id: string; version: string; content_sha256: string }>;
  case_pack_sha256: string;
  resolved_case_sha256: string;
}

export interface CapabilityCatalogResponse {
  schema_version: 'nebula_one.capabilities.v1';
  engine: Record<string, unknown> | null;
  items: Array<{
    key: string;
    name: string;
    execution: string;
    basis: string;
    limits: string[];
    status: 'ready' | 'unavailable';
  }>;
}
export interface FrozenReportRow {
  exchange_id: string; process_id: string; process_name: string | null; flow_name: string | null;
  group: string; quantity: number | string | null; quantity_unit: string | null;
  contribution_value: number | string | null; contribution_unit: string | null;
  status: string; basis?: string | null;
}
export interface FrozenReport {
  schema_version: string; kind: 'cbam' | 'organization'; snapshot_id: string; revision_id: string;
  title: string; method_name: string | null; method_version: string; complete_total: number | string | null;
  summary: Array<{group: string; value: number | string | null; unit: string | null; status: string}>;
  details: FrozenReportRow[]; process_contributions: Array<{group: string; process_id: string; process_name: string | null; contribution_value: number | string; contribution_unit: string}>;
  gaps: Array<{name: string | null; status: string; basis?: string | null}>;
  outside_boundary: Array<{name: string; status: string}>; uncharacterized: FrozenReportRow[];
  status_labels: Record<string,string>; group_labels: Record<string,string>; sources: Record<string,unknown>;
  detail_status?: string;
}
