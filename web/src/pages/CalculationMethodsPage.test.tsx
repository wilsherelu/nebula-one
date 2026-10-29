import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, expect, it, vi } from 'vitest';
import { api, ApiError } from '../api/client';
import { seedProjectsApi } from '../api/seedProjects';
import type { CalculationMethod, CalculationMethodCapabilities, CalculationMethodDetail, CalculationMethodRule, CalculationMethodValidation, ClassificationSuggestions, MethodPackage, ProjectWorkspace, SystemModel, SystemRevision } from '../api/types';
import { CalculationMethodsPage } from './CalculationMethodsPage';

function LocationProbe() { const location = useLocation(); return <output aria-label="当前位置">{location.pathname}{location.search}</output>; }

const model: SystemModel = { id: 'model-1', application_id: 'app-steel', name: '钢铁模型', provider: 'nebula_lca', provider_base_url: 'http://127.0.0.1:18023', upstream_project_id: 'up-1', upstream_version: 3, graph_sha256: 'g'.repeat(64), upstream_receipt: {}, created_at: '2026-09-22T00:00:00Z' };
const r1: SystemRevision = { id: 'r1', system_model_id: 'model-1', parent_revision_id: null, revision_number: 1, label: null, revision_kind: 'data', graph_sha256: 'g'.repeat(64), content_sha256: 'c'.repeat(64), status: 'active', created_at: '2026-09-22T00:00:00Z', published_at: null };
const r2: SystemRevision = { ...r1, id: 'r2', parent_revision_id: 'r1', revision_number: 2, content_sha256: 'd'.repeat(64) };
const method: CalculationMethod = { id: 'm1', application_id: 'app-steel', model_revision_id: 'r2', purpose: 'pcf', name: '我的产品碳足迹方法', description: '说明', origin_method_id: null, status: 'draft', created_at: '2026-09-22T00:00:00Z', updated_at: '2026-09-22T00:00:00Z' };
const pkg: MethodPackage = { id: 'official', package_id: 'pcf.steel', version: '1.0.5', package_kind: 'product_carbon_footprint', jurisdiction: null, valid_from: null, valid_to: null, manifest: {}, content_sha256: 'f'.repeat(64), status: 'active', created_at: '2026-09-22T00:00:00Z' };
const power: CalculationMethodRule = { process_instance_id: 'p-steelmaking', exchange_id: 'p-steelmaking::e1', flow_uuid: 'power', direction: 'input', boundary_status: 'selected', location_role: 'purchased_energy', scope: 'scope_2', cbam_relevant: false, classification_basis: 'user' };
const co2: CalculationMethodRule = { process_instance_id: 'p-steelmaking', exchange_id: 'p-steelmaking::e9', flow_uuid: 'co2', direction: 'emission', boundary_status: 'pending', location_role: 'onsite', scope: 'scope_1', cbam_relevant: true, classification_basis: 'user' };
const detail: CalculationMethodDetail = { method, latest_version: 2, versions: [
  { id: 'v2', method_id: 'm1', version: 2, cbam_boundary_ref: null, content_sha256: 'b'.repeat(64), status: 'draft', created_at: '2026-09-23T00:00:00Z', validated_at: null, rules: [power, co2] },
  { id: 'v1', method_id: 'm1', version: 1, cbam_boundary_ref: null, content_sha256: 'a'.repeat(64), status: 'draft', created_at: '2026-09-22T00:00:00Z', validated_at: null, rules: [power] },
] };
const workspace: ProjectWorkspace = { application_id: 'app-steel', revision_id: 'r2', content_sha256: 'd'.repeat(64), template_title: '钢铁', fields: [
  { key: 'power', label: '电力', process: '炼钢', process_id: 'p-steelmaking', port_id: 'e1', group: 'inputs', flow_type: 'technosphere', value: 50, unit: 'kWh' },
  { key: 'co2', label: '二氧化碳', process: '炼钢', process_id: 'p-steelmaking', port_id: 'e9', group: 'outputs', flow_type: 'biosphere', value: 1, unit: 'kg' },
  { key: 'ch4', label: '甲烷', process: '炼钢', process_id: 'p-steelmaking', port_id: 'e10', group: 'emissions', flow_type: 'biosphere', value: 0.1, unit: 'kg' },
], demand: [{ reference_flow_uuid: 'steel', amount: 1000, unit: 'kg' }], source: '台账', saved: true, capabilities: [], blocked_capabilities: [], background_options: [], background_note: '', process_graph: { nodes: [{ id: 'p-steelmaking', name: '炼钢' }], edges: [] } };

const capabilities = {
  method_id: 'm1', method_name: '我的产品碳足迹方法', semantics: null, latest_version: 2, latest_status: 'draft',
  content_sha256: 'b'.repeat(64), purpose: 'pcf', tag_scheme: false, tag_grouping: false,
  result_category: false, legacy_tag_scheme: false, legacy_method: false, conversion_available: false,
  dedicated_strategy: null, processing_package_selection: true, processing_package_reason: null,
};

const tagMethod: CalculationMethod = { ...method, id: 't1', name: '能源标签', purpose: 'custom', semantics: 'result_category.v1',
  latest_version: 1, latest_content_sha256: 'b'.repeat(64), latest_status: 'draft', category_summary: ['购入能源', '现场排放'] };
const tagRule: CalculationMethodRule = { process_instance_id: 'p-steelmaking', exchange_id: 'p-steelmaking::e1', flow_uuid: 'power',
  direction: 'input', boundary_status: 'selected', location_role: 'other', scope: null, cbam_relevant: false, classification_basis: 'user',
  categories: { result_category: 'result_category_1' } };
const tagDimensions = [{ id: 'result_category', name: '分类', categories: [
  { id: 'result_category_1', name: '购入能源', is_leaf: true },
  { id: 'result_category_2', name: '现场排放', is_leaf: true },
] }];
const tagDetail: CalculationMethodDetail = { method: tagMethod, latest_version: 1, versions: [{
  id: 't1v1', method_id: 't1', version: 1, cbam_boundary_ref: null, content_sha256: 'b'.repeat(64), status: 'draft',
  created_at: '2026-09-23T00:00:00Z', validated_at: null, rules: [tagRule], reporting_dimensions: tagDimensions, semantics: 'result_category.v1',
}] };
const legacyMethod: CalculationMethod = { ...tagMethod, id: 't0', name: '旧能源标签', semantics: 'flow_tag.v1' };
const legacyDetail: CalculationMethodDetail = { method: legacyMethod, latest_version: 1, versions: [{
  ...tagDetail.versions[0], id: 't0v1', method_id: 't0', rules: [{ ...tagRule, categories: { tag: 'tag_category_1' } }],
  reporting_dimensions: [{ id: 'tag', name: '分类', categories: [
    { id: 'tag_category_1', name: '购入能源', is_leaf: true },
  ] }], semantics: 'flow_tag.v1',
}] };

function stubs(options: { methods?: CalculationMethod[]; detail?: CalculationMethodDetail; capabilities?: CalculationMethodCapabilities } = {}) {
  vi.spyOn(api, 'models').mockResolvedValue([model]);
  vi.spyOn(api, 'revisions').mockResolvedValue([r1, r2]);
  vi.spyOn(api, 'methodPackages').mockResolvedValue([pkg]);
  const listed = options.methods ?? [method];
  vi.spyOn(api, 'calculationMethods').mockImplementation((_a, revisionId) => Promise.resolve(revisionId === 'r2' ? listed : []));
  vi.spyOn(api, 'calculationMethod').mockResolvedValue(options.detail ?? detail);
  vi.spyOn(api, 'calculationMethodCapabilities').mockResolvedValue(options.capabilities ?? capabilities);
  vi.spyOn(api, 'workspace').mockResolvedValue(workspace);
}

/** The version/history/source and copy actions live behind the "更多" menu, never as permanent tabs. */
async function openMore(item: string) {
  fireEvent.click(await screen.findByRole('button', { name: '更多' }));
  const items = await screen.findAllByText(item);
  fireEvent.click(items[items.length - 1]);
}

/** Arco keeps a closed modal mounted with role=dialog; only a wrapper that is not display:none is open. */
function openDialogs(): HTMLElement[] {
  return screen.queryAllByRole('dialog').filter(dialog => {
    const wrapper = dialog.closest('.arco-modal-wrapper') as HTMLElement | null;
    return !wrapper || wrapper.style.display !== 'none';
  });
}
async function findOpenDialog(count = 1): Promise<HTMLElement> {
  await waitFor(() => expect(openDialogs()).toHaveLength(count));
  return openDialogs()[count - 1];
}
function mount(url: string, options: Parameters<typeof stubs>[0] = {}) {
  stubs(options);
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={[url]}>
      <Routes><Route path="/applications/:applicationId/calculation-methods" element={<CalculationMethodsPage />} /></Routes>
    </MemoryRouter>
  </QueryClientProvider>);
}
afterEach(() => { cleanup(); vi.restoreAllMocks(); localStorage.clear(); });

