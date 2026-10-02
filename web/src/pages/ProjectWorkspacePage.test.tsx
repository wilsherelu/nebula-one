import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, expect, it, vi } from 'vitest';
import { api } from '../api/client';
import { seedProjectsApi } from '../api/seedProjects';
import type { Application, BackgroundProcessPin, MappedBackgroundProcessPin, MethodPackage, ProjectWorkspace, SolvedSystemSnapshot, SystemModel, SystemRevision } from '../api/types';
import { ProjectWorkspacePage } from './ProjectWorkspacePage';
import { ProjectHistoryPage } from './ProjectHistoryPage';

const application: Application = {
  id: 'app-steel', name: '钢铁 BF-BOF 粗钢', application_type: 'system_analysis', description: null,
  context: { template_locked: true, method_package_refs: [] }, status: 'active',
  created_at: '2026-09-22T00:00:00Z', updated_at: '2026-09-22T00:00:00Z',
};
const model: SystemModel = {
  id: 'model-1', application_id: 'app-steel', name: '钢铁模型', provider: 'nebula_lca',
  provider_base_url: 'http://127.0.0.1:18023', upstream_project_id: 'up-1', upstream_version: 3,
  graph_sha256: 'g'.repeat(64), upstream_receipt: {}, created_at: '2026-09-22T00:00:00Z',
};
const revision: SystemRevision = {
  id: 'r2', system_model_id: 'model-1', parent_revision_id: null, revision_number: 2, label: null,
  revision_kind: 'data', graph_sha256: 'g'.repeat(64), content_sha256: 'c'.repeat(64), status: 'active',
  created_at: '2026-09-22T00:00:00Z', published_at: null,
};
const workspace: ProjectWorkspace = {
  application_id: 'app-steel', revision_id: 'r2', content_sha256: 'c'.repeat(64), template_title: '钢铁 BF-BOF 粗钢',
  fields: [
    { key: 'power', label: '电力', process: '炼钢', process_id: 'p-steelmaking', port_id: 'e1', group: 'inputs', flow_type: 'technosphere', value: 50, unit: 'MJ' },
    { key: 'crude', label: '粗钢', process: '炼钢', process_id: 'p-steelmaking', port_id: 'e2', group: 'outputs', flow_type: 'technosphere', value: 1, unit: 'kg', reference_product: true },
    { key: 'sinter', label: '烧结矿', process: '烧结', process_id: 'p-sintering', port_id: 'e3', group: 'inputs', flow_type: 'technosphere', value: 1.6, unit: 'kg' },
  ],
  inventory_editing: true,
  demand: [{ reference_flow_uuid: 'steel', amount: 1000, unit: 'kg' }],
  source: '生产台账', saved: true, capabilities: ['mfa.solved.v1'], blocked_capabilities: [],
  background_options: [], background_note: '',
  background_ports: [{ exchange_id: 'p-steelmaking::e1', process: '炼钢', label: '电力', unit: 'MJ', flow_uuid: 'power', version: '01.00.000', source_namespace: 'tiangong_open_data', exact_binding_supported: true }],
};

const bound: ProjectWorkspace = { ...workspace, revision_id: 'r3', content_sha256: 'd'.repeat(64) };
const revision3: SystemRevision = {
  ...revision, id: 'r3', parent_revision_id: 'r2', revision_number: 3, content_sha256: 'd'.repeat(64),
};

