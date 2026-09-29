import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useNavigate, useSearchParams } from 'react-router-dom';
import type { ComponentProps, ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, api } from '../api/client';
import type {
  EnergyCarrierResult,
  InventorySnapshot,
  MethodPackage,
  OrganizationGhgInventoryResult,
  OrganizationGhgInventoryV1Result,
  ReportingPeriod,
  SolvedSystemSnapshot,
  SystemBinding,
} from '../api/types';
import { classifyBindingRole } from './OrganizationGhgInventoryFormalPanel';
import { OrganizationGhgInventoryPanel, provinceScenarios, suggestPeriodBindings } from './OrganizationGhgInventoryPanel';

const periods = [
  { id: 'period-q1', application_id: 'app-1', key: 'q1', name: '2025 Q1', start_date: '2025-01-01', end_date: '2025-03-31', resolution: 'quarter', created_at: '2026-09-01T08:00:00Z' },
  { id: 'period-q2', application_id: 'app-1', key: 'q2', name: '2025 Q2', start_date: '2025-04-01', end_date: '2025-06-30', resolution: 'quarter', created_at: '2026-09-01T08:00:00Z' },
] as ReportingPeriod[];
const snapshots = periods.map((_, index) => ({
  id: `snapshot-q${index + 1}`, application_id: 'app-1', system_revision_id: `revision-q${index + 1}`,
  inventory_snapshot_id: null, parameter_set_id: null, solve_hash: `solve-q${index + 1}`, provider: 'nebula-lca', provider_receipt: {}, functional_unit: {}, database_release: 'EF3.1', solver_version: 'provider-v1',
  activity_vector: [], scaled_technosphere_exchanges: [], scaled_elementary_exchanges: [], internal_transfers: [], boundary_flows: [], process_balance_residuals: [], contribution_graph: {}, lcia_results: {}, content_sha256: `${index + 1}`.repeat(64), created_at: `2026-09-01T0${index + 8}:00:00Z`,
})) as SolvedSystemSnapshot[];
const energies = snapshots.map((snapshot, index) => ({ id: `energy-q${index + 1}`, solved_snapshot_id: snapshot.id, created_at: snapshot.created_at })) as EnergyCarrierResult[];
const inventories = periods.map((period, index) => ({ id: `inventory-q${index + 1}`, name: `${period.name}产量`, period_id: period.id, system_revision_id: snapshots[index].system_revision_id, status: 'frozen', content_sha256: `${index + 3}`.repeat(64) })) as InventorySnapshot[];

function method(packageId: string, kind: string, manifest: Record<string, unknown> = {}): MethodPackage {
  return { id: packageId, package_id: packageId, version: '1.0.0', package_kind: kind, jurisdiction: null, valid_from: null, valid_to: null, manifest, content_sha256: 'a'.repeat(64), status: 'active', created_at: '2026-09-01T08:00:00Z' };
}

const classificationRules = {
  classification_rules: {
    role_mappings: [
      { role_pattern: 'scope_1', scope: 'scope_1', category: 'stationary_combustion' },
      { role_pattern: 'scope_2', scope: 'scope_2', category: 'purchased_electricity' },
      { role_pattern: 'scope_3_purchased_crude', scope: 'scope_3', category: 'purchased_goods' },
      { role_pattern: 'scope_3_upstream_transport', scope: 'scope_3', category: 'upstream_transport' },
    ],
  },
};