it('lists bound user methods and the exact revision, then opens the detail', async () => {
  mount('/applications/app-steel/calculation-methods');
  expect((await screen.findAllByText('我的产品碳足迹方法')).length).toBeGreaterThan(0);
  expect(api.calculationMethods).toHaveBeenCalledWith('app-steel', 'r2');
  expect(screen.getByRole('button', { name: '返回项目' })).toBeInTheDocument();
  const openButton = screen.getAllByRole('button', { name: '查看详情' })[0];
  fireEvent.click(openButton);
  expect(await screen.findByText('返回结果分类')).toBeInTheDocument();
});

it('filters rule rows by the electricity keyword on the rules tab', async () => {
  mount('/applications/app-steel/calculation-methods?method=m1');
  const input = await screen.findByPlaceholderText('搜索电力、热、蒸汽、燃料、排放');
  fireEvent.change(input, { target: { value: '电力' } });
  await waitFor(() => expect(screen.queryAllByText('二氧化碳')).toHaveLength(0));
  expect(screen.getAllByText('电力').length).toBeGreaterThan(0);
});

it('refuses an unknown method without falling back to the list', async () => {
  mount('/applications/app-steel/calculation-methods?method=ghost');
  expect(await screen.findByText('未找到该计算方法或版本。')).toBeInTheDocument();
  expect(api.calculationMethod).not.toHaveBeenCalled();
});

it('refuses an unknown method version instead of defaulting to latest', async () => {
  mount('/applications/app-steel/calculation-methods?method=m1&version=99');
  expect(await screen.findByText('未找到该计算方法或版本。')).toBeInTheDocument();
});

it('saves an edited method as a new version against the loaded content hash', async () => {
  mount('/applications/app-steel/calculation-methods?method=m1');
  const save = vi.spyOn(api, 'saveCalculationMethodVersion').mockResolvedValue(detail);
  await openMore('编辑名称与说明');
  const nameInput = await screen.findByDisplayValue('我的产品碳足迹方法');
  fireEvent.change(nameInput, { target: { value: '改名后的方法' } });
  expect((await screen.findAllByText('有未保存的修改')).length).toBeGreaterThan(0);
  fireEvent.click(screen.getByRole('button', { name: '保存为新版本' }));
  await waitFor(() => expect(save).toHaveBeenCalledOnce());
  const [methodId, version, payload] = save.mock.calls[0];
  expect(methodId).toBe('m1');
  expect(version).toBe(2);
  expect(payload.expected_content_sha256).toBe('b'.repeat(64));
  expect(payload.name).toBe('改名后的方法');
  expect(payload.rules).toEqual([power, co2]);
});

it('keeps the edited input and shows a reload action when the save conflicts', async () => {
  mount('/applications/app-steel/calculation-methods?method=m1');
  vi.spyOn(api, 'saveCalculationMethodVersion').mockRejectedValue(new ApiError('方法已更新', 409, 'CALCULATION_METHOD_CONFLICT'));
  await openMore('编辑名称与说明');
  const nameInput = await screen.findByDisplayValue('我的产品碳足迹方法');
  fireEvent.change(nameInput, { target: { value: '未保存的编辑' } });
  fireEvent.click(screen.getByRole('button', { name: '保存为新版本' }));
  expect(await screen.findByText('该方法已被其他操作更新')).toBeInTheDocument();
  expect(screen.getByDisplayValue('未保存的编辑')).toBeInTheDocument();
});

it('discards a local draft without touching the saved version', async () => {
  mount('/applications/app-steel/calculation-methods?method=m1');
  await openMore('编辑名称与说明');
  const nameInput = await screen.findByDisplayValue('我的产品碳足迹方法');
  fireEvent.change(nameInput, { target: { value: '临时草稿' } });
  fireEvent.click(screen.getByRole('button', { name: '撤销本次未保存修改' }));
  expect(await screen.findByDisplayValue('我的产品碳足迹方法')).toBeInTheDocument();
  expect(screen.queryByText('有未保存的修改')).toBeNull();
});

it('clones the latest version into a new method bound to the same revision', async () => {
  mount('/applications/app-steel/calculation-methods?method=m1');
  const clone = vi.spyOn(api, 'cloneCalculationMethod').mockResolvedValue({ ...detail, method: { ...method, id: 'm2', name: '我的产品碳足迹方法 · 副本', origin_method_id: 'm1' } });
  await openMore('另存方案');
  fireEvent.click(await screen.findByRole('button', { name: '另存为方案' }));
  await waitFor(() => expect(clone).toHaveBeenCalledOnce());
  const [methodId, version, payload] = clone.mock.calls[0];
  expect(methodId).toBe('m1');
  expect(version).toBe(2);
  expect(payload).toEqual({ name: '我的产品碳足迹方法 · 副本', purpose: 'pcf', model_revision_id: 'r2' });
});

it('shows read-only history for a superseded version instead of editing controls', async () => {
  mount('/applications/app-steel/calculation-methods?method=m1&version=1');
  expect(await screen.findByText('只读')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: '保存为新版本' })).toBeNull();
  const co2Row = (await screen.findByText('二氧化碳')).closest('tr') as HTMLElement;
  expect(within(co2Row).getByText('待确认')).toBeInTheDocument();
  expect(within(co2Row).queryByText('范围1')).toBeNull();
  await openMore('编辑名称与说明');
  expect((await screen.findAllByText('正在查看历史版本（只读）。只有最新版本可以编辑。')).length).toBeGreaterThan(0);
});

it('clones the history version the reader is viewing', async () => {
  mount('/applications/app-steel/calculation-methods?method=m1&version=1');
  const clone = vi.spyOn(api, 'cloneCalculationMethod').mockResolvedValue(detail);
  await openMore('另存方案');
  fireEvent.click(await screen.findByRole('button', {name: '另存为方案'}));
  await waitFor(() => expect(clone).toHaveBeenCalledWith('m1', 1, expect.anything()));
});

it('keeps the newly chosen category when a saved relation is set to 无 and chosen again', async () => {
  mount('/applications/app-steel/calculation-methods?method=t1', { methods: [tagMethod], detail: tagDetail });
  const save = vi.spyOn(api, 'saveCalculationMethodVersion').mockResolvedValue(tagDetail);
  const row = (await screen.findByText('电力')).closest('tr') as HTMLElement;
  fireEvent.click(within(row).getByLabelText('结果分类'));
  fireEvent.click(await screen.findByRole('option', {name: '无'}));
  await waitFor(() => expect(screen.queryByRole('option', {name: '无'})).not.toBeInTheDocument());
  const clearedRow = screen.getByText('电力').closest('tr') as HTMLElement;
  fireEvent.click(within(clearedRow).getByLabelText('结果分类'));
  fireEvent.click(await screen.findByRole('option', {name: '现场排放'}));
  fireEvent.click(screen.getByRole('button', {name: '保存为新版本'}));
  await waitFor(() => expect(save).toHaveBeenCalledOnce());
  expect(save.mock.calls[0][2].rules).toContainEqual(expect.objectContaining({
    exchange_id: 'p-steelmaking::e1', categories: {result_category: 'result_category_2'},
  }));
});

it('shows save refusal without clearing the edited category', async () => {
  mount('/applications/app-steel/calculation-methods?method=t1', { methods: [tagMethod], detail: tagDetail });
  vi.spyOn(api, 'saveCalculationMethodVersion').mockRejectedValue(new ApiError('分类已被修改，请重新检查', 422, 'RESULT_CATEGORY_INVALID'));
  const row = (await screen.findByText('电力')).closest('tr') as HTMLElement;
  fireEvent.click(within(row).getByLabelText('结果分类'));
  fireEvent.click(await screen.findByRole('option', {name: '现场排放'}));
  fireEvent.click(screen.getByRole('button', {name: '保存为新版本'}));
  expect(await screen.findByText('分类已被修改，请重新检查')).toBeInTheDocument();
  expect(within(row).getByText('现场排放')).toBeInTheDocument();
  expect(screen.getByRole('button', {name: '保存为新版本'})).toBeEnabled();
});

