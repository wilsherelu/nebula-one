import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactElement } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '../api/client';
import { createAppQueryClient } from '../api/queryClient';
import { I18nProvider, LANGUAGE_STORAGE_KEY } from '../i18n';
import type { CarbonManagementResult, EnergyCarrierResult, MethodPackage, ProductCarbonFootprint, SolvedSystemSnapshot, SpatialAggregateResult, SpatialDistributionResult, SpatialEnergyResult } from '../api/types';
import { AnalysisResultsPage } from './AnalysisResultsPage';
vi.mock('echarts-for-react', () => ({ default: () => <div data-testid="contribution-chart" /> }));

function renderResults(element: ReactElement) {
  return render(<I18nProvider>{element}</I18nProvider>);
}

const snapshot: SolvedSystemSnapshot = {
  id: 'snapshot-1', application_id: 'app-1', system_revision_id: 'revision-3', inventory_snapshot_id: null, parameter_set_id: null,
  solve_hash: 'solve-hash-1', provider: 'nebula-lca', provider_receipt: { run_id: 'provider-run-1' }, functional_unit: { amount: 1, unit: 'kg' },
  database_release: 'EF3.1', solver_version: 'provider-v1', activity_vector: [{ process_id: 'p1' }, { process_id: 'p2' }],
  scaled_technosphere_exchanges: [], scaled_elementary_exchanges: [], internal_transfers: [{ exchange_id: 'e1' }],
  boundary_flows: [{ exchange_id: 'e2' }, { exchange_id: 'e3' }], process_balance_residuals: [], contribution_graph: {},
  lcia_results: { method: 'EF v3.1', indicator_results: [{ canonical_indicator_key: 'climate change', indicator_en: 'Climate change', value: 1.25, unit: 'kg CO2-Eq', method_en: 'EF v3.1' }] },
  content_sha256: 'content-hash-1', created_at: '2026-08-31T08:00:00Z',
};

const energyResult: EnergyCarrierResult = {
  id: 'energy-result-1', application_id: 'app-1', solved_snapshot_id: 'snapshot-1', request_sha256: 'energy-request-hash', content_sha256: 'energy-record-hash', created_at: snapshot.created_at,
  result: {
    schema_version: 'nebula.energy.carrier.solved.v1', solved_snapshot_ref: { id: 'snapshot-1', content_sha256: snapshot.content_sha256, solve_hash: snapshot.solve_hash }, status: 'passed_with_warnings', content_sha256: 'energy-domain-hash',
    issues: [{ code: 'PARTIAL_BACKGROUND_SCOPE', severity: 'warning', message: 'partial scope' }],
    series: [{ series_id: 'energy-series-1', unit_symbol: 'MJ', unit_identity_sha256: 'unit-hash', basis: { energy_convention: 'declared_energy', material_condition: 'not_applicable' }, entries: [{ exchange_id: 'electricity-in' }], total_amount: '3.2727272727272725', content_sha256: 'series-hash' }],
  },
};

const pcfResult: ProductCarbonFootprint = {
  schema_version: 'nebula_one.pcf.product.v1', capability_key: 'pcf.product.v1',
  method_package: { reference: 'pcf.bound@2.0.0', content_sha256: 'pcf-method-hash', lcia_method: 'Bound LCIA method', total_indicator_key: 'climate-total' },
  source_snapshot: { id: snapshot.id, content_sha256: snapshot.content_sha256 },
  functional_unit: { reference_flow_uuid: 'flow-final', amount: 1, unit: 'kg' },
  total_footprint: { value: 0.5258152018, unit: 'kg CO2-Eq', indicator_key: 'climate-total' },
  component_results: [{ indicator_key: 'climate-fossil', value: 0.5258152018, unit: 'kg CO2-Eq' }],
  contribution_analysis: {
    status: 'available', coverage: 'exact_exchange_contributions', reason: null,
    indicator_receipt: { content_hash: 'receipt-hash', contribution_receipts_hash: 'receipts-hash', solve_hash: snapshot.solve_hash, provider_commit: null, runtime_assets_hash: 'assets-hash', term_count: 1 },
    hotspots: [{ rank: 1, process_id: 'process-hotspot', exchange_id: 'exchange-hotspot', flow_identity: { source_namespace: 'ef31', flow_uuid: 'flow-co2', version: '1' }, amount: 0.5, amount_unit: 'kg', contribution_value: 0.5258152018, contribution_unit: 'kg CO2-Eq', share_of_total: 1, cf_hash: 'cf-hash' }],
  },
  boundary_claim: { claim_scope: 'foreground_boundary', coverage: 'foreground_with_pinned_background', complete_product_declaration: false },
  data_quality: { database_release: 'release-1', elementary_flow_receipt_count: 4 },
  audit: { status: 'passed', checks: { snapshot_content_pinned: true }, limitations: ['bounded result'] },
  provenance: { inventory_hash: 'inventory-hash' }, content_sha256: 'pcf-content-hash',
};

const carbonResult: CarbonManagementResult = {
  schema_version: 'nebula_one.carbon.management.v1', capability_key: 'carbon.management.v1',
  method_package: { reference: 'carbon.period@1.0.0', content_sha256: 'carbon-method-hash' },
  source_snapshot: { id: snapshot.id, content_sha256: snapshot.content_sha256 },
  reporting_period: { id: 'representative-year', version: '0.1.0', content_sha256: 'period-hash' },
  energy_result: { id: energyResult.id, content_sha256: energyResult.content_sha256, series: [{ series_id: 'energy-series-1', basis: { energy_convention: 'declared_energy', material_condition: 'not_applicable' }, unit: 'MJ', unit_identity_sha256: 'unit-hash', categories: [{ category: 'purchased_electricity', amount: '3.2727272727272725' }], entries: [], total_amount: '3.2727272727272725' }] },
  direct_emission_inventory: [{ exchange_id: 'process::co2-out', process_id: 'process', flow_identity: { source_namespace: 'tiangong_open_data', flow_uuid: 'co2', version: '03.00.004' }, category: 'direct_fossil_co2_to_air', amount: 0.00909, unit: 'kg', direction: 'output', factor_hash: 'factor-hash' }],
  climate_change_total: { indicator_key: 'climate change', value: 0.5258152018, unit: 'kg CO2-Eq' },
  carbon_attribution: { coverage: 'total_only', categories: [{ category: 'direct', value: null, unit: null, reason: 'provider contribution receipts unavailable' }], scope_1_2_3_statement: false },
  audit: { status: 'passed_with_warnings', checks: { reporting_period_pinned: true }, issues: [{ code: 'CARBON_ATTRIBUTION_UNAVAILABLE', message: 'no contribution receipts' }], limitations: ['demonstration only'] },
  content_sha256: 'carbon-content-hash',
};

const parkBoundary = {
  id: 'boundary-park-1', application_id: 'app-1', name: '参考石化园区边界', boundary_type: 'park', included_entity_ids: ['park', 'facility-a', 'facility-b'], included_process_ids: [], included_flow_rules: [], excluded_items: [],
  consolidation_policy: { intra_facility: 'eliminate', inter_facility: 'retain_as_internal', external_boundary: 'solved_snapshot_boundary_flows' }, period_id: 'period-1', geographic_scope: {}, method_package_ref: null, content_sha256: 'park-boundary-hash', status: 'frozen', created_at: snapshot.created_at, frozen_at: snapshot.created_at,
};