const organizationMethod = method('ghg.organization.partial-trial', 'organization_ghg_inventory_trial');
const formalOrganizationMethod = method('ghg.organization.formal', 'organization_ghg_inventory', classificationRules);
const otherFormalMethod = method('ghg.organization.formal.alt', 'organization_ghg_inventory', classificationRules);
const pcfMethod = method('pcf.product', 'product_carbon_footprint');
const otherPcfMethod = method('pcf.product.alt', 'product_carbon_footprint');
const carbonMethod = method('carbon.management.period', 'period_carbon_management');
const provinceMethod = method('electricity.province', 'province_electricity_factor', { classification_rules: { scenarios: [{ scenario_id: 'zhejiang-2023', province_name: 'Zhejiang' }, { scenario_id: 'guizhou-2024', province_name: 'Guizhou' }] } });
const result = {
  schema_version: 'nebula_one.organization-ghg-inventory-trial.v1', capability_key: 'ghg.inventory.trial.v1', application_id: 'app-1',
  method_package: { ref: 'ghg.organization.partial-trial@1.0.0', content_sha256: 'method-hash' },
  source_period_energy_total: { content_sha256: 'period-total-hash', period_ids: periods.map((item) => item.id) },
  reporting_period: { id: 'year-2025', version: '1.0.0', content_sha256: 'period-hash', covered_start_date: '2025-01-01', covered_end_date: '2025-06-30' },
  inventory_boundary: { status: 'partial_trial', organizational_boundary_complete: false, combined_total_available: false, reason: 'Scope 1、Scope 2 口径不同，Scope 3 尚未计算。' },
  scopes: [
    { scope: 'scope_1', status: 'quantified_partial', value: '3750', unit: 'kg CO2-Eq', label: 'Exact direct contribution', source: { period_observations: [] } },
    { scope: 'scope_2', status: 'reference_only', value: '201447', unit: 'kg CO2', label: 'Purchased electricity', source: { scenario_id: 'zhejiang-2023' } },
    { scope: 'scope_3', status: 'not_calculated', value: null, unit: null, label: 'Value chain', reason: 'missing evidence' },
  ],
  combined_total: null, issues: [], status: 'passed_with_warnings', audit: { status: 'passed_with_warnings', checks: { scope_3_not_inferred: true }, limitations: ['partial'] }, content_sha256: 'result-hash',
} as OrganizationGhgInventoryResult;

const formalBindings = [
  { binding_id: 'binding-scope-1', role: 'scope_1' },
  { binding_id: 'binding-scope-2', role: 'scope_2' },
  { binding_id: 'binding-scope-3-crude', role: 'scope_3_purchased_crude' },
  { binding_id: 'binding-scope-3-transport', role: 'scope_3_upstream_transport' },
].map((item, index) => ({
  id: `record-${index + 1}`,
  application_id: 'app-1',
  ...item,
  system_model_id: `model-${index + 1}`,
  system_revision_id: `revision-${index + 1}`,
  solved_snapshot_id: `snapshot-${index + 1}`,
  study_frame_id: 'study-frame-1',
  reporting_period_id: 'period-2025',
  organizational_boundary_id: 'boundary-1',
  demand: [{ reference_flow_uuid: 'flow-final', amount: 1, unit: 'kg' }],
  capabilities: ['product-carbon-footprint'],
  dependencies: [],
  content_sha256: `${index + 5}`.repeat(64),
  status: 'active',
  created_at: '2026-09-01T08:00:00Z',
  updated_at: '2026-09-01T08:00:00Z',
})) as SystemBinding[];

const formalResult = {
  schema_version: 'nebula_one.organization-ghg-inventory.v1',
  capability_key: 'organization.ghg-inventory.v1',
  application_id: 'app-1',
  reporting_period_id: 'period-2025',
  organizational_boundary_id: 'boundary-1',
  method_package: { reference: 'ghg.organization.formal@1.0.0', content_sha256: 'formal-method-hash' },
  comparability: { lcia_method: 'method-from-package', unit: 'kg CO2-Eq', database_release: 'EF3.1' },
  scopes: [
    { scope: 'scope_1', total: { value: 2500, unit: 'kg CO2-Eq' }, categories: [] },
    { scope: 'scope_2', total: { value: 3000, unit: 'kg CO2-Eq' }, categories: [] },
    { scope: 'scope_3', total: { value: 2000, unit: 'kg CO2-Eq' }, categories: [] },
  ],
  total: { value: 7500, unit: 'kg CO2-Eq' },
  audit: { status: 'passed', source_binding_count: 4, checks: { all_bindings_active: true } },
  content_sha256: 'formal-result-hash',
} as OrganizationGhgInventoryV1Result;

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

type PanelProps = ComponentProps<typeof OrganizationGhgInventoryPanel>;

function Panel(props: Partial<PanelProps>) {
  return <OrganizationGhgInventoryPanel applicationId="app-1" snapshots={snapshots}
    organizationMethods={[organizationMethod]} formalOrganizationMethods={[formalOrganizationMethod, otherFormalMethod]}
    pcfMethods={[pcfMethod, otherPcfMethod]} carbonMethods={[carbonMethod]} provinceMethods={[provinceMethod]}
    enabled packagesLoading={false} packagesError={null} onPackagesRetry={vi.fn()} {...props} />;
}