it('creates a brand-new result category on the exact revision and opens it for editing', async () => {
  mount('/applications/app-steel/calculation-methods');
  const created: CalculationMethod = { ...method, id: 'm-new', name: '新口径', purpose: 'custom', semantics: 'result_category.v1', origin_method_id: null };
  vi.spyOn(api, 'calculationMethods').mockImplementation((_a, revisionId) =>
    Promise.resolve(revisionId === 'r2' ? [method, created] : []));
  const create = vi.spyOn(api, 'createCalculationMethod').mockResolvedValue({ ...detail, method: created });
  fireEvent.click(await screen.findByRole('button', { name: '新建结果分类' }));
  fireEvent.change(await screen.findByPlaceholderText('方法名称'), { target: { value: '新口径' } });
  fireEvent.change(screen.getByPlaceholderText('分类名称'), { target: { value: '购入能源' } });
  fireEvent.click(screen.getByRole('button', { name: '创建并编辑' }));
  await waitFor(() => expect(create).toHaveBeenCalledOnce());
  expect(create).toHaveBeenCalledWith('app-steel', {
    name: '新口径', purpose: 'custom', model_revision_id: 'r2', rules: [], semantics: 'result_category.v1',
    reporting_dimensions: [{ id: 'result_category', name: '分类', categories: [{ id: 'result_category_1', name: '购入能源', is_leaf: true }] }],
  });
  expect(await screen.findByText('返回结果分类')).toBeInTheDocument();
});

it('blocks creating a result category until a name is entered', async () => {
  mount('/applications/app-steel/calculation-methods');
  fireEvent.click(await screen.findByRole('button', { name: '新建结果分类' }));
  const submit = await screen.findByRole('button', { name: '创建并编辑' });
  expect(submit).toBeDisabled();
  expect(screen.getByText('请先填写方法名称。')).toBeInTheDocument();
});

const failedValidation: CalculationMethodValidation = {
  method_id: 'm1', version: 2, model_revision_id: 'r2', content_sha256: 'b'.repeat(64),
  valid: false, status: 'draft', validated_at: '2026-09-24T00:00:00Z',
  problems: [{ code: 'CALCULATION_METHOD_SCOPE_LOCATION_MISMATCH', message: 'Scope 与位置角色不符', rule_index: 0, process_instance_id: 'p-steelmaking', exchange_id: 'p-steelmaking::e1' }],
};

it('validates the latest version and lists each problem located to its process', async () => {
  mount('/applications/app-steel/calculation-methods?method=m1');
  const validate = vi.spyOn(api, 'validateCalculationMethodVersion').mockResolvedValue(failedValidation);
  fireEvent.click(await screen.findByRole('button', { name: '检查' }));
  fireEvent.click(await screen.findByRole('button', { name: '校验该方法版本' }));
  await waitFor(() => expect(validate).toHaveBeenCalledWith('m1', 2));
  expect(await screen.findByText('CALCULATION_METHOD_SCOPE_LOCATION_MISMATCH')).toBeInTheDocument();
  expect(screen.getByText('Scope 与位置角色不符')).toBeInTheDocument();
  expect(screen.getByText(/过程 p-steelmaking · 交换 p-steelmaking::e1/)).toBeInTheDocument();
  expect(screen.getByText('未通过校验的方法版本不能进入计算。请修正下列问题后重新校验。')).toBeInTheDocument();
});

it('reports a passing validation and marks the version usable', async () => {
  mount('/applications/app-steel/calculation-methods?method=m1');
  vi.spyOn(api, 'validateCalculationMethodVersion').mockResolvedValue({ ...failedValidation, valid: true, status: 'ready', problems: [] });
  fireEvent.click(await screen.findByRole('button', { name: '检查' }));
  fireEvent.click(await screen.findByRole('button', { name: '校验该方法版本' }));
  expect(await screen.findByText('校验通过：该方法版本可用于计算。')).toBeInTheDocument();
});

it('disables validation while an unsaved draft makes the result stale', async () => {
  mount('/applications/app-steel/calculation-methods?method=m1');
  await openMore('编辑名称与说明');
  const nameInput = await screen.findByDisplayValue('我的产品碳足迹方法');
  fireEvent.change(nameInput, { target: { value: '未保存草稿' } });
  fireEvent.click(await screen.findByRole('button', { name: '检查' }));
  expect(await screen.findByText('草稿尚未保存，无法校验。请先“保存为新版本”后再校验。')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '校验该方法版本' })).toBeDisabled();
});

it('shows validation as read-only for a historical version', async () => {
  mount('/applications/app-steel/calculation-methods?method=m1&version=1');
  fireEvent.click(await screen.findByRole('button', { name: '检查' }));
  expect(await screen.findByText('只能校验最新版本，历史版本为只读。')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '校验该方法版本' })).toBeDisabled();
});

it('lists every exchange of the selected process, including the ones no rule covers yet', async () => {
  mount('/applications/app-steel/calculation-methods?method=m1');
  expect(await screen.findByRole('heading', { name: /炼钢/ })).toBeInTheDocument();
  expect(screen.getByText('3 个流 · 2 条已设置')).toBeInTheDocument();
  const methane = (await screen.findByText('甲烷')).closest('tr') as HTMLElement;
  expect(within(methane).getByText('未设置（待确认）')).toBeInTheDocument();
  const power = screen.getByText('电力').closest('tr') as HTMLElement;
  expect(within(power).getByText('单独设置')).toBeInTheDocument();
  expect(screen.getByText('共 3 个流，3 个符合筛选')).toBeInTheDocument();
});

it('inherits a historical process default on unset flows, overrides one flow, and restores it', async () => {
  // The editor no longer authors new implicit process defaults (§2.2); a default the historical
  // scheme already carries is resolved server-side into the unset flows' effective value, shown
  // read-only, and a per-flow override still wins until the reader restores the default.
  const historicalDefault: CalculationMethodRule = { process_instance_id: 'p-steelmaking', exchange_id: null, flow_uuid: null, direction: 'emission', contribution_target: 'direct', boundary_status: 'pending', location_role: 'other', scope: null, cbam_relevant: false, classification_basis: 'user' };
  let current: CalculationMethodDetail = { ...detail, versions: [
    { ...detail.versions[0], rules: [power, co2, historicalDefault] },
    detail.versions[1],
  ] };
  stubs();
  vi.spyOn(api, 'calculationMethod').mockImplementation(() => Promise.resolve(current));
  const save = vi.spyOn(api, 'saveCalculationMethodVersion').mockImplementation(async (_id, version, payload) => {
    current = { ...current, latest_version: version + 1, versions: [
      { id: `v${version + 1}`, method_id: 'm1', version: version + 1, cbam_boundary_ref: payload.cbam_boundary_ref ?? null,
        content_sha256: `${version + 1}`.padStart(64, 'e'), status: 'draft', created_at: '2026-09-24T00:00:00Z',
        validated_at: null, rules: payload.rules, reporting_dimensions: payload.reporting_dimensions },
      ...current.versions,
    ] };
    return current;
  });
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={['/applications/app-steel/calculation-methods?method=m1']}>
      <Routes><Route path="/applications/:applicationId/calculation-methods" element={<CalculationMethodsPage />} /></Routes>
    </MemoryRouter>
  </QueryClientProvider>);

  // The unset emission flow inherits the historical default; the already-set one does not.
  await waitFor(() => expect(within((screen.getByText('甲烷')).closest('tr') as HTMLElement).getByText('继承过程默认')).toBeInTheDocument());
  expect(within(screen.getByText('二氧化碳').closest('tr') as HTMLElement).getByText('单独设置')).toBeInTheDocument();

  // One per-flow override on the inheriting row is saved as its own rule, next to the default.
  const methane = screen.getByText('甲烷').closest('tr') as HTMLElement;
  fireEvent.click(within(methane).getByLabelText('是否计入'));
  fireEvent.click(await screen.findByRole('option', { name: '不计入' }));
  await waitFor(() => expect(within(screen.getByText('甲烷').closest('tr') as HTMLElement).getByText('单独设置')).toBeInTheDocument());
  fireEvent.click(screen.getByRole('button', { name: '保存为新版本' }));
  await waitFor(() => expect(save).toHaveBeenCalledOnce());
  const overridden = save.mock.calls[0][2].rules;
  expect(overridden).toContainEqual(expect.objectContaining({
    exchange_id: 'p-steelmaking::e10', boundary_status: 'excluded', scope: null,
  }));
  // the historical default itself is preserved, never rewritten by a per-flow override
  expect(overridden).toContainEqual(expect.objectContaining({ exchange_id: null, direction: 'emission' }));

  // Restoring the default drops exactly that override, so the flow inherits the saved default again.
  fireEvent.click(within(screen.getByText('甲烷').closest('tr') as HTMLElement).getByRole('button', { name: '恢复过程默认' }));
  await waitFor(() => expect(within(screen.getByText('甲烷').closest('tr') as HTMLElement).getByText('继承过程默认')).toBeInTheDocument());
  fireEvent.click(screen.getByRole('button', { name: '保存为新版本' }));
  await waitFor(() => expect(save).toHaveBeenCalledTimes(2));
  const restored = save.mock.calls[1][2].rules;
  expect(restored.some(rule => rule.exchange_id === 'p-steelmaking::e10')).toBe(false);
  expect(restored).toContainEqual(expect.objectContaining({ exchange_id: null, direction: 'emission' }));
});