// The template's own capabilities never imply the climate task: it appears with the mapped provider.
const mappedPin: MappedBackgroundProcessPin = {
  schema_version: 'provider.mapped-background-process-pin.v1', consumer_exchange_id: 'p-steelmaking::e1',
  source_flow_namespace: 'tiangong_open_data', source_flow_uuid: 'power', source_flow_version: '01.00.000',
  target_flow_uuid: 'mapped-power', source_unit: 'MJ', target_unit: 'kWh', amount_factor: 1 / 3.6,
  mapping_level: 'L2', mapping_status: 'user_confirmed', mapping_rule_id: 'power-rule',
  mapping_package_id: 'test-mapping', mapping_package_version: '1.0.0', mapping_package_hash: 'a'.repeat(64),
  database_release: 'synthetic', process_uuid: 'provider', expected_process_content_hash: 'b'.repeat(64),
  expected_vector_checksum: 'd'.repeat(64), claim_role: 'partial_background_leaf',
};
const climateWorkspace: ProjectWorkspace = { ...workspace, mapped_background_process_pins: [mappedPin], native_climate: { available: true, provider_count: 1 }, native_inventory: { available: true, provider_count: 1 } };
const climateSnapshot: SolvedSystemSnapshot = {
  id: 'snap-climate', application_id: 'app-steel', system_revision_id: 'r2', inventory_snapshot_id: null, parameter_set_id: null,
  solve_hash: 'solve-1', provider: 'nebula_lca', provider_receipt: {}, functional_unit: { amount: 1, unit: 'kg' },
  database_release: 'ecoinvent_3.11', solver_version: 'provider-v1', activity_vector: [], scaled_technosphere_exchanges: [],
  scaled_elementary_exchanges: [], internal_transfers: [], boundary_flows: [], process_balance_residuals: [],
  contribution_graph: {}, lcia_results: {}, native_background_climate: {
    schema_version: 'nebula_one.native-background-climate.v1',
    source_contract: { repository: 'nebula-lca', commit: '2c3ebd7e72be644db47e1f9049417aa1cf8bf6d3', document: 'docs/PROVIDER_NATIVE_CLIMATE_TOTAL_V1.md', document_sha256: 'd'.repeat(64) },
    request: { schema_version: 'provider.native-background-climate-total.request.v1', database_release: 'ecoinvent_3.11', method_package_id: 'p', method_package_version: '1.0.0', method_package_sha256: 'f'.repeat(64), runtime_manifest_sha256: 'e'.repeat(64), flow_snapshot_hash: 'a'.repeat(64), reference_dependency_snapshot_hash: 'b'.repeat(64) },
    response: { schema_version: 'provider.native-background-climate-total.response.v1', method_package_id: 'p', method_package_version: '1.0.0', method_package_sha256: 'f'.repeat(64), runtime_manifest_sha256: 'e'.repeat(64), indicator: { method: 'EF v3.1', category: 'climate change', name: 'GWP100', unit: 'kg CO2-Eq' }, merge_status: 'merged', merge_blockers: [], unified_climate_total: 2.0883914, domains: {}, provider_system_model_evidence: 'not_asserted_by_local_vector_metadata', carbon_storage_permanence: 'not_assessed', claim_limit: 'partial' },
  },
  content_sha256: 'content-1', created_at: '2026-09-23T00:00:00Z',
};
const organizationMethod: MethodPackage = { id: 'org-method', package_id: 'org.steel', version: '1.0.5', package_kind: 'organization_lifecycle_carbon',
  jurisdiction: null, valid_from: null, valid_to: null, status: 'active', created_at: '2026-09-23T00:00:00Z', content_sha256: 'f'.repeat(64),
  manifest: { classification_rules: { energy_path_source: 'project_background_process_receipts' },
    formula_graph: { lcia_method: 'EF v3.1', total_indicator_key: 'climate change|gwp100' } } };

function mountClimate(workspaceData: ProjectWorkspace, options: { app?: Application; snapshots?: SolvedSystemSnapshot[]; packages?: MethodPackage[] } = {}) {
  vi.spyOn(api, 'application').mockResolvedValue(options.app ?? application);
  vi.spyOn(api, 'models').mockResolvedValue([model]);
  vi.spyOn(api, 'revisions').mockResolvedValue([revision]);
  vi.spyOn(api, 'workspace').mockResolvedValue(workspaceData);
  vi.spyOn(api, 'methodPackages').mockResolvedValue(options.packages ?? []);
  vi.spyOn(api, 'solvedSnapshots').mockResolvedValue(options.snapshots ?? [climateSnapshot]);
  vi.spyOn(api, 'organizationLifecycleInventories').mockResolvedValue([]);
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>
    <MemoryRouter initialEntries={['/applications/app-steel/workbench?step=reports']}>
      <Routes><Route path="/applications/:applicationId/workbench" element={<ProjectWorkspacePage />} /><Route path="/applications/:applicationId/history" element={<ProjectHistoryPage />} /></Routes>
    </MemoryRouter>
  </QueryClientProvider>);
}