/** The panel reads and writes the URL, so each render needs a router plus a probe for the live query string. */
function Harness({ children }: { children: ReactNode }) {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  return <div>
    {children}
    <output data-testid="search">{searchParams.toString()}</output>
    <button onClick={() => navigate(-1)}>浏览器后退</button>
  </div>;
}

function Tree({ entry, panel, client }: { entry: string; panel: ReactNode; client: QueryClient }) {
  return <QueryClientProvider client={client}><MemoryRouter initialEntries={[entry]}><Harness>{panel}</Harness></MemoryRouter></QueryClientProvider>;
}

function renderPanel(entry: string, panel: ReactNode, client = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  return render(<Tree entry={entry} panel={panel} client={client} />);
}

function searchTerm() {
  return screen.getByTestId('search').textContent ?? '';
}

function mockTrialReads() {
  vi.spyOn(api, 'systemBindings').mockResolvedValue([]);
  vi.spyOn(api, 'periods').mockResolvedValue(periods);
  vi.spyOn(api, 'energyCarrierResults').mockImplementation(async (snapshotId) => energies.filter((item) => item.solved_snapshot_id === snapshotId));
  vi.spyOn(api, 'inventorySnapshots').mockResolvedValue(inventories);
  vi.spyOn(api, 'inventoryDataPoints').mockImplementation(async (inventoryId) => [{ id: inventoryId.replace('inventory', 'point'), inventory_snapshot_id: inventoryId, metric_key: 'period_product_output', quantity: 100, unit: 'kg', quality_status: 'valid', review_status: 'approved', mapping_target: { role: 'period_product_output' } } as never]);
  vi.spyOn(api, 'organizationGhgInventory').mockResolvedValue(result);
  vi.spyOn(api, 'organizationGhgInventoryChart').mockResolvedValue(new Blob(['<svg />'], { type: 'image/svg+xml' }));
}

function mockFormalReads() {
  vi.spyOn(api, 'systemBindings').mockResolvedValue(formalBindings);
  vi.spyOn(api, 'organizationGhgInventoryV1').mockResolvedValue(formalResult);
  vi.spyOn(api, 'organizationGhgInventoryV1Chart').mockResolvedValue(new Blob(['<svg />'], { type: 'image/svg+xml' }));
}