it('removes a rule so it is dropped from the saved list', async () => {
  mount('/applications/app-steel/calculation-methods?method=m1');
  const co2Cell = await screen.findByText('二氧化碳');
  fireEvent.click(within(co2Cell.closest('tr') as HTMLElement).getByRole('button', { name: '移除' }));
  const save = vi.spyOn(api, 'saveCalculationMethodVersion').mockResolvedValue(detail);
  fireEvent.click(screen.getByRole('button', { name: '保存为新版本' }));
  await waitFor(() => expect(save).toHaveBeenCalledOnce());
  expect(save.mock.calls[0][2].rules).toEqual([power]);
});

it('batch sets inclusion on the selected flows behind a confirm and leaves the unselected ones alone', async () => {
  mount('/applications/app-steel/calculation-methods?method=m1');
  fireEvent.click(await screen.findByRole('checkbox', { name: '已选 1 条 电力' }));
  fireEvent.click(screen.getByRole('checkbox', { name: '已选 1 条 二氧化碳' }));
  expect(screen.getByText('已选 2 条')).toBeInTheDocument();
  fireEvent.click(screen.getByLabelText('批量设定是否计入'));
  fireEvent.click(await screen.findByText('不计入'));
  // The batch is a whole-process operation: it names the process and the affected count and asks
  // for confirmation before writing, so a mis-scoped apply is not silent.
  fireEvent.click(screen.getByRole('button', { name: '应用到所选' }));
  const dialog = await screen.findByRole('dialog');
  expect(within(dialog).getByText(/炼钢/)).toBeInTheDocument();
  expect(within(dialog).getByText('将影响 2 条规则，单条例外不受影响。')).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole('button', { name: '确认应用' }));
  const save = vi.spyOn(api, 'saveCalculationMethodVersion').mockResolvedValue(detail);
  fireEvent.click(screen.getByRole('button', { name: '保存为新版本' }));
  await waitFor(() => expect(save).toHaveBeenCalledOnce());
  const rules = save.mock.calls[0][2].rules;
  // The unselected 甲烷 row is not turned into a rule by the batch operation.
  expect(rules).toHaveLength(2);
  // Exclusion only flips inclusion; each flow keeps the Scope it already carried, because
  // inclusion and result-grouping are two independent settings and an excluded flow still tracks
  // its original classification.
  expect(rules.every(rule => rule.boundary_status === 'excluded')).toBe(true);
  expect(rules.find(rule => rule.exchange_id === 'p-steelmaking::e1')?.scope).toBe('scope_2');
  expect(rules.find(rule => rule.exchange_id === 'p-steelmaking::e9')?.scope).toBe('scope_1');
});

it('authors a non-Scope category dimension and groups a flow onto a saved version', async () => {
  mount('/applications/app-steel/calculation-methods?method=m1');

  // Declare one custom dimension: the editor adds a dimension_1 axis with a category_1 leaf, no Scope needed.
  fireEvent.click(await screen.findByRole('button', { name: '添加类别维度' }));
  expect(await screen.findByDisplayValue('dimension_1')).toBeInTheDocument();

  // The per-flow category column appears over the same process context; assign the electricity flow.
  const row = (await screen.findByText('电力')).closest('tr') as HTMLElement;
  fireEvent.click(within(row).getByLabelText('dimension_1'));
  fireEvent.click(await screen.findByText('category_1'));

  const save = vi.spyOn(api, 'saveCalculationMethodVersion').mockResolvedValue(detail);
  fireEvent.click(screen.getByRole('button', { name: '保存为新版本' }));
  await waitFor(() => expect(save).toHaveBeenCalledOnce());
  const payload = save.mock.calls[0][2];
  expect(payload.reporting_dimensions).toEqual([
    { id: 'dimension_1', name: '', categories: [{ id: 'category_1', name: '', is_leaf: true }] },
  ]);
  expect(payload.rules).toContainEqual(expect.objectContaining({
    exchange_id: 'p-steelmaking::e1', categories: { dimension_1: 'category_1' },
  }));
});

it('sets inclusion and Scope on the same row in one edit without a second CBAM switch', async () => {
  // F3: the unified editor puts 是否计入 and 结果分类 on one contribution row, so a single edit sets
  // both; the row never exposes a separate cbam_relevant switch (the backend derives it).
  mount('/applications/app-steel/calculation-methods?method=m1');
  const row = (await screen.findByText('甲烷')).closest('tr') as HTMLElement;
  expect(within(row).queryByLabelText('纳入 CBAM 边界')).toBeNull();
  fireEvent.click(within(row).getByLabelText('是否计入'));
  fireEvent.click(await screen.findByRole('option', { name: '计入' }));
  fireEvent.click(within(row).getByLabelText('结果分类'));
  fireEvent.click(await screen.findByRole('option', { name: '范围2' }));
  const save = vi.spyOn(api, 'saveCalculationMethodVersion').mockResolvedValue(detail);
  fireEvent.click(screen.getByRole('button', { name: '保存为新版本' }));
  await waitFor(() => expect(save).toHaveBeenCalledOnce());
  const rules = save.mock.calls[0][2].rules;
  expect(rules).toContainEqual(expect.objectContaining({
    exchange_id: 'p-steelmaking::e10', boundary_status: 'selected', scope: 'scope_2',
  }));
  expect(rules).toContainEqual(power);
});

it('binds a compatible processing package and saves the exact reference for readback', async () => {
  mount('/applications/app-steel/calculation-methods?method=m1');
  vi.spyOn(api, 'selectableProcessingPackages').mockResolvedValue([
    { package_id: 'steel-bf-bof.model-processing', version: '1.0.12', content_sha256: 'c'.repeat(64), selection_mode: 'explicit_only', purpose_declared: true, elementary_flows_mode: 'explicit_flow_rules' },
  ]);
  const save = vi.spyOn(api, 'saveCalculationMethodVersion').mockResolvedValue(detail);

  // The package list comes from the server under this method's template, graph and purpose; the user
  // never edits model or rule internals, only picks one compatible reviewed package here.
  await openMore('来源与诊断');
  await userEvent.click(await screen.findByRole('combobox', { name: '处理规则包' }));
  fireEvent.click(await screen.findByRole('option', { name: 'steel-bf-bof.model-processing · 1.0.12' }));

  // Selection persists through save (a variant→save+readback), not a request-time swap.
  fireEvent.click(screen.getByRole('button', { name: '保存为新版本' }));
  await waitFor(() => expect(save).toHaveBeenCalledOnce());
  expect(save.mock.calls[0][2].model_processing_rules_ref).toEqual({
    package_id: 'steel-bf-bof.model-processing', version: '1.0.12', content_sha256: 'c'.repeat(64),
  });
});

it('keeps the official automatic default unbound when nothing is selected', async () => {
  mount('/applications/app-steel/calculation-methods?method=m1');
  vi.spyOn(api, 'selectableProcessingPackages').mockResolvedValue([
    { package_id: 'steel-bf-bof.model-processing', version: '1.0.12', content_sha256: 'c'.repeat(64), selection_mode: 'explicit_only', purpose_declared: true, elementary_flows_mode: 'explicit_flow_rules' },
  ]);

  await openMore('来源与诊断');
  // An untouched head inherits the server's null binding, so the official path shows the automatic
  // default and never auto-selects the new package.
  expect(await screen.findByText('自动默认（不显式绑定）')).toBeInTheDocument();
});

it('sends an old template=1 method link into the template configuration workspace', async () => {
  stubs();
  vi.spyOn(seedProjectsApi, 'catalog').mockResolvedValue({ items: [{
    id: 'steel', title: '高炉—转炉钢铁', version: '1.1.0', template_sha256: 'a'.repeat(64), seed_id: 'steel-template',
    installed_application_id: 'installed', source_application_id: 'app-steel', source_model_id: 'model-1',
    source_revision_id: 'r2', process_count: 5, field_count: 28, capabilities: [],
  }] });
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={['/applications/app-steel/calculation-methods?model=model-1&revision=r2&template=1']}>
      <Routes>
        <Route path="/applications/:applicationId/calculation-methods" element={<CalculationMethodsPage />} />
        <Route path="/templates/:templateId/config" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>
  </QueryClientProvider>);
  // The list is not shown at all: a template link configures a template version, not a project.
  await waitFor(() => expect(screen.getByLabelText('当前位置')).toHaveTextContent('/templates/steel/config?tab=methods'));
  expect(screen.queryByText('我的产品碳足迹方法')).not.toBeInTheDocument();
});