function mount(step = 'data', revisions: SystemRevision[] = [revision], revisionParam = '') {
  vi.spyOn(api, 'application').mockResolvedValue(application);
  vi.spyOn(api, 'models').mockResolvedValue([model]);
  vi.spyOn(api, 'revisions').mockResolvedValue(revisions);
  vi.spyOn(api, 'workspace').mockImplementation((_applicationId, revisionId) =>
    Promise.resolve(revisionId === 'r3' ? bound : workspace));
  vi.spyOn(api, 'methodPackages').mockResolvedValue([]);
  vi.spyOn(api, 'solvedSnapshots').mockResolvedValue([]);
  vi.spyOn(api, 'organizationLifecycleInventories').mockResolvedValue([]);
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>
    <MemoryRouter initialEntries={[`/applications/app-steel/workbench?step=${step}${revisionParam}`]}>
      <Routes><Route path="/applications/:applicationId/workbench" element={<ProjectWorkspacePage />} /><Route path="/applications/:applicationId/history" element={<ProjectHistoryPage />} /></Routes>
    </MemoryRouter>
  </QueryClientProvider>);
}
afterEach(() => { cleanup(); vi.restoreAllMocks(); localStorage.clear(); });

it('opens process data as the primary project entry', async () => {
  mount();
  expect(await screen.findByRole('button', { name: '核算' })).toBeInTheDocument();
  expect(screen.queryByRole('tab', { name: '工艺与数据' })).not.toBeInTheDocument();
  expect(screen.getByRole('spinbutton', { name: '炼钢 / 电力' })).toBeInTheDocument();
  expect(screen.queryByText('该过程不属于当前模板，请重新选择。')).toBeNull();
});

it('retries a failed workspace load instead of leaving the operator stuck', async () => {
  vi.spyOn(api, 'application').mockResolvedValue(application);
  vi.spyOn(api, 'models').mockResolvedValue([model]);
  vi.spyOn(api, 'revisions').mockResolvedValue([revision]);
  let reachable = false;
  const load = vi.spyOn(api, 'workspace').mockImplementation(() => reachable ? Promise.resolve(workspace) : Promise.reject(new Error('数据版本暂时读不到')));
  vi.spyOn(api, 'methodPackages').mockResolvedValue([]);
  vi.spyOn(api, 'solvedSnapshots').mockResolvedValue([]);
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>
    <MemoryRouter initialEntries={['/applications/app-steel/workbench']}>
      <Routes><Route path="/applications/:applicationId/workbench" element={<ProjectWorkspacePage />} /></Routes>
    </MemoryRouter>
  </QueryClientProvider>);
  expect(await screen.findByText('数据版本暂时读不到')).toBeInTheDocument();
  expect(load).toHaveBeenCalledOnce();
  reachable = true;
  fireEvent.click(screen.getByRole('button', { name: '重新加载' }));
  expect(await screen.findByRole('button', { name: '核算' })).toBeInTheDocument();
  expect(await screen.findByRole('spinbutton', { name: '核算规模 1' })).toHaveValue('1000');
});

const electricityPin: BackgroundProcessPin = {
  schema_version: 'provider.background-process-pin.v1', consumer_exchange_id: 'p-steelmaking::e1',
  source_namespace: 'tiangong_open_data', process_uuid: 'p-1', version: '01.00.000',
  expected_process_content_hash: 'a'.repeat(64), expected_process_snapshot_hash: 'b'.repeat(64),
  quantitative_reference_exchange_internal_id: '0', claim_role: 'partial_background_leaf',
};