const spatialResult: SpatialAggregateResult = {
  schema_version: 'nebula_one.spatial.aggregate.v1', capability_key: 'spatial.aggregate.v1',
  source_snapshot: { id: snapshot.id, content_sha256: snapshot.content_sha256, solve_hash: snapshot.solve_hash, system_revision_id: snapshot.system_revision_id },
  park: { entity_id: 'park', external_id: 'reference-park', name: '参考石化园区', spatial_unit: { content_sha256: 'park-spatial-hash' } },
  facilities: [
    { entity_id: 'facility-a', external_id: 'facility-a', name: '一次加工设施', spatial_unit: { content_sha256: 'facility-a-hash' }, process_uuids: ['p1'] },
    { entity_id: 'facility-b', external_id: 'facility-b', name: '产品升级设施', spatial_unit: { content_sha256: 'facility-b-hash' }, process_uuids: ['p2'] },
  ],
  series: [{
    series_id: 'mass::kg', unit_group: 'mass', unit_group_label: 'Mass', unit: 'kg', nodes: [], links: [],
    totals: { external_input: 1100, external_output: 1050, inter_facility: 1000, eliminated_intra_facility: 80 },
    facility_metrics: [
      { entity_id: 'facility-a', external_input: 1100, external_output: 0, inter_facility_input: 0, inter_facility_output: 1000 },
      { entity_id: 'facility-b', external_input: 0, external_output: 1050, inter_facility_input: 1000, inter_facility_output: 0 },
    ], external_flow_metrics: [],
  }],
  audit: { status: 'passed', checks: { binding_coverage_complete: true }, counts: { facility_count: 2 }, issues: [], provenance: {} },
  content_sha256: 'spatial-result-hash',
};

const spatialEnergyResult: SpatialEnergyResult = {
  schema_version: 'nebula_one.spatial.energy.v1', capability_key: 'spatial.energy.v1',
  source_snapshot: spatialResult.source_snapshot,
  source_energy_result: { id: energyResult.id, record_content_sha256: energyResult.content_sha256, result_content_sha256: energyResult.result.content_sha256 },
  source_spatial_result: { content_sha256: spatialResult.content_sha256, boundary_id: parkBoundary.id },
  park: spatialResult.park, facilities: spatialResult.facilities,
  series: [{
    series_id: 'energy-series-1', unit_group: 'unit-hash', unit_group_label: 'Energy · declared energy · not applicable', unit: 'MJ',
    basis: { energy_convention: 'declared_energy', material_condition: 'not_applicable' }, nodes: [], links: [{ exchange_id: 'electricity-in' }], total_amount: '3.2727272727272725',
    facility_metrics: [{ entity_id: 'facility-a', amount: '3.2727272727272725', share: '1' }, { entity_id: 'facility-b', amount: '0', share: '0' }],
    carrier_metrics: [{ flow_uuid: 'electricity', flow_name: 'Electricity', amount: '3.2727272727272725' }],
  }],
  audit: { status: 'passed', checks: { snapshot_identity_match: true }, counts: { facilities_with_energy_count: 1 }, issues: [], limitations: ['external inputs only'], provenance: {} },
  content_sha256: 'spatial-energy-result-hash',
};

const distributionResult: SpatialDistributionResult = {
  schema_version: 'nebula_one.spatial.distribution.v1', capability_key: 'spatial.distribution.v1',
  source_snapshot: { id: snapshot.id, system_revision_id: snapshot.system_revision_id, solve_hash: snapshot.solve_hash, content_sha256: snapshot.content_sha256 },
  method_package: { ref: 'spatial.supply@1.0.0', content_sha256: 'distribution-method-hash' },
  source_flow: { name: 'Crude oil', selector: { flow_uuid: 'tidas-crude' }, amount: 1100, unit: 'kg', provider_flow_receipt: { flow_uuid: 'tidas-crude' } },
  destination: { spatial_unit: { content_sha256: 'destination-spatial-hash' }, longitude: 121.5, latitude: 31.2 },
  baseline_scenario_id: 'baseline',
  scenarios: [
    {
      scenario_id: 'baseline', name: '基准供应', description: null, content_sha256: 'baseline-hash', total_allocated: 1100, allocation_residual: 0,
      regions: [
        { region: { region_id: 'shandong', name: 'Shandong', content_sha256: 'region-a-hash' }, share: 0.6, amount: 660, baseline_amount: 660, amount_delta_from_baseline: 0, relative_delta_from_baseline: 0 },
        { region: { region_id: 'xinjiang', name: 'Xinjiang', content_sha256: 'region-b-hash' }, share: 0.4, amount: 440, baseline_amount: 440, amount_delta_from_baseline: 0, relative_delta_from_baseline: 0 },
      ],
    },
    {
      scenario_id: 'balanced', name: '均衡供应', description: null, content_sha256: 'balanced-hash', total_allocated: 1100, allocation_residual: 0,
      regions: [
        { region: { region_id: 'shandong', name: 'Shandong', content_sha256: 'region-a-hash' }, share: 0.5, amount: 550, baseline_amount: 660, amount_delta_from_baseline: -110, relative_delta_from_baseline: -1 / 6 },
        { region: { region_id: 'xinjiang', name: 'Xinjiang', content_sha256: 'region-b-hash' }, share: 0.5, amount: 550, baseline_amount: 440, amount_delta_from_baseline: 110, relative_delta_from_baseline: 0.25 },
      ],
    },
  ],
  audit: { status: 'passed', checks: { source_flow_unique: true }, counts: { region_count: 2, scenario_count: 2 }, limitations: ['representative points only'] },
  content_sha256: 'distribution-result-hash',
};

beforeEach(() => {
  vi.spyOn(api, 'pcfDefaultMethod').mockResolvedValue({
    schema_version: 'nebula_one.climate-method-resolution.v1', status: 'ready',
    reference: 'pcf.bound@2.0.0', content_sha256: 'pcf-method-hash', reason_code: null,
    method: { lcia_method: 'EF v3.1', total_indicator_key: 'climate change', result_unit: 'kg CO2-Eq', source_contract: null, source_method: null },
  });
});

afterEach(() => {
  cleanup();
  window.localStorage.removeItem(LANGUAGE_STORAGE_KEY);
  vi.restoreAllMocks();
});