const draftKeys = () => Object.keys(localStorage).filter(key => key.startsWith('nebula.calc-method-draft:'));

it('asks before leaving unsaved rule edits, and the draft survives only when the reader keeps it', async () => {
  mount('/applications/app-steel/calculation-methods?method=m1');
  await openMore('编辑名称与说明');
  const identity = await findOpenDialog();
  fireEvent.change(within(identity).getByDisplayValue('我的产品碳足迹方法'), { target: { value: '未保存的名称' } });
  fireEvent.click(within(identity).getByRole('button', { name: '关闭' }));
  await waitFor(() => expect(openDialogs()).toHaveLength(0));
  fireEvent.click(await screen.findByRole('button', { name: '返回结果分类' }));
  const dialog = await findOpenDialog();
  expect(within(dialog).getByText('这个方案有尚未保存的规则修改。保留草稿后返回时可以继续编辑；放弃草稿则这些修改不可恢复。')).toBeInTheDocument();
  // Cancelling stays in the editor with the edit intact.
  fireEvent.click(within(dialog).getByRole('button', { name: '取消' }));
  await waitFor(() => expect(openDialogs()).toHaveLength(0));
  await openMore('编辑名称与说明');
  expect(await screen.findByDisplayValue('未保存的名称')).toBeInTheDocument();
  fireEvent.click(within(await findOpenDialog()).getByRole('button', { name: '关闭' }));
  await waitFor(() => expect(openDialogs()).toHaveLength(0));
  fireEvent.click(screen.getByRole('button', { name: '返回结果分类' }));
  fireEvent.click(within(await findOpenDialog()).getByRole('button', { name: '保留草稿并离开' }));
  await screen.findByRole('button', { name: '查看详情' });
  expect(draftKeys()).toHaveLength(1);
  // Returning to the same method resumes the kept draft instead of starting over.
  fireEvent.click(screen.getAllByRole('button', { name: '查看详情' })[0]);
  await openMore('编辑名称与说明');
  expect(await screen.findByDisplayValue('未保存的名称')).toBeInTheDocument();
  fireEvent.click(within(await findOpenDialog()).getByRole('button', { name: '关闭' }));
  await waitFor(() => expect(openDialogs()).toHaveLength(0));
  fireEvent.click(screen.getByRole('button', { name: '返回结果分类' }));
  fireEvent.click(within(await findOpenDialog()).getByRole('button', { name: '放弃草稿' }));
  await screen.findByRole('button', { name: '查看详情' });
  expect(draftKeys()).toHaveLength(0);
  fireEvent.click(screen.getAllByRole('button', { name: '查看详情' })[0]);
  await openMore('编辑名称与说明');
  expect(await screen.findByDisplayValue('我的产品碳足迹方法')).toBeInTheDocument();
});

it('keeps official package identifiers behind the source disclosure on the project page', async () => {
  mount('/applications/app-steel/calculation-methods');
  expect(await screen.findByText('共 1 条软件配置与版本记录，用于追溯计算，不代表监管机构发布了同等数量的方法。')).toBeInTheDocument();
  const disclosure = screen.getByText('包名与版本（来源详情）').closest('details') as HTMLDetailsElement;
  expect(disclosure.open).toBe(false);
  expect(within(disclosure).getByText('pcf.steel')).toBeInTheDocument();
});

it('offers a reload when the method list itself fails to load', async () => {
  vi.spyOn(api, 'models').mockRejectedValue(new ApiError('数据库暂时不可用', 503, 'BACKEND_UNAVAILABLE'));
  vi.spyOn(api, 'revisions').mockResolvedValue([r1, r2]);
  vi.spyOn(api, 'methodPackages').mockResolvedValue([pkg]);
  vi.spyOn(api, 'calculationMethods').mockResolvedValue([method]);
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={['/applications/app-steel/calculation-methods']}>
      <Routes><Route path="/applications/:applicationId/calculation-methods" element={<CalculationMethodsPage />} /></Routes>
    </MemoryRouter>
  </QueryClientProvider>);
  expect(await screen.findByText('数据库暂时不可用')).toBeInTheDocument();
  const attempts = vi.mocked(api.models).mock.calls.length;
  fireEvent.click(screen.getByRole('button', { name: '重新加载' }));
  await waitFor(() => expect(vi.mocked(api.models).mock.calls.length).toBeGreaterThan(attempts));
});

it('warns the browser before a refresh or close while rule edits are unsaved', async () => {
  mount('/applications/app-steel/calculation-methods?method=m1');
  await screen.findByRole('button', { name: '返回结果分类' });
  const warn = () => {
    const event = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(event);
    return event.defaultPrevented;
  };
  expect(warn()).toBe(false);
  await openMore('编辑名称与说明');
  fireEvent.change(await screen.findByDisplayValue('我的产品碳足迹方法'), { target: { value: '未保存的名称' } });
  expect((await screen.findAllByText('有未保存的修改')).length).toBeGreaterThan(0);
  expect(warn()).toBe(true);
});

it('names a frozen CBAM boundary by what it covers instead of its stored record name', async () => {
  stubs();
  vi.spyOn(api, 'calculationMethod').mockResolvedValue({
    ...detail, method: { ...method, purpose: 'cbam', name: 'CBAM·我的调整' },
  });
  vi.spyOn(api, 'boundaries').mockResolvedValue([{
    id: 'boundary-1', application_id: 'app-steel',
    // A seed installs its frozen boundary under a bundle path: an engineering identifier, so it must
    // not become the label a reader picks an accounting boundary by.
    name: 'nebula.iron-steel.bf-bof-crude-steel@1.1.0 boundaries/cbam.json',
    boundary_type: 'cbam_trial', included_entity_ids: [],
    included_process_ids: ['n1', 'n2', 'n3', 'n4', 'n5'],
    included_flow_rules: [{}, {}, {}, {}, {}, {}], excluded_items: [], consolidation_policy: {},
    period_id: null, geographic_scope: {}, method_package_ref: null, content_sha256: 'b'.repeat(64),
    status: 'frozen', created_at: '2026-09-22T00:00:00Z', frozen_at: '2026-09-22T01:00:00Z',
  }]);
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={['/applications/app-steel/calculation-methods?method=m1']}>
      <Routes><Route path="/applications/:applicationId/calculation-methods" element={<CalculationMethodsPage />} /></Routes>
    </MemoryRouter>
  </QueryClientProvider>);
  await openMore('来源与诊断');
  await userEvent.click(await screen.findByRole('combobox', { name: 'CBAM 核算边界' }));
  expect(await screen.findByRole('option', { name: 'CBAM 冻结边界（5 个过程 · 6 条流规则）' })).toBeInTheDocument();
  expect(screen.queryByText(/boundaries\/cbam\.json/)).not.toBeInTheDocument();
});

const suggestionPreview: ClassificationSuggestions = {
  strategy_version: 'nebula_one.classification-suggestion.v1',
  method_id: 'm1', version: 2, model_revision_id: 'r2',
  graph_content_sha256: 'd'.repeat(64),
  energy_packages: [],
  suggestions: [
    { exchange_id: 'p-steelmaking::e1', process_id: 'p-steelmaking', process_name: '炼钢', flow_name: '电力', unit: 'kWh', direction: 'input', status: 'already_classified', rationale: 'manual_rule_present', confidence: 'none', basis: ['rule.manual'], suggested: null, current: { boundary_status: 'selected', location_role: 'purchased_energy', scope: 'scope_2' } },
    { exchange_id: 'p-steelmaking::e9', process_id: 'p-steelmaking', process_name: '炼钢', flow_name: '二氧化碳', unit: 'kg', direction: 'emission', status: 'suggested', rationale: 'onsite_direct_emission', confidence: 'high', basis: ['flow_type.elementary', 'direction.emission', 'contribution_domain.direct'], suggested: { boundary_status: 'selected', location_role: 'onsite', scope: 'scope_1' }, current: { boundary_status: 'pending', location_role: 'onsite', scope: 'scope_1' } },
    { exchange_id: 'p-steelmaking::e10', process_id: 'p-steelmaking', process_name: '炼钢', flow_name: '甲烷', unit: 'kg', direction: 'emission', status: 'suggested', rationale: 'onsite_direct_emission', confidence: 'high', basis: ['flow_type.elementary', 'direction.emission', 'contribution_domain.direct'], suggested: { boundary_status: 'selected', location_role: 'onsite', scope: 'scope_1' }, current: null },
  ],
};