it('keeps unsaved inventory edits when a background binding mints the next data version', async () => {

  vi.spyOn(seedProjectsApi, 'resolveBackground').mockResolvedValue({ pin: electricityPin, name: '同源电力' });
  const save = vi.spyOn(api, 'saveProjectInputs').mockResolvedValue(bound);
  mount('data', [revision, revision3], '&revision=r2');
  fireEvent.change(await screen.findByRole('spinbutton', { name: '炼钢 / 电力' }), { target: { value: '600' } });
  await userEvent.click(screen.getByRole('button', { name: '选择背景数据' }));
  await userEvent.click(await screen.findByRole('combobox', { name: '背景来源' }));
  fireEvent.click(await screen.findByRole('option', { name: '精确引用' }));
  fireEvent.change(await screen.findByRole('textbox', { name: '背景过程 UUID' }), { target: { value: 'p-1' } });
  fireEvent.change(screen.getByRole('textbox', { name: '数据版本' }), { target: { value: '01.00.000' } });
  fireEvent.click(screen.getByRole('button', { name: '校验背景数据' }));
  await waitFor(() => expect(screen.getByRole('button', { name: '确认关联' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: '确认关联' }));
  await waitFor(() => expect(save).toHaveBeenCalledWith('app-steel', expect.objectContaining({ revision_id: 'r2' }), 'zh'));
  // The binding really did move the workbench to the next version; the edits have to survive that.
  await waitFor(() => expect(api.workspace).toHaveBeenCalledWith('app-steel', 'r3', 'zh'));
  expect(await screen.findByRole('spinbutton', { name: '炼钢 / 电力' })).toHaveValue('600');
});

it('asks before switching versions with an unsaved draft and keeps it scoped to the original version', async () => {
  mount('data', [revision, revision3], '&revision=r2');
  fireEvent.change(await screen.findByRole('spinbutton', { name: '炼钢 / 电力' }), { target: { value: '600' } });
  await userEvent.click(screen.getByRole('combobox', { name: '当前数据版本' }));
  fireEvent.click(await screen.findByRole('option', { name: /版本 3/ }));
  // The switch is refused until the operator chooses; the version bar still reads the current one.
  expect(await screen.findByText(/尚未保存的填报修改/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: '保留草稿并切换' }));
  await waitFor(() => expect(api.workspace).toHaveBeenCalledWith('app-steel', 'r3', 'zh'));
  // The kept draft stays under r2's own scope, not r3's.
  expect(JSON.parse(localStorage.getItem('nebula-one:project:app-steel:r2')!)).toEqual(expect.objectContaining({ amounts: [1000] }));
  expect(localStorage.getItem('nebula-one:project:app-steel:r3')).toBeNull();
  // Returning to r2 restores the unsaved edit.
  await userEvent.click(screen.getByRole('combobox', { name: '当前数据版本' }));
  fireEvent.click(await screen.findByRole('option', { name: /版本 2/ }));
  expect(await screen.findByRole('spinbutton', { name: '炼钢 / 电力' })).toHaveValue('600');
});

it('discards the draft when the operator chooses to abandon it on a version switch', async () => {
  mount('data', [revision, revision3], '&revision=r2');
  fireEvent.change(await screen.findByRole('spinbutton', { name: '炼钢 / 电力' }), { target: { value: '600' } });
  await userEvent.click(screen.getByRole('combobox', { name: '当前数据版本' }));
  fireEvent.click(await screen.findByRole('option', { name: /版本 3/ }));
  expect(await screen.findByText(/尚未保存的填报修改/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: '放弃草稿' }));
  await waitFor(() => expect(api.workspace).toHaveBeenCalledWith('app-steel', 'r3', 'zh'));
  expect(localStorage.getItem('nebula-one:project:app-steel:r2')).toBeNull();
});

it('saves an edited inventory before solving against the returned exact revision', async () => {
  const save = vi.spyOn(api, 'saveProjectInputs').mockResolvedValue(bound);
  const solve = vi.spyOn(api, 'solveAndFreeze').mockResolvedValue({ ...climateSnapshot, system_revision_id: 'r3' });
  mount('data', [revision, revision3], '&revision=r2');
  fireEvent.change(await screen.findByRole('spinbutton', { name: '炼钢 / 电力' }), { target: { value: '600' } });
  fireEvent.click(screen.getByRole('button', { name: '核算' }));
  fireEvent.click(screen.getByRole('button', { name: '保存并计算' }));
  await waitFor(() => expect(save).toHaveBeenCalledOnce());
  await waitFor(() => expect(solve).toHaveBeenCalledOnce());
  expect(solve.mock.calls[0][1]).toBe('r3');
  expect(solve.mock.calls[0][2].idempotency_key).toContain(`r3:${'d'.repeat(64)}`);
});