describe('Analysis results page', () => {
  it('keeps a missing exact snapshot unavailable in English', async () => {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, 'en');
    vi.spyOn(api, 'application').mockResolvedValue({ id: 'app-1', name: 'User project', application_type: 'system_analysis', description: null, context: {}, status: 'active', created_at: snapshot.created_at, updated_at: snapshot.created_at });
    vi.spyOn(api, 'solvedSnapshots').mockResolvedValue([snapshot]);
    vi.spyOn(api, 'comparisonRuns').mockResolvedValue([]);
    vi.spyOn(api, 'boundaries').mockResolvedValue([]);
    const mfa = vi.spyOn(api, 'solvedMfa');
    renderResults(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={['/applications/app-1/results?snapshot=foreign-snapshot']}>
        <Routes><Route path="/applications/:applicationId/results" element={<AnalysisResultsPage />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>);
    expect(await screen.findByText('This result is unavailable or does not belong to this application. Return to the project and choose again.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Back to project' })).toBeInTheDocument();
    expect(mfa).not.toHaveBeenCalled();
  });
  it('does not substitute the first result when the requested snapshot is missing', async () => {
    vi.spyOn(api, 'application').mockResolvedValue({ id: 'app-1', name: 'Analysis', application_type: 'system_analysis', description: null, context: {}, status: 'active', created_at: snapshot.created_at, updated_at: snapshot.created_at });
    vi.spyOn(api, 'solvedSnapshots').mockResolvedValue([snapshot]);
    vi.spyOn(api, 'comparisonRuns').mockResolvedValue([]);
    vi.spyOn(api, 'boundaries').mockResolvedValue([]);
    const mfa = vi.spyOn(api, 'solvedMfa');
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderResults(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/applications/app-1/results?snapshot=foreign-snapshot']}><Routes><Route path="/applications/:applicationId/results" element={<AnalysisResultsPage />} /></Routes></MemoryRouter></QueryClientProvider>);
    expect(await screen.findByText('该结果不属于当前应用或已不可用，请返回模型重新选择。')).toBeInTheDocument();
    expect(mfa).not.toHaveBeenCalled();
    expect(screen.queryByText('冻结结果')).not.toBeInTheDocument();
  });

  it('keeps MFA, LCIA and provider evidence on one frozen snapshot', async () => {
    vi.spyOn(api, 'application').mockResolvedValue({ id: 'app-1', name: '低硫柴油产品分析', application_type: 'system_analysis', description: null, context: {}, status: 'active', created_at: snapshot.created_at, updated_at: snapshot.created_at });
    vi.spyOn(api, 'solvedSnapshots').mockResolvedValue([snapshot]);
    vi.spyOn(api, 'energyCarrierResults').mockResolvedValue([energyResult]);
    vi.spyOn(api, 'solvedMfa').mockResolvedValue({ schema_version: 'nebula_one.mfa.solved.v1', solved_snapshot_id: snapshot.id, solve_hash: snapshot.solve_hash, series: [{ series_id: 'mass::kg', unit_group: 'mass', unit_group_uuid: '93a60a57-a4c8-11da-a746-0800200c9a66', unit_group_label: 'Mass', is_mass: true, conservation: { status: 'passed', error_count: 0, warning_count: 0, open_boundary_count: 0 }, unit: 'kg', nodes: [], links: [], totals: { internal: 1, boundary_input: 2, boundary_output: 2 } }], audit: { status: 'passed' } });
    vi.spyOn(api, 'comparisonRuns').mockResolvedValue([]);
    vi.spyOn(api, 'boundaries').mockResolvedValue([]);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderResults(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/applications/app-1/results?snapshot=snapshot-1']}><Routes><Route path="/applications/:applicationId/results" element={<AnalysisResultsPage />} /></Routes></MemoryRouter></QueryClientProvider>);

const processMetric = (await screen.findByText('边界输入')).closest('article');
    expect(processMetric).toHaveTextContent('2');
    fireEvent.load(await screen.findByRole('img', { name: '冻结求解结果物质流向图' }));
    await userEvent.click(await screen.findByRole('combobox', { name: '更多分析' }));
    fireEvent.click(await screen.findByRole('option', { name: 'LCIA' }));
    expect(await screen.findByText('Climate change')).toBeInTheDocument();
    expect(screen.getByText('1.25')).toBeInTheDocument();
    await userEvent.click(await screen.findByRole('combobox', { name: '更多分析' }));
    fireEvent.click(await screen.findByRole('option', { name: '能源' }));
    expect((await screen.findAllByText('Declared Energy')).length).toBeGreaterThan(0);
    expect(screen.getAllByText('3.2727272727272725').length).toBeGreaterThan(0);
    fireEvent.load(screen.getByRole('img', { name: '冻结能源载体结果图' }));
    await userEvent.click(screen.getByRole('button', { name: '更多' }));
    fireEvent.click(await screen.findByRole('menuitem', { name: '详情' }));
    expect(await screen.findByText('solve-hash-1')).toBeInTheDocument();
    expect(screen.getByText(/provider-run-1/)).toBeInTheDocument();
    expect(screen.getByText('energy-request-hash')).toBeInTheDocument();
  });

  it.each([false, true])('loads the compatible PCF default, or refuses an explicit unknown method (invalid=%s)', async (invalid) => {
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:pcf-chart') });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
    vi.spyOn(api, 'application').mockResolvedValue({ id: 'app-1', name: '低硫柴油产品分析', application_type: 'system_analysis', description: null, context: { method_package_refs: ['pcf.bound@2.0.0', 'unrelated@1.0.0'], template_locked: true, project_capabilities: ['pcf.product.v1'] }, status: 'active', created_at: snapshot.created_at, updated_at: snapshot.created_at });
    vi.spyOn(api, 'solvedSnapshots').mockResolvedValue([{ ...snapshot, provider_receipt: {
      ...snapshot.provider_receipt, project_background_process_receipts: [{}],
      calculation_basis: { model_derivation: { purpose: 'lca' } },
    }, scaled_elementary_exchanges: [{ process_id: 'process-hotspot', exchange_id: 'process-role::co2-out' }] }]);
    const workspace = vi.spyOn(api, 'workspace').mockResolvedValue({
      application_id: 'app-1', revision_id: 'revision-3', content_sha256: 'revision-hash',
      template_title: 'Example', fields: [], demand: [], source: 'test', saved: true,
      capabilities: ['pcf.product.v1'], blocked_capabilities: [],
      background_options: [], background_note: '',
      process_graph: { nodes: [{ id: 'process-role', name: 'Saved process name' }], edges: [] },
    });
    vi.spyOn(api, 'methodPackages').mockResolvedValue([{
      id: 'method-1', package_id: 'pcf.bound', version: '2.0.0', package_kind: 'product_carbon_footprint', jurisdiction: null, valid_from: null, valid_to: null,
      manifest: { formula_graph: { lcia_method: 'EF v3.1', total_indicator_key: 'climate change' } }, content_sha256: 'pcf-method-hash', status: 'active', created_at: snapshot.created_at,
    }]);
    vi.spyOn(api, 'productCarbonFootprint').mockResolvedValue(pcfResult);
    vi.spyOn(api, 'productCarbonFootprintChart').mockResolvedValue(new Blob(['<svg />'], { type: 'image/svg+xml' }));
    vi.spyOn(api, 'energyCarrierResults').mockResolvedValue([]);
    vi.spyOn(api, 'solvedMfa').mockResolvedValue({ schema_version: 'nebula_one.mfa.solved.v1', solved_snapshot_id: snapshot.id, solve_hash: snapshot.solve_hash, series: [], audit: { status: 'passed' } });
    vi.spyOn(api, 'comparisonRuns').mockResolvedValue([]);
    vi.spyOn(api, 'boundaries').mockResolvedValue([]);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderResults(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/applications/app-1/results?snapshot=snapshot-1&view=pcf' + (invalid ? '&pcf-method=unknown' : '')]}><Routes><Route path="/applications/:applicationId/results" element={<AnalysisResultsPage />} /></Routes></MemoryRouter></QueryClientProvider>);

    if (invalid) {
      expect(await screen.findByText(/unknown/)).toBeInTheDocument();
      expect(api.productCarbonFootprint).not.toHaveBeenCalled();
      expect(screen.getByRole('combobox', { name: '核算方法包' })).toBeInTheDocument();
      return;
    }

    expect(await screen.findByText('已覆盖部分的气候变化结果')).toBeInTheDocument();
    expect((await screen.findAllByText('0.5258152')).length).toBeGreaterThan(0);
    expect(await screen.findByText('Saved process name')).toBeInTheDocument();
    expect(workspace).toHaveBeenCalledWith('app-1', 'revision-3', 'zh');
    expect(screen.queryByRole('combobox', { name: '核算方法包' })).not.toBeInTheDocument();
    expect(screen.getByText('Bound LCIA method')).toBeInTheDocument();
    expect(screen.getByText('边界范围结果')).toBeInTheDocument();
    expect(api.productCarbonFootprint).toHaveBeenCalledWith('snapshot-1', 'pcf.bound@2.0.0', { result_basis: 'total' });
    expect(api.productCarbonFootprintChart).toHaveBeenCalledWith('snapshot-1', 'pcf.bound@2.0.0', { result_basis: 'total' });
    await userEvent.click(screen.getByRole('button', { name: '更多' }));
    fireEvent.click(await screen.findByRole('menuitem', { name: '详情' }));
    expect(await screen.findByRole('img', { name: '产品碳足迹气候变化分项图' })).toHaveAttribute('src', 'blob:pcf-chart');

    expect(await screen.findByText('pcf-method-hash')).toBeInTheDocument();
    expect(screen.getByText('pcf-content-hash')).toBeInTheDocument();
    expect(screen.getByText(/inventory-hash/)).toBeInTheDocument();
    expect(screen.getByText(/receipts-hash/)).toBeInTheDocument();
  });

  it('renders only the mass series and never offers energy in the MFA view', async () => {
    vi.spyOn(api, 'application').mockResolvedValue({ id: 'app-1', name: '低硫柴油产品分析', application_type: 'system_analysis', description: null, context: {}, status: 'active', created_at: snapshot.created_at, updated_at: snapshot.created_at });
    vi.spyOn(api, 'solvedSnapshots').mockResolvedValue([snapshot]);
    vi.spyOn(api, 'energyCarrierResults').mockResolvedValue([]);
    vi.spyOn(api, 'solvedMfa').mockResolvedValue({ schema_version: 'nebula_one.mfa.solved.v1', solved_snapshot_id: snapshot.id, solve_hash: snapshot.solve_hash, series: [
      { series_id: 'mass::kg', unit_group: 'mass', unit_group_uuid: '93a60a57-a4c8-11da-a746-0800200c9a66', unit_group_label: '质量', is_mass: true, conservation: { status: 'passed', error_count: 0, warning_count: 0, open_boundary_count: 0 }, unit: 'kg', nodes: [], links: [], totals: { internal: 1, boundary_input: 2, boundary_output: 2 } },
      { series_id: 'energy::MJ', unit_group: '93a60a57-a4c8-11da-a3c8-0800200c9a66', unit_group_label: '能量', is_mass: false, conservation: { status: 'failed', error_count: 1, warning_count: 0, open_boundary_count: 0 }, unit: 'MJ', nodes: [], links: [], totals: { internal: 625, boundary_input: 625, boundary_output: 0 } },
    ], audit: { status: 'failed' } });
    vi.spyOn(api, 'comparisonRuns').mockResolvedValue([]);
    vi.spyOn(api, 'boundaries').mockResolvedValue([]);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderResults(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/applications/app-1/results?snapshot=snapshot-1&view=mfa']}><Routes><Route path="/applications/:applicationId/results" element={<AnalysisResultsPage />} /></Routes></MemoryRouter></QueryClientProvider>);

    // the mass series is shown; energy is excluded from the KPI, the picker and the verdict
    expect(await screen.findByText('边界输入')).toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: '数量序列' })).not.toBeInTheDocument();
    expect(screen.queryByText('625')).not.toBeInTheDocument();
    // a passing mass view is reported even though the whole audit failed on the energy series
    expect(screen.getByText('守恒审计')).toBeInTheDocument();
  });

  it('shows the mass-only empty state when a snapshot carries only energy', async () => {
    vi.spyOn(api, 'application').mockResolvedValue({ id: 'app-1', name: '低硫柴油产品分析', application_type: 'system_analysis', description: null, context: {}, status: 'active', created_at: snapshot.created_at, updated_at: snapshot.created_at });
    vi.spyOn(api, 'solvedSnapshots').mockResolvedValue([snapshot]);
    vi.spyOn(api, 'energyCarrierResults').mockResolvedValue([]);
    vi.spyOn(api, 'solvedMfa').mockResolvedValue({ schema_version: 'nebula_one.mfa.solved.v1', solved_snapshot_id: snapshot.id, solve_hash: snapshot.solve_hash, series: [
      { series_id: 'energy::MJ', unit_group: '93a60a57-a4c8-11da-a3c8-0800200c9a66', unit_group_label: '能量', is_mass: false, conservation: { status: 'passed', error_count: 0, warning_count: 0, open_boundary_count: 0 }, unit: 'MJ', nodes: [], links: [], totals: { internal: 625, boundary_input: 625, boundary_output: 0 } },
    ], audit: { status: 'passed' } });
    vi.spyOn(api, 'comparisonRuns').mockResolvedValue([]);
    vi.spyOn(api, 'boundaries').mockResolvedValue([]);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderResults(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/applications/app-1/results?snapshot=snapshot-1&view=mfa']}><Routes><Route path="/applications/:applicationId/results" element={<AnalysisResultsPage />} /></Routes></MemoryRouter></QueryClientProvider>);

    expect(await screen.findByText('暂无可展示的质量流。')).toBeInTheDocument();
  });

  it('honours an explicit PCF method package across reload instead of falling back to the first bound one', async () => {
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:pcf-chart') });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
    vi.spyOn(api, 'application').mockResolvedValue({ id: 'app-1', name: '低硫柴油产品分析', application_type: 'system_analysis', description: null, context: { method_package_refs: ['pcf.bound@2.0.0', 'pcf.bound@3.0.0'] }, status: 'active', created_at: snapshot.created_at, updated_at: snapshot.created_at });
    vi.spyOn(api, 'solvedSnapshots').mockResolvedValue([snapshot]);
    vi.spyOn(api, 'methodPackages').mockResolvedValue([2, 3].map((minor) => ({
      id: `method-${minor}`, package_id: 'pcf.bound', version: `${minor}.0.0`, package_kind: 'product_carbon_footprint' as const, jurisdiction: null, valid_from: null, valid_to: null,
      manifest: { formula_graph: { lcia_method: `Bound LCIA method ${minor}` } }, content_sha256: `pcf-method-hash-${minor}`, status: 'active', created_at: snapshot.created_at,
    })));
    vi.spyOn(api, 'productCarbonFootprint').mockImplementation(async (_id, reference) => ({
      ...pcfResult,
      method_package: { ...pcfResult.method_package, reference, lcia_method: `Bound LCIA ${reference}` },
    }));
    vi.spyOn(api, 'productCarbonFootprintChart').mockResolvedValue(new Blob(['<svg />'], { type: 'image/svg+xml' }));
    vi.spyOn(api, 'energyCarrierResults').mockResolvedValue([]);
    vi.spyOn(api, 'solvedMfa').mockResolvedValue({ schema_version: 'nebula_one.mfa.solved.v1', solved_snapshot_id: snapshot.id, solve_hash: snapshot.solve_hash, series: [], audit: { status: 'passed' } });
    vi.spyOn(api, 'comparisonRuns').mockResolvedValue([]);
    vi.spyOn(api, 'boundaries').mockResolvedValue([]);
    const entry = '/applications/app-1/results?snapshot=snapshot-1&view=pcf&pcf-method=pcf.bound%403.0.0';
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { unmount } = renderResults(<QueryClientProvider client={client}><MemoryRouter initialEntries={[entry]}><Routes><Route path="/applications/:applicationId/results" element={<AnalysisResultsPage />} /></Routes></MemoryRouter></QueryClientProvider>);

    expect(await screen.findByText('Bound LCIA pcf.bound@3.0.0')).toBeInTheDocument();
    expect(api.productCarbonFootprint).toHaveBeenCalledWith('snapshot-1', 'pcf.bound@3.0.0', { result_basis: 'total' });
    expect(client.getQueryData(['product-carbon-footprint', 'snapshot-1', 'pcf.bound@2.0.0'])).toBeUndefined();

    unmount();
    vi.mocked(api.productCarbonFootprint).mockClear();
    renderResults(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter initialEntries={[entry]}><Routes><Route path="/applications/:applicationId/results" element={<AnalysisResultsPage />} /></Routes></MemoryRouter></QueryClientProvider>);
    expect(await screen.findByText('Bound LCIA pcf.bound@3.0.0')).toBeInTheDocument();
    expect(api.productCarbonFootprint).toHaveBeenCalledWith('snapshot-1', 'pcf.bound@3.0.0', { result_basis: 'total' });
  });

  it('shows period carbon results without inventing Scope attribution', async () => {
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:carbon-chart') });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
    vi.spyOn(api, 'application').mockResolvedValue({ id: 'app-1', name: '炼厂年度分析', application_type: 'system_analysis', description: null, context: { method_package_refs: ['carbon.period@1.0.0'] }, status: 'active', created_at: snapshot.created_at, updated_at: snapshot.created_at });
    vi.spyOn(api, 'solvedSnapshots').mockResolvedValue([snapshot]);
    vi.spyOn(api, 'methodPackages').mockResolvedValue([{ id: 'method-carbon', package_id: 'carbon.period', version: '1.0.0', package_kind: 'period_carbon_management', jurisdiction: null, valid_from: null, valid_to: null, manifest: {}, content_sha256: 'carbon-method-hash', status: 'active', created_at: snapshot.created_at }]);
    vi.spyOn(api, 'energyCarrierResults').mockResolvedValue([energyResult]);
    vi.spyOn(api, 'carbonManagement').mockResolvedValue(carbonResult);
    vi.spyOn(api, 'carbonManagementChart').mockResolvedValue(new Blob(['<svg />'], { type: 'image/svg+xml' }));
    vi.spyOn(api, 'solvedMfa').mockResolvedValue({ schema_version: 'nebula_one.mfa.solved.v1', solved_snapshot_id: snapshot.id, solve_hash: snapshot.solve_hash, series: [], audit: { status: 'passed' } });
    vi.spyOn(api, 'comparisonRuns').mockResolvedValue([]);
    vi.spyOn(api, 'boundaries').mockResolvedValue([]);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderResults(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/applications/app-1/results?snapshot=snapshot-1']}><Routes><Route path="/applications/:applicationId/results" element={<AnalysisResultsPage />} /></Routes></MemoryRouter></QueryClientProvider>);

    await userEvent.click(await screen.findByRole('combobox', { name: '更多分析' }));
    fireEvent.click(await screen.findByRole('option', { name: '能源碳管理' }));
    expect((await screen.findAllByText('0.5258152')).length).toBeGreaterThan(0);
    expect(screen.getByText('当前不是 Scope 1/2/3 清单')).toBeInTheDocument();
    expect(api.carbonManagement).toHaveBeenCalledWith('snapshot-1', 'carbon.period@1.0.0', 'energy-result-1');
    expect(await screen.findByRole('img', { name: '期间能源碳管理图' })).toHaveAttribute('src', 'blob:carbon-chart');
    await userEvent.click(screen.getByRole('button', { name: '更多' }));
    fireEvent.click(await screen.findByRole('menuitem', { name: '详情' }));
    expect(await screen.findByText('carbon-method-hash')).toBeInTheDocument();
    expect(screen.getByText('carbon-content-hash')).toBeInTheDocument();
  });

  it('shows the consolidated park MFA from a frozen park boundary', async () => {
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:park-chart') });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
    vi.spyOn(api, 'application').mockResolvedValue({ id: 'app-1', name: '石化园区年度分析', application_type: 'system_analysis', description: null, context: {}, status: 'active', created_at: snapshot.created_at, updated_at: snapshot.created_at });
    vi.spyOn(api, 'solvedSnapshots').mockResolvedValue([snapshot]);
    vi.spyOn(api, 'energyCarrierResults').mockResolvedValue([]);
    vi.spyOn(api, 'solvedMfa').mockResolvedValue({ schema_version: 'nebula_one.mfa.solved.v1', solved_snapshot_id: snapshot.id, solve_hash: snapshot.solve_hash, series: [], audit: { status: 'passed' } });
    vi.spyOn(api, 'comparisonRuns').mockResolvedValue([]);
    vi.spyOn(api, 'boundaries').mockResolvedValue([parkBoundary]);
    vi.spyOn(api, 'spatialAggregate').mockResolvedValue(spatialResult);
    vi.spyOn(api, 'spatialAggregateChart').mockResolvedValue(new Blob(['<svg />'], { type: 'image/svg+xml' }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderResults(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/applications/app-1/results?snapshot=snapshot-1']}><Routes><Route path="/applications/:applicationId/results" element={<AnalysisResultsPage />} /></Routes></MemoryRouter></QueryClientProvider>);

    await userEvent.click(await screen.findByRole('combobox', { name: '更多分析' }));
    fireEvent.click(await screen.findByRole('option', { name: '园区' }));
    expect(await screen.findByText('园区边界合并 MFA')).toBeInTheDocument();
    expect(screen.getAllByText('1,100').length).toBeGreaterThan(0);
    expect(screen.getByText('一次加工设施')).toBeInTheDocument();
    expect(api.spatialAggregate).toHaveBeenCalledWith('snapshot-1', 'boundary-park-1');
    expect(await screen.findByRole('img', { name: '园区合并物质流桑基图' })).toHaveAttribute('src', 'blob:park-chart');
    await userEvent.click(screen.getByRole('button', { name: '更多' }));
    fireEvent.click(await screen.findByRole('menuitem', { name: '详情' }));
    expect(await screen.findByText('spatial-result-hash')).toBeInTheDocument();
    expect(screen.getByText('park-spatial-hash')).toBeInTheDocument();
  });

  it('attributes solved external energy inputs to exact park facilities', async () => {
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:spatial-energy-chart') });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
    vi.spyOn(api, 'application').mockResolvedValue({ id: 'app-1', name: '石化园区年度分析', application_type: 'system_analysis', description: null, context: {}, status: 'active', created_at: snapshot.created_at, updated_at: snapshot.created_at });
    vi.spyOn(api, 'solvedSnapshots').mockResolvedValue([snapshot]);
    vi.spyOn(api, 'energyCarrierResults').mockResolvedValue([energyResult]);
    vi.spyOn(api, 'solvedMfa').mockResolvedValue({ schema_version: 'nebula_one.mfa.solved.v1', solved_snapshot_id: snapshot.id, solve_hash: snapshot.solve_hash, series: [], audit: { status: 'passed' } });
    vi.spyOn(api, 'comparisonRuns').mockResolvedValue([]);
    vi.spyOn(api, 'boundaries').mockResolvedValue([parkBoundary]);
    vi.spyOn(api, 'spatialAggregate').mockResolvedValue(spatialResult);
    vi.spyOn(api, 'spatialEnergy').mockResolvedValue(spatialEnergyResult);
    vi.spyOn(api, 'spatialEnergyChart').mockResolvedValue(new Blob(['<svg />'], { type: 'image/svg+xml' }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderResults(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/applications/app-1/results?snapshot=snapshot-1']}><Routes><Route path="/applications/:applicationId/results" element={<AnalysisResultsPage />} /></Routes></MemoryRouter></QueryClientProvider>);

    await userEvent.click(await screen.findByRole('combobox', { name: '更多分析' }));
    fireEvent.click(await screen.findByRole('option', { name: '园区能源' }));
    expect(await screen.findByText('园区外部能源投入')).toBeInTheDocument();
    expect(screen.getByText('一次加工设施')).toBeInTheDocument();
    expect(screen.getByText('100.0%')).toBeInTheDocument();
    expect(api.spatialEnergy).toHaveBeenCalledWith('snapshot-1', 'boundary-park-1', 'energy-result-1');
    expect(api.spatialEnergyChart).toHaveBeenCalledWith('snapshot-1', 'boundary-park-1', 'energy-result-1', 'energy-series-1');
    expect(await screen.findByRole('img', { name: '园区外部能源投入桑基图' })).toHaveAttribute('src', 'blob:spatial-energy-chart');
    await userEvent.click(screen.getByRole('button', { name: '更多' }));
    fireEvent.click(await screen.findByRole('menuitem', { name: '详情' }));
    expect(await screen.findByText('spatial-energy-result-hash')).toBeInTheDocument();
    expect(screen.getByText('energy-domain-hash')).toBeInTheDocument();
  });

  it('shows an audited province supply map from the bound distribution package', async () => {
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:supply-map') });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
    vi.spyOn(api, 'application').mockResolvedValue({ id: 'app-1', name: '石化园区年度分析', application_type: 'system_analysis', description: null, context: { method_package_refs: ['spatial.supply@1.0.0'] }, status: 'active', created_at: snapshot.created_at, updated_at: snapshot.created_at });
    vi.spyOn(api, 'solvedSnapshots').mockResolvedValue([snapshot]);
    vi.spyOn(api, 'methodPackages').mockResolvedValue([{ id: 'method-spatial', package_id: 'spatial.supply', version: '1.0.0', package_kind: 'spatial_distribution', jurisdiction: 'CN-demonstration', valid_from: null, valid_to: null, manifest: {}, content_sha256: 'distribution-method-hash', status: 'active', created_at: snapshot.created_at }]);
    vi.spyOn(api, 'spatialDistribution').mockResolvedValue(distributionResult);
    vi.spyOn(api, 'spatialDistributionMap').mockResolvedValue(new Blob(['<svg />'], { type: 'image/svg+xml' }));
    vi.spyOn(api, 'energyCarrierResults').mockResolvedValue([]);
    vi.spyOn(api, 'solvedMfa').mockResolvedValue({ schema_version: 'nebula_one.mfa.solved.v1', solved_snapshot_id: snapshot.id, solve_hash: snapshot.solve_hash, series: [], audit: { status: 'passed' } });
    vi.spyOn(api, 'comparisonRuns').mockResolvedValue([]);
    vi.spyOn(api, 'boundaries').mockResolvedValue([]);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderResults(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/applications/app-1/results?snapshot=snapshot-1']}><Routes><Route path="/applications/:applicationId/results" element={<AnalysisResultsPage />} /></Routes></MemoryRouter></QueryClientProvider>);

    await userEvent.click(await screen.findByRole('combobox', { name: '更多分析' }));
    fireEvent.click(await screen.findByRole('option', { name: '供应地图' }));
    expect(await screen.findByText('省域供应分布')).toBeInTheDocument();
    expect(screen.getAllByText('1,100').length).toBeGreaterThan(0);
    expect(screen.getByText('演示空间归因，不是行政区统计地图')).toBeInTheDocument();
    expect(api.spatialDistribution).toHaveBeenCalledWith('snapshot-1', 'spatial.supply@1.0.0');
    expect(api.spatialDistributionMap).toHaveBeenCalledWith('snapshot-1', 'spatial.supply@1.0.0', 'baseline');
    expect(await screen.findByRole('img', { name: '省域供应流向图' })).toHaveAttribute('src', 'blob:supply-map');
    await userEvent.click(screen.getByRole('button', { name: '更多' }));
    fireEvent.click(await screen.findByRole('menuitem', { name: '详情' }));
    expect(await screen.findByText('distribution-result-hash')).toBeInTheDocument();
    expect(screen.getByText('destination-spatial-hash')).toBeInTheDocument();
  });

  const renderWithSolvedMfa = (entry: string) => {
    vi.spyOn(api, 'application').mockResolvedValue({ id: 'app-1', name: '低硫柴油产品分析', application_type: 'system_analysis', description: null, context: {}, status: 'active', created_at: snapshot.created_at, updated_at: snapshot.created_at });
    vi.spyOn(api, 'solvedSnapshots').mockResolvedValue([snapshot]);
    vi.spyOn(api, 'methodPackages').mockResolvedValue([]);
    vi.spyOn(api, 'energyCarrierResults').mockResolvedValue([]);
    vi.spyOn(api, 'solvedMfa').mockResolvedValue({ schema_version: 'nebula_one.mfa.solved.v1', solved_snapshot_id: snapshot.id, solve_hash: snapshot.solve_hash, series: [{ series_id: 'mass::kg', unit_group: 'mass', unit_group_uuid: '93a60a57-a4c8-11da-a746-0800200c9a66', unit_group_label: 'Mass', is_mass: true, conservation: { status: 'passed', error_count: 0, warning_count: 0, open_boundary_count: 0 }, unit: 'kg', nodes: [], links: [], totals: { internal: 1, boundary_input: 2, boundary_output: 2 } }], audit: { status: 'passed' } });
    vi.spyOn(api, 'comparisonRuns').mockResolvedValue([]);
    vi.spyOn(api, 'boundaries').mockResolvedValue([]);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderResults(<QueryClientProvider client={client}><MemoryRouter initialEntries={[entry]}><Routes><Route path="/applications/:applicationId/results" element={<AnalysisResultsPage />} /></Routes></MemoryRouter></QueryClientProvider>);
  };

  it.each(['cbm', ''])('refuses an explicit invalid result view "%s" instead of showing MFA numbers', async (view) => {
    renderWithSolvedMfa(`/applications/app-1/results?snapshot=snapshot-1&view=${view}`);

    expect(await screen.findByText('链接指定的引用无法使用')).toBeInTheDocument();
    expect(screen.getByText(new RegExp(`结果视图「${view}」不属于当前对象或已不存在`))).toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: '物质流分析' })).not.toBeInTheDocument();
    expect(screen.queryByText('边界输入')).not.toBeInTheDocument();
    expect(screen.queryByText('冻结结果')).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: '清除并重新选择' }));
    expect(await screen.findByRole('tab', { name: '物质流分析' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.queryByText('链接指定的引用无法使用')).not.toBeInTheDocument();
    expect(await screen.findByText('边界输入')).toBeInTheDocument();
  });

  it('opens the CBAM trial directly from a deep linked view', async () => {
    renderWithSolvedMfa('/applications/app-1/results?snapshot=snapshot-1&view=cbam');

    expect(await screen.findByText('该任务尚无匹配当前数据版本的计算结果。')).toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: '物质流分析' })).not.toBeInTheDocument();
    expect(screen.queryByText('边界输入')).not.toBeInTheDocument();
  });

  it('shows the bound direct trial on a CBAM solve even when a partial review method is also bound', async () => {
    const directRef = 'cbam.steel.direct@1.1.3';
    const partialRef = 'cbam.steel.partial@1.0.4';
    vi.spyOn(api, 'application').mockResolvedValue({ id: 'app-1', name: '钢铁分析', application_type: 'system_analysis', description: null,
      context: { method_package_refs: [directRef, partialRef] }, status: 'active', created_at: snapshot.created_at, updated_at: snapshot.created_at });
    vi.spyOn(api, 'solvedSnapshots').mockResolvedValue([{ ...snapshot,
      provider_receipt: { calculation_basis: { model_derivation: { purpose: 'cbam' } } } }]);
    vi.spyOn(api, 'methodPackages').mockResolvedValue([
      { id: 'direct', package_id: 'cbam.steel.direct', version: '1.1.3', package_kind: 'cbam_trial', jurisdiction: 'EU', valid_from: null, valid_to: null,
        manifest: { output_schema: { schema_version: 'nebula_one.cbam.trial.v2' } }, content_sha256: 'direct-hash', status: 'active', created_at: snapshot.created_at },
      { id: 'partial', package_id: 'cbam.steel.partial', version: '1.0.4', package_kind: 'cbam_partial_review', jurisdiction: 'EU', valid_from: null, valid_to: null,
        manifest: {}, content_sha256: 'partial-hash', status: 'active', created_at: snapshot.created_at },
    ]);
    vi.spyOn(api, 'periods').mockResolvedValue([{ id: 'period-2026', application_id: 'app-1', key: 'calendar-2026', name: '2026 年', resolution: 'year',
      start_date: '2026-01-01', end_date: '2026-12-31', created_at: snapshot.created_at }]);
    vi.spyOn(api, 'boundaries').mockResolvedValue([]);
    vi.spyOn(api, 'energyCarrierResults').mockResolvedValue([]);
    vi.spyOn(api, 'solvedMfa').mockResolvedValue({ schema_version: 'nebula_one.mfa.solved.v1', solved_snapshot_id: snapshot.id,
      solve_hash: snapshot.solve_hash, series: [], audit: { status: 'passed' } });
    vi.spyOn(api, 'comparisonRuns').mockResolvedValue([]);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderResults(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/applications/app-1/results?snapshot=snapshot-1&view=cbam']}>
      <Routes><Route path="/applications/:applicationId/results" element={<AnalysisResultsPage />} /></Routes>
    </MemoryRouter></QueryClientProvider>);
    expect(await screen.findByRole('heading', { name: /CBAM 试算/ })).toBeInTheDocument();
  });

  // Fixtures mirror the live failing page: runtime/isolated-2026-09-17/evidence/segment4-browser-01/http/cbam-simple-trial-rejection.json
  const renderCbamSimpleRejection = (client: QueryClient) => {
    vi.spyOn(api, 'application').mockResolvedValue({ id: 'app-1', name: '合成氨产品分析', application_type: 'system_analysis', description: null, context: { method_package_refs: ['cbam.eu.hydrogen.direct-trial@1.0.0', 'cbam.eu.ammonia.complex-trial@1.0.0'] }, status: 'active', created_at: snapshot.created_at, updated_at: snapshot.created_at });
    vi.spyOn(api, 'solvedSnapshots').mockResolvedValue([{ ...snapshot,
      provider_receipt: { calculation_basis: { model_derivation: { purpose: 'cbam' } } } }]);
    vi.spyOn(api, 'methodPackages').mockResolvedValue([
      { id: 'cbam-simple', package_id: 'cbam.eu.hydrogen.direct-trial', version: '1.0.0', package_kind: 'cbam_trial', jurisdiction: 'EU', valid_from: null, valid_to: null, manifest: {}, content_sha256: 'cbam-simple-hash', status: 'active', created_at: snapshot.created_at },
      { id: 'cbam-complex', package_id: 'cbam.eu.ammonia.complex-trial', version: '1.0.0', package_kind: 'cbam_complex_trial', jurisdiction: 'EU', valid_from: null, valid_to: null, manifest: {}, content_sha256: 'cbam-complex-hash', status: 'active', created_at: snapshot.created_at },
    ]);
    vi.spyOn(api, 'periods').mockResolvedValue([{ id: 'period-2026', application_id: 'app-1', key: 'calendar-2026', name: 'Calendar year 2026', resolution: 'year', start_date: '2026-01-01', end_date: '2026-12-31', created_at: snapshot.created_at }]);
    vi.spyOn(api, 'cbamTrial').mockRejectedValue(new ApiError('the product Process must resolve once in the activity vector', 422, 'CBAM_TRIAL_ACTIVITY_NOT_UNIQUE', { match_count: 0 }));
    vi.spyOn(api, 'energyCarrierResults').mockResolvedValue([]);
    vi.spyOn(api, 'solvedMfa').mockResolvedValue({ schema_version: 'nebula_one.mfa.solved.v1', solved_snapshot_id: snapshot.id, solve_hash: snapshot.solve_hash, series: [], audit: { status: 'passed' } });
    vi.spyOn(api, 'comparisonRuns').mockResolvedValue([]);
    vi.spyOn(api, 'boundaries').mockResolvedValue([]);
    renderResults(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/applications/app-1/results?snapshot=snapshot-1&view=cbam&cbam-tab=simple']}><Routes><Route path="/applications/:applicationId/results" element={<AnalysisResultsPage />} /></Routes></MemoryRouter></QueryClientProvider>);
  };

  it('keeps a rejected CBAM simple trial visible without retrying the refusal', async () => {
    renderCbamSimpleRejection(createAppQueryClient());

    expect(await screen.findByText('the product Process must resolve once in the activity vector')).toBeInTheDocument();
    expect(screen.getByText(/错误码：CBAM_TRIAL_ACTIVITY_NOT_UNIQUE（HTTP 422）/)).toBeInTheDocument();
    expect(api.cbamTrial).toHaveBeenCalledWith('snapshot-1', { method_package_ref: 'cbam.eu.hydrogen.direct-trial@1.0.0', reporting_period_id: 'period-2026' });
    await new Promise((resolve) => setTimeout(resolve, 1_100));
    expect(api.cbamTrial).toHaveBeenCalledTimes(1);
  });

  it('explains a CBAM simple trial whose retry is held back while the tab is in the background', async () => {
    const visibility = Object.getOwnPropertyDescriptor(document, 'visibilityState');
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' });
    try {
      // react-query pauses a retry while the page is hidden, leaving the query pending with no error.
      renderCbamSimpleRejection(new QueryClient({ defaultOptions: { queries: { staleTime: 15_000, retry: () => true, refetchOnWindowFocus: false }, mutations: { retry: false } } }));
      document.dispatchEvent(new Event('visibilitychange'));

      expect(await screen.findByText('试算请求未完成', undefined, { timeout: 3_000 })).toBeInTheDocument();
      expect(screen.getByText('页面处于后台或设备离线时请求会暂停，本次没有产生试算结果。')).toBeInTheDocument();
      expect(api.cbamTrial).toHaveBeenCalledTimes(1);
    } finally {
      if (visibility?.get) Object.defineProperty(document, 'visibilityState', visibility);
      else delete (document as { visibilityState?: string }).visibilityState;
    }
  });

  it('opens the organization inventory from a deep linked view without an MFA context', async () => {
    renderWithSolvedMfa('/applications/app-1/results?snapshot=snapshot-1&view=organization-ghg');

    expect(await screen.findByRole('tab', { name: '组织清单' })).toHaveAttribute('aria-selected', 'true');
    expect(await screen.findByText('组织清单按下方绑定的多个活动系统汇总；产品功能单位不作为年度组织核算边界。')).toBeInTheDocument();
    expect(screen.queryByText('边界输入')).not.toBeInTheDocument();
  });

  const climateSnapshot: SolvedSystemSnapshot = {
    ...snapshot,
    id: 'snapshot-climate',
    lcia_results: {},
    native_background_climate: {
      schema_version: 'nebula_one.native-background-climate.v1',
      source_contract: { repository: 'nebula-lca', commit: '2c3ebd7e72be644db47e1f9049417aa1cf8bf6d3', document: 'docs/PROVIDER_NATIVE_CLIMATE_TOTAL_V1.md', document_sha256: 'd'.repeat(64) },
      request: { schema_version: 'provider.native-background-climate-total.request.v1', database_release: 'ecoinvent_3.11', method_package_id: 'ecoinvent-ef31-climate-total-3.11', method_package_version: '1.0.0', method_package_sha256: 'f'.repeat(64), runtime_manifest_sha256: 'e'.repeat(64), flow_snapshot_hash: 'a'.repeat(64), reference_dependency_snapshot_hash: 'b'.repeat(64) },
      response: { schema_version: 'provider.native-background-climate-total.response.v1', method_package_id: 'ecoinvent-ef31-climate-total-3.11', method_package_version: '1.0.0', method_package_sha256: 'f'.repeat(64), runtime_manifest_sha256: 'e'.repeat(64), indicator: { method: 'EF v3.1', category: 'climate change', name: 'GWP100', unit: 'kg CO2-Eq' }, merge_status: 'merged', merge_blockers: [], unified_climate_total: 2.0883914, domains: { foreground: { source_namespace: 'inline_custom', contribution_value: 1.5, indicator_unit: 'kg CO2-Eq', coverage: { explicit_nonzero: 12 }, negative_cf_exchange_count: 0, terms: [] }, native_background: { source_namespace: 'tiangong_open_data', contribution_value: 0.5883914, indicator_unit: 'kg CO2-Eq', coverage: { explicit_nonzero: 83, no_cf: 2654 }, negative_cf_exchange_count: 1, terms: [] } }, provider_system_model_evidence: 'not_asserted_by_local_vector_metadata', carbon_storage_permanence: 'not_assessed', claim_limit: 'partial background coverage' },
    },
  };

  const renderSteelProject = (entry: string, snapshots: SolvedSystemSnapshot[], capabilities = ['mfa.solved.v1'], packages: MethodPackage[] = []) => {
    vi.spyOn(api, 'application').mockResolvedValue({ id: 'app-1', name: '钢铁 BF-BOF 粗钢', application_type: 'system_analysis', description: null, context: { template_locked: true, project_capabilities: capabilities, method_package_refs: [] }, status: 'active', created_at: snapshot.created_at, updated_at: snapshot.created_at });
    vi.spyOn(api, 'solvedSnapshots').mockResolvedValue(snapshots);
    vi.spyOn(api, 'methodPackages').mockResolvedValue(packages);
    vi.spyOn(api, 'energyCarrierResults').mockResolvedValue([]);
    vi.spyOn(api, 'solvedMfa').mockResolvedValue({ schema_version: 'nebula_one.mfa.solved.v1', solved_snapshot_id: snapshots[0].id, solve_hash: snapshots[0].solve_hash, series: [{ series_id: 'mass::kg', unit_group: 'mass', unit_group_uuid: '93a60a57-a4c8-11da-a746-0800200c9a66', unit_group_label: 'Mass', is_mass: true, conservation: { status: 'passed', error_count: 0, warning_count: 0, open_boundary_count: 0 }, unit: 'kg', nodes: [], links: [], totals: { internal: 1, boundary_input: 2, boundary_output: 2 } }], audit: { status: 'passed' } });
    vi.spyOn(api, 'comparisonRuns').mockResolvedValue([]);
    vi.spyOn(api, 'boundaries').mockResolvedValue([]);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderResults(<QueryClientProvider client={client}><MemoryRouter initialEntries={[entry]}><Routes><Route path="/applications/:applicationId/results" element={<AnalysisResultsPage />} /></Routes></MemoryRouter></QueryClientProvider>);
  };

  it('shows the pinned climate answer for a snapshot frozen in that mode', async () => {
    renderSteelProject('/applications/app-1/results?snapshot=snapshot-climate&view=climate', [climateSnapshot]);

    expect(screen.queryByRole('tab', { name: '部分背景气候' })).not.toBeInTheDocument();
    expect(await screen.findByText('2.0883914')).toBeInTheDocument();
    expect(screen.getByText(/未纳入特征化 2,654 项/)).toBeInTheDocument();
    // The climate total is not a product carbon footprint, so the PCF view is not offered here.
    expect(screen.queryByRole('tab', { name: '产品碳足迹' })).not.toBeInTheDocument();
  });

  it('keeps a steel PCF task empty when only an MFA snapshot exists on the selected revision', async () => {
    const pcf = vi.spyOn(api, 'productCarbonFootprint');
    const resolved = vi.spyOn(api, 'pcfDefaultMethod');
    renderSteelProject('/applications/app-1/results?view=pcf&revision=revision-3',
      [snapshot], ['mfa.solved.v1', 'pcf.product.v1']);
    expect(await screen.findByText('该任务尚无匹配当前数据版本的计算结果。')).toBeInTheDocument();
    expect(screen.queryByRole('tablist', { name: '结果分析' })).not.toBeInTheDocument();
    expect(pcf).not.toHaveBeenCalled();
    expect(resolved).not.toHaveBeenCalled();
  });

  it('shows a pinned PCF result with project supply even when the template has no purpose derivation', async () => {
    const reference = 'pcf.product.ef31.foreground@1.0.1';
    const supplied: SolvedSystemSnapshot = { ...snapshot, id: 'snapshot-supplied-pcf',
      provider_receipt: { project_background_process_receipts: [{ consumer_exchange_id: 'casting::electricity' }],
        calculation_basis: { lcia_methods: ['EF v3.1'], calculation_method: {
          reference, content_sha256: 'a'.repeat(64), lcia_method: 'EF v3.1',
        } } } };
    vi.spyOn(api, 'pcfDefaultMethod').mockResolvedValue({ schema_version: 'nebula_one.climate-method-resolution.v1', status: 'ready',
      reference, content_sha256: 'a'.repeat(64), reason_code: null,
      method: { lcia_method: 'EF v3.1', total_indicator_key: 'climate change', result_unit: 'kg CO2-Eq', source_contract: null, source_method: null } });
    const pcf = vi.spyOn(api, 'productCarbonFootprint').mockResolvedValue(pcfResult);
    vi.spyOn(api, 'productCarbonFootprintChart').mockResolvedValue(new Blob(['<svg />'], { type: 'image/svg+xml' }));
    renderSteelProject('/applications/app-1/results?snapshot=snapshot-supplied-pcf&view=pcf',
      [supplied], ['mfa.solved.v1', 'pcf.product.v1'], [{ id: 'pcf-method', package_id: 'pcf.product.ef31.foreground', version: '1.0.1',
        package_kind: 'product_carbon_footprint', jurisdiction: null, valid_from: null, valid_to: null,
        manifest: { formula_graph: { lcia_method: 'EF v3.1', total_indicator_key: 'climate change' } },
        content_sha256: 'a'.repeat(64), status: 'active', created_at: snapshot.created_at }]);
    await waitFor(() => expect(pcf).toHaveBeenCalledWith('snapshot-supplied-pcf', reference, { result_basis: 'total' }));
    expect(screen.queryByText('该任务尚无匹配当前数据版本的计算结果。')).not.toBeInTheDocument();
    expect(api.pcfDefaultMethod).toHaveBeenCalledWith('snapshot-supplied-pcf');
    expect(pcf).toHaveBeenCalledWith('snapshot-supplied-pcf', reference, { result_basis: 'total' });
  });

  it('explains the missing electricity association for a solved organization deep link', async () => {
    renderSteelProject('/applications/app-1/results?snapshot=snapshot-1&view=organization-lifecycle',
      [snapshot], ['mfa.solved.v1', 'organization.lifecycle-carbon.v1']);
    expect(await screen.findByText(/尚未关联电力供应/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '去关联电力供应' })).toHaveAttribute('href',
      `/applications/app-1/workbench?step=data&revision=${snapshot.system_revision_id}`);
    expect(screen.queryByRole('link', { name: '计算组织碳核算' })).not.toBeInTheDocument();
  });

  it('refuses the climate view on a projection snapshot instead of borrowing another result', async () => {
    renderSteelProject('/applications/app-1/results?snapshot=snapshot-1&view=climate', [snapshot]);

    expect(await screen.findByText('链接指定的引用无法使用')).toBeInTheDocument();
    expect(screen.queryByText('2.0883914')).not.toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: '部分背景气候' })).not.toBeInTheDocument();
  });
});