it('generates classification suggestions, previews the basis, and applies only the confirmed ones', async () => {
  mount('/applications/app-steel/calculation-methods?method=m1');
  vi.spyOn(api, 'classificationSuggestions').mockResolvedValue(suggestionPreview);
  await openMore('分类建议');
  const dialog = await screen.findByRole('dialog');
  expect(within(dialog).getByText('分类建议预览')).toBeInTheDocument();
  // The rows render once the preview query resolves; wait for one before asserting on the table.
  const powerCell = await within(dialog).findByText('电力');
  // The rationale and its evidence basis are the backend's stable codes, rendered in the UI language.
  expect(within(dialog).getAllByText('过程边界与环境的直接交换（基本流），属现场直接排放。').length).toBeGreaterThan(0);
  expect(within(dialog).getAllByText('基本流').length).toBeGreaterThan(0);
  // The operator-facing grouping label is shown next to the raw Scope.
  expect(within(dialog).getAllByText('现场直接排放').length).toBeGreaterThan(0);
  // No package is bound, so the evidence source says the energy property cannot be established.
  expect(within(dialog).getByText('未绑定方法包，购入投入的能源属性无法取证，相关端口保持待确认。')).toBeInTheDocument();

  // The already-decided electricity rule is previewed but cannot be selected or applied.
  const powerRow = powerCell.closest('tr') as HTMLElement;
  expect(within(powerRow).getByText('已手工分类')).toBeInTheDocument();
  expect(within(powerRow).getByRole('checkbox', { name: /选择该行建议/ })).toBeDisabled();
  // Actionable rows are pre-selected; nothing is written until the reader confirms.
  const methaneRow = within(dialog).getByText('甲烷').closest('tr') as HTMLElement;
  expect(within(methaneRow).getByRole('checkbox', { name: /选择该行建议/ })).toBeChecked();
  expect(within(dialog).getByText('已选 2 条建议')).toBeInTheDocument();

  const save = vi.spyOn(api, 'saveCalculationMethodVersion').mockResolvedValue(detail);
  fireEvent.click(within(dialog).getByRole('button', { name: '应用所选建议' }));
  expect(await screen.findByText('已将 2 条建议写入草稿')).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect((await screen.findAllByText('有未保存的修改')).length).toBeGreaterThan(0);
  fireEvent.click(screen.getByRole('button', { name: '保存为新版本' }));
  await waitFor(() => expect(save).toHaveBeenCalledOnce());
  const rules = save.mock.calls[0][2].rules;
  // The methane port had no rule of its own: applying created one override carrying the suggested Scope.
  expect(rules.find(rule => rule.exchange_id === 'p-steelmaking::e10')).toEqual(expect.objectContaining({
    boundary_status: 'selected', location_role: 'onsite', scope: 'scope_1', direction: 'emission',
  }));
  // The CO2 rule was pending: applying moved its boundary to selected and kept its Scope.
  const carbon = rules.find(rule => rule.exchange_id === 'p-steelmaking::e9');
  expect(carbon?.boundary_status).toBe('selected');
  expect(carbon?.scope).toBe('scope_1');
  // The already-classified electricity rule is never overridden by a suggestion.
  expect(rules.find(rule => rule.exchange_id === 'p-steelmaking::e1')).toEqual(power);
});

it('lists a result category by its own type and category summary, and marks a legacy scheme read-only', async () => {
  mount('/applications/app-steel/calculation-methods', { methods: [tagMethod, legacyMethod, method] });
  const row = (await screen.findByText('能源标签')).closest('tr') as HTMLElement;
  expect(within(row).getByText('结果分类')).toBeInTheDocument();
  expect(within(row).getByText('购入能源、现场排放')).toBeInTheDocument();
  const legacyRow = screen.getByText('旧能源标签').closest('tr') as HTMLElement;
  expect(within(legacyRow).getByText('标签方案（旧，只读）')).toBeInTheDocument();
  const methodRow = screen.getByText('我的产品碳足迹方法').closest('tr') as HTMLElement;
  expect(within(methodRow).getByText('核算方法')).toBeInTheDocument();
  expect(within(methodRow).queryByText('结果分类')).toBeNull();
});

it('opens a result category workspace without a Scope editor or an inclusion switch', async () => {
  mount('/applications/app-steel/calculation-methods?method=t1', { methods: [tagMethod], detail: tagDetail });
  expect(await screen.findByRole('button', { name: '添加结果分类' })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: '添加类别维度' })).toBeNull();
  expect(screen.queryByLabelText('是否计入')).toBeNull();
});

it('assigns a flow to a leaf category and saves the assignment as one exact rule', async () => {
  mount('/applications/app-steel/calculation-methods?method=t1', { methods: [tagMethod], detail: tagDetail });
  const save = vi.spyOn(api, 'saveCalculationMethodVersion').mockResolvedValue(tagDetail);
  const powerRow = (await screen.findByText('电力')).closest('tr') as HTMLElement;
  expect(within(powerRow).getByText('购入能源')).toBeInTheDocument();
  const methane = (await screen.findByText('甲烷')).closest('tr') as HTMLElement;
  // The row keeps all three choices: "无" plus the declared leaves, nothing role-dependent.
  fireEvent.click(within(methane).getByLabelText('结果分类'));
  expect(await screen.findByRole('option', { name: '无' })).toBeInTheDocument();
  fireEvent.click(await screen.findByRole('option', { name: '现场排放' }));
  fireEvent.click(screen.getByRole('button', { name: '保存为新版本' }));
  await waitFor(() => expect(save).toHaveBeenCalledOnce());
  const payload = save.mock.calls[0][2];
  expect(payload.semantics).toBe('result_category.v1');
  expect(payload.reporting_dimensions).toEqual(tagDimensions);
  expect(payload.rules).toContainEqual(expect.objectContaining({
    exchange_id: 'p-steelmaking::e10', boundary_status: 'selected', scope: null, categories: { result_category: 'result_category_2' },
  }));
  // The already-assigned electricity flow keeps its saved category untouched.
  expect(payload.rules).toContainEqual(tagRule);
});

it('removes the relation when the reader chooses 无 for an assigned flow', async () => {
  mount('/applications/app-steel/calculation-methods?method=t1', { methods: [tagMethod], detail: tagDetail });
  const save = vi.spyOn(api, 'saveCalculationMethodVersion').mockResolvedValue(tagDetail);
  const powerRow = (await screen.findByText('电力')).closest('tr') as HTMLElement;
  fireEvent.click(within(powerRow).getByLabelText('结果分类'));
  fireEvent.click(await screen.findByRole('option', { name: '无' }));
  fireEvent.click(screen.getByRole('button', { name: '保存为新版本' }));
  await waitFor(() => expect(save).toHaveBeenCalledOnce());
  // "无" is no relation at all: the rule is dropped, not stored as an empty category.
  expect(save.mock.calls[0][2].rules).toEqual([]);
});

it('batch assigns a category to the selected flows and only then shows the batch bar', async () => {
  mount('/applications/app-steel/calculation-methods?method=t1', { methods: [tagMethod], detail: tagDetail });
  // The persistent footer explains selection before the first checkbox is selected.
  expect(await screen.findByLabelText('批量结果分类')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '应用到所选' })).toBeDisabled();
  fireEvent.click(await screen.findByRole('checkbox', { name: '已选 1 条 电力' }));
  fireEvent.click(screen.getByRole('checkbox', { name: '已选 1 条 甲烷' }));
  expect(screen.getByText('已选 2 条')).toBeInTheDocument();
  fireEvent.click(screen.getByLabelText('批量结果分类'));
  fireEvent.click(await screen.findByRole('option', { name: '现场排放' }));
  fireEvent.click(screen.getByRole('button', { name: '应用到所选' }));
  const save = vi.spyOn(api, 'saveCalculationMethodVersion').mockResolvedValue(tagDetail);
  fireEvent.click(screen.getByRole('button', { name: '保存为新版本' }));
  await waitFor(() => expect(save).toHaveBeenCalledOnce());
  const rules = save.mock.calls[0][2].rules;
  expect(rules).toContainEqual(expect.objectContaining({
    exchange_id: 'p-steelmaking::e1', categories: { result_category: 'result_category_2' },
  }));
  expect(rules).toContainEqual(expect.objectContaining({
    exchange_id: 'p-steelmaking::e10', boundary_status: 'selected', categories: { result_category: 'result_category_2' },
  }));
  // The unselected CO2 flow is untouched.
  expect(rules.some(rule => rule.exchange_id === 'p-steelmaking::e9')).toBe(false);
});