it('keeps a failed save as a draft and never starts a solve', async () => {
  vi.spyOn(api, 'saveProjectInputs').mockRejectedValue(new Error('保存失败'));
  const solve = vi.spyOn(api, 'solveAndFreeze');
  mount();
  fireEvent.change(await screen.findByRole('spinbutton', { name: '炼钢 / 电力' }), { target: { value: '600' } });
  fireEvent.click(screen.getByRole('button', { name: '核算' }));
  fireEvent.click(screen.getByRole('button', { name: '保存并计算' }));
  expect((await screen.findAllByText('保存失败')).length).toBeGreaterThan(0);
  expect(solve).not.toHaveBeenCalled();
  expect(localStorage.getItem('nebula-one:project:app-steel:r2')).toContain('600');
});

it('offers the four peer tasks without a separate covered-range LCA or partial-climate button', async () => {
  mountClimate(climateWorkspace);
  fireEvent.click(await screen.findByRole('button', { name: '核算' }));
  expect(await screen.findByText('选择核算方法')).toBeInTheDocument();
  // The standalone covered-range LCA and partial-background climate tasks folded into the four
  // release tasks; a distinct climate button no longer competes with the product footprint task.
  expect(screen.queryByRole('button', { name: '计算部分背景下的气候变化结果' })).toBeNull();
  expect(screen.queryByRole('button', { name: '计算已覆盖范围 LCA' })).toBeNull();
});

it('requests the server-pinned EF climate default for PCF without choosing a catalog item', async () => {
  const solve = vi.spyOn(api, 'solveAndFreeze').mockResolvedValue(climateSnapshot);
  mountClimate({ ...workspace, capabilities: ['mfa.solved.v1', 'pcf.product.v1'] });
  fireEvent.click(await screen.findByRole('button', { name: '核算' }));
  fireEvent.click(screen.getByRole('button', { name: '开始计算' }));
  await waitFor(() => expect(solve).toHaveBeenCalledOnce());
  const payload = solve.mock.calls[0][2];
  expect(payload.climate_default).toBe(true);
  expect(payload.lcia_methods).toBeUndefined();
  expect(payload.native_background_climate).toBeUndefined();
  expect(payload.idempotency_key).toBe(`calc-v2-pcf:r2:${'c'.repeat(64)}`);
});

it('uses a new idempotency key when an operator retries a failed solve on the same revision', async () => {
  const solve = vi.spyOn(api, 'solveAndFreeze').mockRejectedValueOnce(new Error('上游计算暂时失败'))
    .mockResolvedValueOnce(climateSnapshot);
  mountClimate({ ...workspace, capabilities: ['mfa.solved.v1', 'pcf.product.v1'] });
  fireEvent.click(await screen.findByRole('button', { name: '核算' }));
  const button = screen.getByRole('button', { name: '开始计算' });
  fireEvent.click(button);
  expect(await screen.findByText('上游计算暂时失败')).toBeInTheDocument();
  fireEvent.click(button);
  await waitFor(() => expect(solve).toHaveBeenCalledTimes(2));
  const base = `calc-v2-pcf:r2:${'c'.repeat(64)}`;
  expect(solve.mock.calls.map(call => call[2].idempotency_key)).toEqual([base, `${base}:retry-1`]);
});

it('uses the method-independent native inventory for mapped-background MFA', async () => {
  const solve = vi.spyOn(api, 'solveAndFreeze').mockResolvedValue(climateSnapshot);
  mountClimate(climateWorkspace);
  fireEvent.click(await screen.findByRole('button', { name: '核算' }));
  fireEvent.click(screen.getByRole('button', { name: '开始计算' }));
  await waitFor(() => expect(solve).toHaveBeenCalledOnce());
  expect(solve.mock.calls[0][2].idempotency_key).toBe(`calc-v2-mfa:r2:${'c'.repeat(64)}`);
  expect(solve.mock.calls[0][2].native_background_inventory).toBe(true);
  expect(solve.mock.calls[0][2].native_background_climate).toBeUndefined();
});

it('offers no standalone climate task when the mapped provider cannot resolve one', async () => {
  mountClimate({ ...workspace, native_climate: { available: false, provider_count: 2 } });
  fireEvent.click(await screen.findByRole('button', { name: '核算' }));
  expect(await screen.findByText('选择核算方法')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /部分背景下的气候变化结果/ })).toBeNull();
});