describe('organization GHG inventory panel', () => {
  it('keeps a chart failure visible and retries the chart independently', async () => {
    mockFormalReads();
    vi.mocked(api.organizationGhgInventoryV1Chart).mockRejectedValueOnce(new Error('Chart unavailable'));
    renderPanel('/applications/app-1/results?view=organization-ghg', <Panel />);
    expect(await screen.findByText('Chart unavailable')).toBeInTheDocument();
    expect(screen.getByText('7,500')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '重新加载' }));
    await waitFor(() => expect(screen.queryByText('Chart unavailable')).not.toBeInTheDocument());
    expect(api.organizationGhgInventoryV1Chart).toHaveBeenCalledTimes(2);
    expect(api.organizationGhgInventoryV1).toHaveBeenCalledTimes(1);
  });

  it('does not aggregate a subset when one reporting period lacks evidence', async () => {
    mockTrialReads();
    vi.mocked(api.periods).mockResolvedValue([...periods, { ...periods[1], id: 'period-q3', name: '2025 Q3', start_date: '2025-07-01', end_date: '2025-09-30' }]);
    renderPanel('/applications/app-1/results?view=organization-ghg&ghg-tab=trial', <Panel />);
    expect(await screen.findByText('期间证据尚未就绪')).toBeInTheDocument();
    expect(api.organizationGhgInventory).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: '生成组织清单' })).toBeDisabled();
  });

  it('names the missing dependency of a refused trial run without inventing a value', async () => {
    mockTrialReads();
    vi.mocked(api.organizationGhgInventory).mockRejectedValue(new ApiError(
      'direct energy requires an exact TIDAS Flow receipt',
      422,
      'ENERGY_CARRIER_FLOW_NOT_EXACT',
      {
        exchange_id: 'ammonia-auxiliary-boiler::grid-electricity-in',
        dependency_gap: {
          schema_version: 'nebula_one.dependency-gap.v1',
          code: 'ENERGY_CARRIER_FLOW_NOT_EXACT',
          what_missing: {
            kind: 'tidas_exact_flow_snapshot',
            exchange_id: 'ammonia-auxiliary-boiler::grid-electricity-in',
            observed_resolution: 'inline_custom',
            identity: { source_namespace: 'nebula.standard-lca-seed', flow_uuid: '222665f3-76a4-5894-a34a-27107e793f08', version: '1.3.0' },
            required_identity: { resolution: 'tidas_exact_snapshot', source_namespace: 'tiangong_open_data' },
          },
          affects: {
            step: 'energy_carrier',
            downstream_steps: ['carbon_management', 'organization_ghg_inventory'],
            scopes_affected: ['scope_1', 'scope_2'],
            results_produced: false,
          },
          how_to_resolve: [{
            action: '为该能量端口配置精确 TIDAS Flow 快照，使求解回执的 resolution 成为 tidas_exact_snapshot',
            owner: '上游引擎与目录数据',
            precondition: '端口 ammonia-auxiliary-boiler::grid-electricity-in 的流身份可在目录中解析为唯一版本',
          }],
          evidence: { solved_snapshot_id: 'snapshot-q1' },
        },
      },
    ));
    renderPanel('/applications/app-1/results?view=organization-ghg&ghg-tab=trial', <Panel />);

    const notice = await screen.findByRole('note', { name: '缺数据说明' });
    expect(within(notice).getByText(/tidas_exact_flow_snapshot/)).toBeInTheDocument();
    expect(within(notice).getByText(/inline_custom/)).toBeInTheDocument();
    expect(within(notice).getByText(/为该能量端口配置精确 TIDAS Flow 快照/)).toBeInTheDocument();
    expect(within(notice).getByText(/本次没有产出任何结果/)).toBeInTheDocument();
    // the evidence that does exist stays on screen while the gap is reported
    expect((await screen.findAllByText('2025 Q1')).length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: '重新加载' })).toBeInTheDocument();
  });

  it('does not substitute suggested energy results for a malformed URL binding', async () => {
    mockTrialReads();
    renderPanel('/applications/app-1/results?view=organization-ghg&ghg-tab=trial&ghg-trial-energy=period-q1:', <Panel />);
    expect(await screen.findByText('链接指定的引用无法使用')).toBeInTheDocument();
    expect(api.organizationGhgInventory).not.toHaveBeenCalled();
  });

  it('derives scenario choices and exact period bindings from versioned records', () => {
    expect(provinceScenarios(provinceMethod)).toEqual([{ id: 'zhejiang-2023', label: 'Zhejiang' }, { id: 'guizhou-2024', label: 'Guizhou' }]);
    expect(suggestPeriodBindings(periods, energies, snapshots, inventories)).toEqual({ 'period-q1': 'energy-q1', 'period-q2': 'energy-q2' });
    expect(classifyBindingRole('scope_3_upstream_transport', formalOrganizationMethod)).toEqual({ scope: 'scope_3', category: 'upstream_transport' });
  });

  it('aggregates four active bindings with the formal versioned contract', async () => {
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:formal-organization-chart') });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
    mockFormalReads();
    const run = vi.mocked(api.organizationGhgInventoryV1);

    renderPanel('/applications/app-1/results?view=organization-ghg&snapshot=snapshot-q1', <Panel />);

    expect((await screen.findAllByText('活动系统名称未提供')).length).toBe(4);
    expect(screen.getByText('upstream_transport')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText('7,500')).toBeInTheDocument());
    expect(run).toHaveBeenCalledTimes(1);
    expect(run).toHaveBeenCalledWith('app-1', {
      method_package_ref: 'ghg.organization.formal@1.0.0',
      pcf_method_package_ref: 'pcf.product@1.0.0',
      binding_ids: formalBindings.map((item) => item.binding_id).sort(),
    });
    expect(screen.getByText('4 个活动系统')).toBeInTheDocument();
    expect(await screen.findByRole('img', { name: '组织温室气体清单聚合图' })).toHaveAttribute('src', 'blob:formal-organization-chart');

    await userEvent.click(screen.getByRole('button', { name: '执行聚合' }));
    await waitFor(() => expect(run).toHaveBeenCalledTimes(2));

    await userEvent.click(screen.getByRole('button', { name: '清单审计' }));
    expect(await screen.findByText('formal-result-hash')).toBeInTheDocument();
    expect(screen.getByText('formal-method-hash')).toBeInTheDocument();
  });

  it('restores a deep-linked formal method pair and runs the read-only aggregation once', async () => {
    mockFormalReads();
    const run = vi.spyOn(api, 'organizationGhgInventoryV1');
    renderPanel('/applications/app-1/results?view=organization-ghg&snapshot=snapshot-q1&ghg-tab=formal&ghg-method=ghg.organization.formal.alt@1.0.0&ghg-pcf=pcf.product.alt@1.0.0', <Panel />);

    await waitFor(() => expect(run).toHaveBeenCalledTimes(1));
    expect(run).toHaveBeenCalledWith('app-1', expect.objectContaining({
      method_package_ref: 'ghg.organization.formal.alt@1.0.0',
      pcf_method_package_ref: 'pcf.product.alt@1.0.0',
    }));
    expect(screen.getByText('ghg.organization.formal.alt · 1.0.0')).toBeInTheDocument();
    expect(screen.getByText('pcf.product.alt · 1.0.0')).toBeInTheDocument();
  });

  it('rejects a formal method package the application does not bind, then recovers after clearing', async () => {
    mockFormalReads();
    const run = vi.spyOn(api, 'organizationGhgInventoryV1');
    renderPanel('/applications/app-1/results?view=organization-ghg&ghg-method=ghg.organization.formal@9.9.9', <Panel />);

    expect(await screen.findByText('链接指定的引用无法使用')).toBeInTheDocument();
    expect(screen.getByText('组织清单方法包「ghg.organization.formal@9.9.9」不属于当前对象或已不存在。 未使用其它方法包替代链接中的引用。')).toBeInTheDocument();
    expect(run).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole('button', { name: '清除并重新选择' }));
    await waitFor(() => expect(run).toHaveBeenCalledTimes(1));
    expect(vi.mocked(api.organizationGhgInventoryV1).mock.calls[0][1]).toMatchObject({ method_package_ref: 'ghg.organization.formal@1.0.0' });
    expect(searchTerm()).toBe('view=organization-ghg');
  });

  it('refuses an unknown inventory view without touching either contract', async () => {
    mockFormalReads();
    const trial = vi.spyOn(api, 'organizationGhgInventory').mockResolvedValue(result);
    renderPanel('/applications/app-1/results?view=organization-ghg&ghg-tab=production', <Panel />);

    expect(await screen.findByText(/清单视图「production」不属于当前对象或已不存在/)).toBeInTheDocument();
    expect(api.organizationGhgInventoryV1).not.toHaveBeenCalled();
    expect(trial).not.toHaveBeenCalled();
  });

  it('walks back and forward between the formal and trial views', async () => {
    mockFormalReads();
    vi.spyOn(api, 'periods').mockResolvedValue([]);
    vi.spyOn(api, 'inventorySnapshots').mockResolvedValue([]);
    renderPanel('/applications/app-1/results?view=organization-ghg', <Panel snapshots={[]} />);
    expect((await screen.findAllByText('活动系统名称未提供')).length).toBe(4);

    await userEvent.click(screen.getByRole('tab', { name: '兼容试算' }));
    expect(await screen.findByText(/至少需要两个报告期及其冻结能源结果/)).toBeInTheDocument();
    expect(screen.getByText(/当前报告期 0 个，冻结能源结果 0 份/)).toBeInTheDocument();
    expect(searchTerm()).toBe('view=organization-ghg&ghg-tab=trial');

    await userEvent.click(screen.getByRole('button', { name: '浏览器后退' }));
    await waitFor(() => expect(screen.getByText('7,500')).toBeInTheDocument());
    expect(searchTerm()).toBe('view=organization-ghg');
  });

  it('shows the formal empty state while keeping the compatibility trial available', async () => {
    vi.spyOn(api, 'systemBindings').mockResolvedValue([]);
    vi.spyOn(api, 'periods').mockResolvedValue([]);
    vi.spyOn(api, 'inventorySnapshots').mockResolvedValue([]);

    renderPanel('/applications/app-1/results?view=organization-ghg', <Panel snapshots={[]} />);

    expect(await screen.findByText('当前应用没有 active System Binding，正式组织清单暂不可执行。')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('tab', { name: '兼容试算' }));
    expect(await screen.findByText(/至少需要两个报告期及其冻结能源结果/)).toBeInTheDocument();
    expect(screen.getByText(/当前报告期 0 个，冻结能源结果 0 份/)).toBeInTheDocument();
  });

  it('runs one real-contract request, renders all scopes and exposes audit hashes', async () => {
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:organization-chart') });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
    mockTrialReads();
    const run = vi.mocked(api.organizationGhgInventory);

    renderPanel('/applications/app-1/results?view=organization-ghg&ghg-tab=trial', <Panel />);

    expect(await screen.findByText('3,750')).toBeInTheDocument();
    expect(screen.getByText('201,447')).toBeInTheDocument();
    expect(screen.getAllByText('未计算')).toHaveLength(2);
    expect(screen.getByText('部分量化')).toBeInTheDocument();
    expect(screen.getByText('参考值')).toBeInTheDocument();
    await waitFor(() => expect(run).toHaveBeenCalledTimes(1));
    expect(run).toHaveBeenCalledWith('app-1', {
      method_package_ref: 'ghg.organization.partial-trial@1.0.0',
      carbon_method_package_ref: 'carbon.management.period@1.0.0',
      province_electricity: {
        method_package_ref: 'electricity.province@1.0.0',
        period_energy_total: {
          baseline_period_id: 'period-q1',
          observations: [
            { period_id: 'period-q1', energy_result_id: 'energy-q1', inventory_snapshot_id: 'inventory-q1', production_data_point_id: 'point-q1' },
            { period_id: 'period-q2', energy_result_id: 'energy-q2', inventory_snapshot_id: 'inventory-q2', production_data_point_id: 'point-q2' },
          ],
        },
      },
      scope_2_scenario_id: 'zhejiang-2023',
    });
    expect(await screen.findByRole('img', { name: '组织温室气体清单试算图' })).toHaveAttribute('src', 'blob:organization-chart');
    await userEvent.click(screen.getByRole('button', { name: '清单审计' }));
    expect(await screen.findByText('result-hash')).toBeInTheDocument();
    expect(screen.getByText('period-total-hash')).toBeInTheDocument();
  });

  it('holds linked trial choices pending while catalogs load, then runs the trial once', async () => {
    mockTrialReads();
    const run = vi.mocked(api.organizationGhgInventory);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const entry = '/applications/app-1/results?view=organization-ghg&ghg-tab=trial&ghg-trial-scenario=guizhou-2024&ghg-trial-energy=period-q1:energy-q1;period-q2:energy-q2';

    const { rerender } = renderPanel(entry, <Panel packagesLoading />, client);
    expect(await screen.findByLabelText('正在加载')).toBeInTheDocument();
    expect(run).not.toHaveBeenCalled();
    expect(decodeURIComponent(searchTerm())).toContain('ghg-trial-scenario=guizhou-2024');

    rerender(<Tree entry={entry} panel={<Panel />} client={client} />);
    expect(await screen.findByText('3,750')).toBeInTheDocument();
    await waitFor(() => expect(run).toHaveBeenCalledTimes(1));
    expect(run).toHaveBeenCalledWith('app-1', expect.objectContaining({ scope_2_scenario_id: 'guizhou-2024' }));
  });

  it('refuses a period binding that points at another application result', async () => {
    mockTrialReads();
    const run = vi.spyOn(api, 'organizationGhgInventory');
    renderPanel('/applications/app-1/results?view=organization-ghg&ghg-tab=trial&ghg-trial-energy=period-q1:energy-of-other-app', <Panel />);

    expect(await screen.findByText(/2025 Q1的冻结能源结果「energy-of-other-app」不属于当前对象或已不存在/)).toBeInTheDocument();
    expect(run).not.toHaveBeenCalled();
    expect(screen.queryByText('3,750')).not.toBeInTheDocument();
  });
});