it('adds and deletes categories, naming how many assignments the delete affects', async () => {
  mount('/applications/app-steel/calculation-methods?method=t1', { methods: [tagMethod], detail: tagDetail });
  await screen.findByRole('button', { name: '添加结果分类' });
  const manager = document.querySelector('.tag-scheme__category-inline') as HTMLElement;
  expect(within(manager).getByText('1 条归属')).toBeInTheDocument();
  fireEvent.click(within(manager).getByRole('button', { name: '添加结果分类' }));
  fireEvent.change(within(manager).getAllByPlaceholderText('分类名称')[2], { target: { value: '蒸汽' } });
  const electricity = within(manager).getByDisplayValue('购入能源').closest('.tag-scheme__cat-row') as HTMLElement;
  fireEvent.click(within(electricity).getByRole('button', { name: '删除' }));
  const confirm = await findOpenDialog();
  expect(within(confirm).getByText('“购入能源”被 1 条归属引用。删除前请选择重新归类或设为“无”。')).toBeInTheDocument();
  await userEvent.click(within(confirm).getByRole('combobox', { name: '这些归属如何处理' }));
  fireEvent.click(await screen.findByRole('option', { name: '现场排放' }));
  fireEvent.click(within(confirm).getByRole('button', { name: '删除分类' }));
  await waitFor(() => expect(openDialogs()).toHaveLength(0));
  const save = vi.spyOn(api, 'saveCalculationMethodVersion').mockResolvedValue(tagDetail);
  fireEvent.click(screen.getByRole('button', { name: '保存为新版本' }));
  await waitFor(() => expect(save).toHaveBeenCalledOnce());
  const payload = save.mock.calls[0][2];
  expect(payload.reporting_dimensions?.[0].categories).toEqual([
    { id: 'result_category_2', name: '现场排放', is_leaf: true },
    { id: 'result_category_3', name: '蒸汽', parent_id: null, is_leaf: true },
  ]);
  // Reclassification moves the referencing rule onto the chosen leaf instead of dangling.
  expect(payload.rules).toContainEqual(expect.objectContaining({
    exchange_id: 'p-steelmaking::e1', categories: { result_category: 'result_category_2' },
  }));
});

it('removes the relations before deleting a category instead of leaving a dangling reference', async () => {
  mount('/applications/app-steel/calculation-methods?method=t1', { methods: [tagMethod], detail: tagDetail });
  await screen.findByRole('button', { name: '添加结果分类' });
  const manager = document.querySelector('.tag-scheme__category-inline') as HTMLElement;
  const electricity = within(manager).getByDisplayValue('购入能源').closest('.tag-scheme__cat-row') as HTMLElement;
  fireEvent.click(within(electricity).getByRole('button', { name: '删除' }));
  const confirm = await findOpenDialog();
  // 无 is the default: the flow leaves the caliber, never keeping a dangling id.
  fireEvent.click(within(confirm).getByRole('button', { name: '删除分类' }));
  await waitFor(() => expect(openDialogs()).toHaveLength(0));
  const save = vi.spyOn(api, 'saveCalculationMethodVersion').mockResolvedValue(tagDetail);
  fireEvent.click(screen.getByRole('button', { name: '保存为新版本' }));
  await waitFor(() => expect(save).toHaveBeenCalledOnce());
  expect(save.mock.calls[0][2].rules).toEqual([]);
});

it('keeps a legacy tag scheme read-only and converts it into an independent result category', async () => {
  mount('/applications/app-steel/calculation-methods?method=t0', { methods: [legacyMethod], detail: legacyDetail,
    capabilities: { ...capabilities, method_id: 't0', semantics: 'flow_tag.v1', purpose: 'custom',
      legacy_tag_scheme: true, conversion_available: true, tag_scheme: true } });
  expect(await screen.findByText(/旧标签方案保持原样只读/)).toBeInTheDocument();
  expect(screen.getByText('旧标签方案只读，可预览并转换为结果分类。')).toBeInTheDocument();
  // A legacy scheme is never edited in place: no save, no category management, no per-flow dropdown.
  expect(screen.queryByRole('button', { name: '保存为新版本' })).toBeNull();
  expect(screen.queryByRole('button', { name: '管理分类' })).toBeNull();
  expect(screen.queryByLabelText('结果分类')).toBeNull();
  // The old presence reading is preserved verbatim for the flows it already matched.
  expect(within((screen.getByText('电力')).closest('tr') as HTMLElement).getByText('购入能源')).toBeInTheDocument();

  const preview = vi.spyOn(api, 'resultCategoryConversionPreviewMapping').mockResolvedValue({
    source_method_id: 't0', source_method_name: '旧能源标签', source_version: 1,
    source_semantics: 'flow_tag.v1', source_content_sha256: 'b'.repeat(64),
    source_dimensions: [{ id: 'tag', name: '分类', category_count: 1, rule_count: 1 }],
    source_dimension_id: 'tag', target_semantics: 'result_category.v1', target_dimension_id: 'tag',
    dimension: legacyDetail.versions[0].reporting_dimensions![0],
    counts: { total: 2, assigned: 1, selected_without_category: 1, pending: 0, excluded: 0,
      invalid_category: 0, unresolved_invalid: 0, resolved_without_category: 0 },
    rules: [{ rule_index: 0, process_instance_id: 'p-steelmaking', exchange_id: 'p-steelmaking::e1', flow_uuid: 'power',
      old_category: 'tag_category_1', new_category: 'tag_category_1', outcome: 'assigned',
      needs_resolution: false, resolved: false }],
    problems: [], can_convert: true, reason: null, mapping_sha256: 'd'.repeat(64),
  });
  const convert = vi.spyOn(api, 'convertToResultCategory').mockResolvedValue({
    ...legacyDetail, method: { ...legacyMethod, id: 't2', name: '旧能源标签（结果分类）', semantics: 'result_category.v1' },
  });
  fireEvent.click(screen.getByRole('button', { name: '转换为结果分类' }));
  const dialog = await findOpenDialog();
  expect(await within(dialog).findByText('将“旧能源标签” v1 转换为独立的结果分类口径。原方法不会被修改。')).toBeInTheDocument();
  expect(within(dialog).getByText('1 条归属会带入新口径。')).toBeInTheDocument();
  expect(within(dialog).getByText('1 条旧“已选但未分类”会变为“无”，不进入新口径。')).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole('button', { name: '创建结果分类口径' }));
  await waitFor(() => expect(preview).toHaveBeenCalledWith('t0', 1, expect.objectContaining({ resolutions: [] })));
  await waitFor(() => expect(convert).toHaveBeenCalledWith('t0', 1, expect.objectContaining({
    name: '旧能源标签（结果分类）', expected_mapping_sha256: 'd'.repeat(64), resolutions: [],
  })));
  await waitFor(() => expect(openDialogs()).toHaveLength(0));
});

it('keeps a pre-caliber ordinary method read-only instead of reopening the inclusion editor', async () => {
  const ordinaryMethod: CalculationMethod = {
    ...legacyMethod, id: 'm9', name: '旧普通方法', semantics: null, purpose: 'custom',
  };
  const ordinaryDetail: CalculationMethodDetail = {
    method: ordinaryMethod,
    latest_version: 1,
    versions: [{
      ...legacyDetail.versions[0], id: 'm9v1', method_id: 'm9', semantics: null, reporting_dimensions: [],
      rules: [
        { ...tagRule, categories: {}, scope: 'scope_1', location_role: 'onsite', boundary_status: 'selected' },
        { ...tagRule, exchange_id: 'p-steelmaking::e10', flow_uuid: 'ch4', categories: {}, scope: 'scope_2',
          location_role: 'purchased_energy', boundary_status: 'excluded' },
      ],
    }],
  };
  mount('/applications/app-steel/calculation-methods?method=m9', { methods: [ordinaryMethod], detail: ordinaryDetail,
    capabilities: { ...capabilities, method_id: 'm9', method_name: '旧普通方法', semantics: null, purpose: 'custom',
      latest_version: 1, legacy_method: true, conversion_available: true } });
  expect(await screen.findByText(/旧普通方法保持原样只读/)).toBeInTheDocument();
  expect(screen.getAllByText('旧普通方法（只读）').length).toBeGreaterThanOrEqual(2);
  // The old inclusion editor and its per-flow Scope column are gone, not merely hidden behind a flag.
  expect(screen.queryByText('是否计入')).toBeNull();
  expect(screen.queryByRole('button', { name: '保存为新版本' })).toBeNull();
  expect(screen.queryByRole('button', { name: '管理分类' })).toBeNull();
  expect(screen.queryByLabelText('结果分类')).toBeNull();
  expect(screen.getByText('旧范围分布')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '转换为结果分类' })).toBeInTheDocument();
});