it('opens a saved climate snapshot from the independent history page', async () => {
  mountClimate(workspace);
  await userEvent.click(await screen.findByRole('link', { name: '历史结果' }));
  expect(await screen.findByRole('link', { name: /产品碳足迹/ })).toHaveAttribute('href', expect.stringContaining('snapshot=snap-climate&view=pcf'));
  expect(screen.queryByRole('button', { name: /部分背景下的气候变化结果/ })).toBeNull();
});

it('links saved task records back to their own result views', async () => {
  const app: Application = { ...application, context: { ...application.context, method_package_refs: ['org.steel@1.0.5'] } };
  const pcf: SolvedSystemSnapshot = { ...climateSnapshot, id: 'snap-pcf', native_background_climate: null,
    provider_receipt: { calculation_basis: { calculation_method: { reference: 'pcf.product.ef31.foreground@1.0.1', content_sha256: 'a'.repeat(64) } },
      project_background_process_receipts: [{ consumer_exchange_id: 'casting::electricity' }] } };
  const cbam: SolvedSystemSnapshot = { ...climateSnapshot, id: 'snap-cbam', native_background_climate: null,
    provider_receipt: { calculation_basis: { model_derivation: { purpose: 'cbam' } } } };
  const org: SolvedSystemSnapshot = { ...climateSnapshot, id: 'snap-org', native_background_climate: null,
    provider_receipt: { calculation_basis: { model_derivation: { purpose: 'lca' }, calculation_method: { reference: 'pcf.product.ef31.foreground@1.0.1', content_sha256: 'a'.repeat(64) } },
      project_background_process_receipts: [{ consumer_exchange_id: 'casting::electricity' }] } };
  mountClimate({ ...workspace, capabilities: ['mfa.solved.v1', 'pcf.product.v1', 'cbam.trial.v2', 'organization.lifecycle-carbon.v1'] },
    { app, packages: [organizationMethod], snapshots: [{ ...climateSnapshot, id: 'snap-mfa', native_background_climate: null }, pcf, cbam, org] });
  await userEvent.click(await screen.findByRole('link', { name: '历史结果' }));
  for (const [id, view] of [['snap-mfa', 'mfa'], ['snap-pcf', 'pcf'], ['snap-cbam', 'cbam'], ['snap-org', 'pcf']]) {
    await waitFor(() => expect(screen.getAllByRole('link', { name: new RegExp(view === 'mfa' ? '物质流分析' : view === 'pcf' ? '产品碳足迹' : 'CBAM 试算') })
      .some(link => link.getAttribute('href')?.includes(`snapshot=${id}&view=${view}`))).toBe(true));
  }
});

it('computes organization lifecycle directly without requiring an earlier PCF snapshot', async () => {
  const app: Application = { ...application, context: { ...application.context, seed_template: {}, method_package_refs: ['org.steel@1.0.5'] } };
  const organizationWorkspace: ProjectWorkspace = { ...workspace, capabilities: ['organization.lifecycle-carbon.v1'],
    project_background_pins: [{ schema_version: 'provider.project-background-pin.v1',
      consumer_exchange_id: 'p-steelmaking::e1', project_id: 'electricity-supply', version: 1,
      expected_graph_hash: 'a'.repeat(64), source_node_id: 'grid', reference_port_id: 'electricity-out',
      provider_amount_per_consumer_unit: 1, claim_role: 'user_declared_partial_background_leaf' }] };
  const wrongRevision: SolvedSystemSnapshot = { ...climateSnapshot, id: 'snap-wrong-revision', system_revision_id: 'r3',
    provider_receipt: { project_background_process_receipts: [{ id: 'supply' }] } };
  const eligible: SolvedSystemSnapshot = { ...climateSnapshot, id: 'snap-supply', native_background_climate: null,
    provider_receipt: { project_background_process_receipts: [{ id: 'supply' }] },
    lcia_results: { method: 'EF v3.1', indicator_contribution_receipts: [{ canonical_indicator_key: 'climate change|gwp100' }] } };
  const laterMfa = { ...eligible, id: 'snap-mfa', lcia_results: {} };
  const solve = vi.spyOn(api, 'solveAndFreeze').mockResolvedValue(eligible);
  mountClimate(organizationWorkspace, { app, packages: [organizationMethod], snapshots: [wrongRevision, climateSnapshot, eligible, laterMfa] });
  fireEvent.click(await screen.findByRole('button', { name: '核算' }));
  fireEvent.click(screen.getByRole('button', { name: '开始计算' }));
  await waitFor(() => expect(solve).toHaveBeenCalledOnce());
  expect(solve.mock.calls[0][2]).toMatchObject({ climate_default: true, calculation_purpose: 'lca',
    project_background_pins: organizationWorkspace.project_background_pins });
});

it('keeps PCF and organization available without a background and hides the raw method ID', async () => {
  const app: Application = { ...application, context: { ...application.context, method_package_refs: ['org.steel@1.0.5'] } };
  mountClimate({ ...workspace, capabilities: ['organization.lifecycle-carbon.v1'] }, { app, packages: [organizationMethod] });
  fireEvent.click(await screen.findByRole('button', { name: '核算' }));
  expect(screen.getByRole('radio', { name: /组织碳核算/ })).toBeEnabled();
  expect(screen.getByRole('button', { name: '取消' })).toBeInTheDocument();
  expect(screen.queryByText(/org\.steel@1\.0\.5/)).not.toBeInTheDocument();
});

it('routes a return that descends from a reviewed template into the fillable workbench', async () => {
  // A model handed back from professional modelling is only fillable because it carries the reviewed
  // template it descends from; that must open the workbench, not the read-only professional view.
  const returned: Application = { ...application, context: {
    ...application.context, modeling_handoff_id: 'h-1', template_locked: true,
    modeling_template_binding: { profile: { id: 'steel', version: '1.0.0', content_sha256: 'x'.repeat(64) } },
  } };
  const returnedWorkspace: ProjectWorkspace = { ...workspace, capabilities: ['mfa.solved.v1', 'solve.nebula.v1', 'pcf.product.v1', 'cbam.partial-review.v1'],
    blocked_capabilities: [{ capability: 'cbam.trial.v2', reason: '跨界供给尚未声明' }] };
  vi.spyOn(api, 'application').mockResolvedValue(returned);
  vi.spyOn(api, 'models').mockResolvedValue([model]);
  vi.spyOn(api, 'revisions').mockResolvedValue([revision]);
  vi.spyOn(api, 'workspace').mockResolvedValue(returnedWorkspace);
  vi.spyOn(api, 'methodPackages').mockResolvedValue([]);
  vi.spyOn(api, 'solvedSnapshots').mockResolvedValue([]);
  const solve = vi.spyOn(api, 'solveAndFreeze').mockResolvedValue(climateSnapshot);
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>
    <MemoryRouter initialEntries={['/applications/app-steel/workbench?step=reports']}>
      <Routes><Route path="/applications/:applicationId/workbench" element={<ProjectWorkspacePage />} /></Routes>
    </MemoryRouter>
  </QueryClientProvider>);
  // The workbench offers the tasks the current model can actually answer for: material flow works,
  // while the undeclared cross-boundary supply stays a blocked task rather than a live button.
  fireEvent.click(await screen.findByRole('button', { name: '核算' }));
  expect(screen.getByRole('radio', { name: /物质流分析/ })).toBeInTheDocument();
  // The blocked capability shows a Chinese task name, not the raw capability key, alongside its reason.
  expect(screen.getAllByText(/当前数据版本的 CBAM 边界尚未通过审查/).length).toBeGreaterThan(0);
  expect(screen.queryByText(/cbam\.trial\.v2/)).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: '计算并查看 CBAM' })).not.toBeInTheDocument();
  // The covered-range LCA button is no longer a first-release task; product footprint covers it.
  expect(screen.queryByRole('button', { name: '计算已覆盖范围 LCA' })).toBeNull();
  fireEvent.click(screen.getByRole('radio', { name: /产品碳足迹/ }));
  fireEvent.click(screen.getByRole('button', { name: '开始计算' }));
  await waitFor(() => expect(solve).toHaveBeenCalledOnce());
  expect(solve.mock.calls[0][2]).toMatchObject({ calculation_purpose: 'lca', climate_default: true });
});