it('blocks conversion while an invalid legacy category is unmapped and applies the chosen mapping', async () => {
  mount('/applications/app-steel/calculation-methods?method=t0', { methods: [legacyMethod], detail: legacyDetail,
    capabilities: { ...capabilities, method_id: 't0', semantics: 'flow_tag.v1', purpose: 'custom',
      legacy_tag_scheme: true, conversion_available: true, tag_scheme: true } });
  const dimension = { id: 'tag', name: '分类', categories: [
    { id: 'tag_category_1', name: '购入能源', is_leaf: true },
    { id: 'tag_category_2', name: '现场排放', is_leaf: true },
  ] };
  const blocked = {
    source_method_id: 't0', source_method_name: '旧能源标签', source_version: 1,
    source_semantics: 'flow_tag.v1', source_content_sha256: 'b'.repeat(64),
    source_dimensions: [{ id: 'tag', name: '分类', category_count: 2, rule_count: 1 }],
    source_dimension_id: 'tag', target_semantics: 'result_category.v1', target_dimension_id: 'tag',
    dimension,
    counts: { total: 1, assigned: 0, selected_without_category: 0, pending: 0, excluded: 0,
      invalid_category: 1, unresolved_invalid: 1, resolved_without_category: 0 },
    rules: [{ rule_index: 0, process_instance_id: 'p-steelmaking', exchange_id: 'p-steelmaking::e1',
      flow_uuid: 'power', old_category: 'ghost', new_category: null, outcome: 'invalid_category' as const,
      needs_resolution: true, resolved: false }],
    problems: [{ code: 'TAG_SCHEME_CONVERSION_CATEGORY_INVALID', message: 'mapping required', rule_index: 0 }],
    can_convert: false, reason: { code: 'TAG_SCHEME_CONVERSION_UNRESOLVED_MAPPING', message: 'unresolved' },
    mapping_sha256: 'e'.repeat(64),
  };
  const resolved = {
    ...blocked,
    counts: { ...blocked.counts, assigned: 1, unresolved_invalid: 0 },
    rules: [{ ...blocked.rules[0], new_category: 'tag_category_2', outcome: 'assigned' as const,
      needs_resolution: false, resolved: true }],
    problems: [],
    can_convert: true,
    mapping_sha256: 'f'.repeat(64),
  };
  const preview = vi.spyOn(api, 'resultCategoryConversionPreviewMapping')
    .mockResolvedValueOnce(blocked)
    .mockResolvedValueOnce(resolved);
  const convert = vi.spyOn(api, 'convertToResultCategory').mockResolvedValue({
    ...legacyDetail, method: { ...legacyMethod, id: 't2', name: '旧能源标签（结果分类）', semantics: 'result_category.v1' },
  });
  fireEvent.click(await screen.findByRole('button', { name: '转换为结果分类' }));
  const dialog = await findOpenDialog();
  expect(await within(dialog).findByText('1 条旧归属需要处理')).toBeInTheDocument();
  // The flow is named from the exact model data, never by an exchange id.
  expect(within(dialog).getByText('炼钢 / 电力')).toBeInTheDocument();
  expect(within(dialog).getByText('还有 1 条旧归属未处理，处理前无法转换。')).toBeInTheDocument();
  expect(within(dialog).getByRole('button', { name: '创建结果分类口径' })).toBeDisabled();
  await userEvent.click(within(dialog).getByRole('combobox', { name: '第 1 条旧归属' }));
  fireEvent.click(await screen.findByRole('option', { name: '现场排放' }));
  await waitFor(() => expect(preview).toHaveBeenCalledTimes(2));
  expect(preview.mock.calls[1][2]).toEqual(expect.objectContaining({
    resolutions: [{ rule_index: 0, category: 'tag_category_2' }],
  }));
  await waitFor(() => expect(within(dialog).getByText('1 条归属会带入新口径。')).toBeInTheDocument());
  fireEvent.click(within(dialog).getByRole('button', { name: '创建结果分类口径' }));
  await waitFor(() => expect(convert).toHaveBeenCalledWith('t0', 1, expect.objectContaining({
    resolutions: [{ rule_index: 0, category: 'tag_category_2' }],
    expected_mapping_sha256: 'f'.repeat(64),
  })));
});

it('collects target categories before converting a scope-only legacy method', async () => {
  mount('/applications/app-steel/calculation-methods?method=t0', { methods: [legacyMethod], detail: {
    ...legacyDetail,
    versions: [{ ...legacyDetail.versions[0], reporting_dimensions: [] }],
  }, capabilities: { ...capabilities, method_id: 't0', semantics: 'flow_tag.v1', purpose: 'custom',
    legacy_tag_scheme: true, conversion_available: true, tag_scheme: true } });
  const needsTarget = {
    source_method_id: 't0', source_method_name: '旧能源标签', source_version: 1,
    source_semantics: 'flow_tag.v1', source_content_sha256: 'b'.repeat(64),
    source_dimensions: [], source_dimension_id: null,
    target_semantics: 'result_category.v1', target_dimension_id: null, dimension: null,
    counts: { total: 1, assigned: 0, selected_without_category: 0, pending: 0, excluded: 0,
      invalid_category: 1, unresolved_invalid: 1, resolved_without_category: 0 },
    rules: [{ rule_index: 0, process_instance_id: 'p-steelmaking', exchange_id: 'p-steelmaking::e1',
      flow_uuid: 'power', old_category: null, new_category: null, outcome: 'invalid_category' as const,
      needs_resolution: true, resolved: false }],
    problems: [{ code: 'TAG_SCHEME_CONVERSION_CATEGORY_REQUIRED', message: 'target required', rule_index: 0 }],
    can_convert: false, reason: { code: 'TAG_SCHEME_CONVERSION_TARGET_REQUIRED', message: 'target required' },
    mapping_sha256: 'a'.repeat(64),
  };
  const preview = vi.spyOn(api, 'resultCategoryConversionPreviewMapping').mockResolvedValue(needsTarget);
  fireEvent.click(await screen.findByRole('button', { name: '转换为结果分类' }));
  const dialog = await findOpenDialog();
  expect(await within(dialog).findByText(/旧方法没有分类树/)).toBeInTheDocument();
  expect(within(dialog).getByRole('button', { name: '创建结果分类口径' })).toBeDisabled();
  fireEvent.click(within(dialog).getByRole('button', { name: '添加分类' }));
  fireEvent.change(within(dialog).getByLabelText('分类 1'), { target: { value: '现场排放' } });
  await waitFor(() => expect(preview).toHaveBeenLastCalledWith('t0', 1, expect.objectContaining({
    target_dimension: expect.objectContaining({
      categories: [expect.objectContaining({ name: '现场排放', is_leaf: true })],
    }),
  })));
});

it('asks the server whether a package can be chosen at all before requesting the package list', async () => {
  const packages = vi.spyOn(api, 'selectableProcessingPackages').mockResolvedValue([]);
  mount('/applications/app-steel/calculation-methods?method=m1', { capabilities: {
    ...capabilities, processing_package_selection: false,
    processing_package_reason: { code: 'METHOD_TEMPLATE_BINDING_MISSING', message: '该模型没有模板绑定。' },
  } });
  await openMore('来源与诊断');
  expect(await screen.findByText('当前模型没有可用于选择处理规则包的模板绑定；标签匹配、保存和历史查看不受影响。正式计算仍按项目模板流程进行。')).toBeInTheDocument();
  expect(screen.getByText('METHOD_TEMPLATE_BINDING_MISSING')).toBeInTheDocument();
  expect(screen.getByText(/该模型没有模板绑定。/)).toBeInTheDocument();
  expect(screen.queryByRole('combobox', { name: '处理规则包' })).toBeNull();
  // No 409/empty-list guessing: the package endpoint is never requested at all.
  expect(packages).not.toHaveBeenCalled();
});

it('never asks for processing packages on a result category source page', async () => {
  const packages = vi.spyOn(api, 'selectableProcessingPackages').mockResolvedValue([]);
  mount('/applications/app-steel/calculation-methods?method=t1', { methods: [tagMethod], detail: tagDetail,
    capabilities: { ...capabilities, semantics: 'result_category.v1', purpose: 'custom', result_category: true, tag_scheme: true } });
  await openMore('来源与诊断');
  expect(await screen.findByText('结果分类只做贡献归集，不绑定处理规则包。')).toBeInTheDocument();
  expect(screen.queryByRole('combobox', { name: '处理规则包' })).toBeNull();
  expect(packages).not.toHaveBeenCalled();
});

it('archives a scheme only after an explicit confirmation', async () => {
  mount('/applications/app-steel/calculation-methods?method=m1');
  const archive = vi.spyOn(api, 'archiveCalculationMethod').mockResolvedValue({ ...method, status: 'retired' });
  await openMore('归档方案');
  const dialog = await findOpenDialog();
  expect(within(dialog).getByText('归档后不再用于新的结果归集，历史版本和已有结果仍可查看。此操作不会删除模型、包或历史结果。')).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole('button', { name: '归档' }));
  await waitFor(() => expect(archive).toHaveBeenCalledWith('m1'));
});
