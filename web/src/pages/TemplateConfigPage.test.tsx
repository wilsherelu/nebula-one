import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import {cleanup, fireEvent, render, screen, waitFor, within} from '@testing-library/react';
import {MemoryRouter, Route, Routes, useLocation} from 'react-router-dom';
import {afterEach, expect, it, vi} from 'vitest';
import {api} from '../api/client';
import {templateMethodsApi, type TemplateAccountingMethod, type TemplateAccountingMethods,
  type TemplateMethodCopyResult, type TemplateSavePlan, type TemplateSaveResult} from '../api/templateMethods';
import {TemplateConfigPage} from './TemplateConfigPage';

vi.mock('./calculationMethods/MethodEditor', () => ({
  MethodEditor: (props: {applicationId: string; revisionId: string; methodId: string}) =>
    <output aria-label="规则编辑器">{`${props.applicationId}|${props.revisionId}|${props.methodId}`}</output>,
}));

/** What the aggregation returns for a working method that lives in the template's source application. */
function sourceCard(methodId: string, name: string, purpose: string,
                    group: TemplateAccountingMethod['method_group']): TemplateAccountingMethod {
  return {
    method_key: `source:${methodId}@1`, purpose, method_group: group, origin: 'source_user_method',
    display_name: {zh: name, en: name}, editable: true,
    actions: ['view', 'edit', 'save_draft', 'check'], base_method_ref: null,
    rule_source: {kind: 'user_method_rules', declared: [{exchange_id: 'blast-furnace::co2-bf-raceway-out', rule_paths: ['rules[0]']}],
      declared_count: 6, port_count: 28, undeclared_port_count: 22, declared_but_absent_from_model: [], provenance: []},
    coverage_gaps: [],
    user_method: {method_id: methodId, version: 1, content_sha256: '9'.repeat(64), status: 'draft',
      name, description: '复制自内置方案', origin_method_id: null, origin_method_version: null,
      model_processing_rules_ref: null, cbam_boundary_ref: 'boundary-1', rule_count: 6, reporting_dimension_count: 0},
    check: {status: 'not_validated', status_basis: 'method_version_status', problem_count: 0, problems: []},
  };
}

const payload: TemplateAccountingMethods = {
  schema_version: 'nebula_one.template-accounting-methods.v1',
  template: {
    id: 'steel', kind: 'seed', title: 'BF-BOF steel', version: '1.1.0', template_sha256: 'a'.repeat(64),
    display_name: {zh: '高炉—转炉钢铁', en: 'BF-BOF steel'}, official: true, editable: false,
    source_application_id: 'source-app', source_model_id: 'source-model', source_revision_id: 'source-revision',
    capabilities: ['mfa.solved.v1'], template_profile: null,
    method_package_refs: ['cbam.eu.iron-steel.bf-bof-direct-trial@1.2.3', 'missing.package@9.9.9'],
    unresolved_method_package_refs: ['missing.package@9.9.9'],
    model: {process_count: 5, port_count: 28, graph_sha256: 'b'.repeat(64), graph_basis: 'source_revision',
      graph_snapshot: {nodes: [], edges: []}},
  },
  methods: [
    {
      method_key: 'cbam.eu.iron-steel.bf-bof-direct-trial@1.2.3', purpose: 'cbam_trial', method_group: 'cbam',
      origin: 'official_package', display_name: {zh: 'CBAM 直接排放（钢铁）'}, editable: false,
      actions: ['view', 'copy_and_adjust'],
      base_method_ref: {package_id: 'cbam.eu.iron-steel.bf-bof-direct-trial', version: '1.2.3', content_sha256: 'c'.repeat(64)},
      rule_source: {
        kind: 'official_package_classification',
        declared: [{exchange_id: 'blast-furnace::co2-bf-raceway-out', rule_paths: ['classification_rules.direct'] }],
        declared_count: 6, port_count: 28, undeclared_port_count: 22, declared_but_absent_from_model: [],
        provenance: [{source_path: 'provenance.regulation', url: 'https://example.eu/cbam'}],
      },
      coverage_gaps: [{code: 'PACKAGE_PENDING_RULE', message: '电力间接排放待确认', source_path: 'pending_activity_rules', exchange_id: 'ore-sintering::grid-electricity-in'}],
      user_method: null, check: {status: 'gap', status_basis: 'official_package_declaration', problem_count: 1, problems: []},
      cbam_boundaries: [
        {id: 'boundary-1', name: '一号高炉边界', boundary_type: 'cbam_trial', status: 'frozen', period_id: null,
          method_package_ref: null, graph_sha256: 'b'.repeat(64), included_process_count: 5,
          included_flow_rule_count: 6, excluded_item_count: 0},
        {id: 'boundary-2', name: '二号转炉边界', boundary_type: 'cbam_trial', status: 'frozen', period_id: null,
          method_package_ref: null, graph_sha256: 'b'.repeat(64), included_process_count: 3,
          included_flow_rule_count: 4, excluded_item_count: 1},
      ],
    },
    {
      method_key: 'pcf.iron-steel.native-model-boundary@1.0.3', purpose: 'product_carbon_footprint', method_group: 'product',
      origin: 'official_package', display_name: {zh: '产品碳足迹（钢铁）'}, editable: false,
      actions: ['view', 'copy_and_adjust'],
      base_method_ref: {package_id: 'pcf.iron-steel.native-model-boundary', version: '1.0.3', content_sha256: 'd'.repeat(64)},
      rule_source: {kind: 'none', declared: [], declared_count: 0, port_count: 28, undeclared_port_count: 28, declared_but_absent_from_model: [], provenance: []},
      coverage_gaps: [{code: 'NO_PER_FLOW_DECLARATION', message: '没有逐流声明', source_path: 'classification_rules'}],
      user_method: null, check: {status: 'gap', status_basis: 'official_package_declaration', problem_count: 1, problems: []},
    },
    {
      method_key: 'user-method-1@3', purpose: 'organization', method_group: 'user', origin: 'template_user_method',
      display_name: null, editable: true, actions: ['view', 'edit', 'save_draft', 'check'], base_method_ref: null,
      rule_source: {kind: 'user_method_rules', declared: [{exchange_id: 'product::product-out', rule_paths: ['rules[0]']}],
        declared_count: 1, port_count: 28, undeclared_port_count: 27, declared_but_absent_from_model: [], provenance: []},
      coverage_gaps: [],
      user_method: {method_id: 'user-method-1', version: 3, content_sha256: 'e'.repeat(64), status: 'ready',
        name: '组织范围规则', description: null, origin_method_id: null, origin_method_version: null,
        model_processing_rules_ref: null, cbam_boundary_ref: null, rule_count: 1, reporting_dimension_count: 3},
      check: {status: 'not_validated', status_basis: 'template_snapshot', problem_count: 0, problems: []},
    },
    sourceCard('copied-method', 'CBAM·我的调整', 'cbam', 'cbam'),
  ],
  tasks: null,
  other_scheme_keys: [],
};

function Location() {const location = useLocation(); return <output aria-label="当前位置">{location.search}</output>;}

/** What the server offers to freeze when the reader saves this exact template version as their own. */
function savePlanFixture(overrides: Partial<TemplateSavePlan> = {}): TemplateSavePlan {
  return {
    schema_version: 'nebula_one.template-save.v1', template_id: 'steel', kind: 'seed', official: true,
    title: 'BF-BOF steel', version: '1.1.0', template_sha256: 'a'.repeat(64),
    suggested_title: 'BF-BOF steel · 我的模板', suggested_version: '1.1.1',
    source_application_id: 'source-app', source_model_id: 'source-model', source_revision_id: 'source-revision',
    expected_revision_sha256: 'f'.repeat(64),
    method_pins: [{package_id: 'cbam.eu.iron-steel.bf-bof-direct-trial', version: '1.2.3', content_sha256: 'c'.repeat(64)}],
    unresolved_method_package_refs: [],
    user_methods: [
      {method_id: 'copied-method', name: 'CBAM·我的调整', purpose: 'cbam', method_group: 'cbam', version: 1,
        content_sha256: '9'.repeat(64), status: 'ready', rule_count: 6, reporting_dimension_count: 0,
        cbam_boundary_ref: 'boundary-1', already_frozen_in_template: false, savable: true, blocking_reason: null},
      {method_id: 'draft-method', name: '未检查的组织范围', purpose: 'organization', method_group: 'user', version: 1,
        content_sha256: null, status: 'draft', rule_count: 0, reporting_dimension_count: 0,
        cbam_boundary_ref: null, already_frozen_in_template: false, savable: false,
        blocking_reason: 'METHOD_NOT_VALIDATED'},
    ],
    ...overrides,
  };
}

const savedResult: TemplateSaveResult = {
  schema_version: 'nebula_one.template-save.v1',
  template: {id: 'mine', title: '钢铁·我的模板', version: '1.1.1', template_sha256: '7'.repeat(64), kind: 'authored',
    user_method_count: 1, process_count: 5, field_count: 28},
  source_template: {template_id: 'steel', title: 'BF-BOF steel', version: '1.1.0', template_sha256: 'a'.repeat(64),
    source_application_id: 'source-app', source_model_id: 'source-model', source_revision_id: 'source-revision'},
  frozen_user_methods: [{method_id: 'copied-method', version: 1, content_sha256: '9'.repeat(64)}],
};

function mountSave(plan: TemplateSavePlan = savePlanFixture()) {
  mount();
  vi.spyOn(templateMethodsApi, 'savePlan').mockResolvedValue(plan);
  return vi.spyOn(templateMethodsApi, 'saveTemplate').mockResolvedValue(savedResult);
}

function mount(entry = '/templates/steel/config?tab=methods', methods = payload) {
  vi.spyOn(templateMethodsApi, 'forTemplate').mockResolvedValue(methods);
  vi.spyOn(api, 'revisions').mockResolvedValue([
    {id: 'source-revision', system_model_id: 'source-model', parent_revision_id: null, revision_number: 2,
      label: '定稿数据', revision_kind: 'data', graph_sha256: 'b'.repeat(64), content_sha256: 'f'.repeat(64),
      status: 'published', created_at: '', published_at: null},
  ] as never);
  render(<QueryClientProvider client={new QueryClient({defaultOptions: {queries: {retry: false}}})}>
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/templates/:templateId/config" element={<><TemplateConfigPage /><Location /></>} />
      </Routes>
    </MemoryRouter>
  </QueryClientProvider>);
}
afterEach(() => {cleanup(); vi.restoreAllMocks();});

it('shows the schemes this template version binds, in Chinese, grouped by purpose', async () => {
  mount();
  expect(await screen.findByRole('heading', {name: '高炉—转炉钢铁'})).toBeInTheDocument();
  expect(screen.getByText('内置模板')).toBeInTheDocument();
  expect(screen.getByRole('heading', {name: 'CBAM'})).toBeInTheDocument();
  expect(screen.getByRole('heading', {name: '产品碳足迹'})).toBeInTheDocument();
  expect(screen.getByRole('heading', {name: '我的方案'})).toBeInTheDocument();
  expect(screen.getByRole('heading', {name: 'CBAM 直接排放（钢铁）'})).toBeInTheDocument();
  // A bound package that cannot be resolved is stated in business words; its ref stays collapsed.
  expect(screen.getByText('有 1 个绑定的方案包无法解析，它们的规则没有出现在本页。')).toBeInTheDocument();
  const unresolved = screen.getByText(/有绑定的方法包无法解析/).closest('details') as HTMLDetailsElement;
  expect(unresolved.open).toBe(false);
  expect(within(unresolved).getByText('missing.package@9.9.9')).toBeInTheDocument();
});

it('names a scheme the interface has no fixed term for instead of printing the enum', async () => {
  const odd: TemplateAccountingMethods = {...payload, methods: [{
    ...payload.methods[0], method_key: 'odd.package@0.0.1', purpose: 'some_new_purpose',
    display_name: null, cbam_boundaries: [],
    check: {status: 'partially_checked', status_basis: 'official_package_declaration', problem_count: 0, problems: []},
  }]};
  mount('/templates/steel/config?tab=methods', odd);
  const card = (await screen.findByRole('heading', {name: '未命名方案'})).closest('section') as HTMLElement;
  expect(within(card).getByText('检查状态未识别')).toBeInTheDocument();
  // The raw enums are still readable, but only in the source disclosure.
  const disclosure = within(card).getByText('来源与版本').closest('details') as HTMLDetailsElement;
  expect(disclosure.open).toBe(false);
  expect(within(disclosure).getByText('some_new_purpose')).toBeInTheDocument();
  expect(within(disclosure).getByText('partially_checked')).toBeInTheDocument();
  expect(within(disclosure).getByText(/official_package_declaration/)).toBeInTheDocument();
});

it('keeps package identifiers inside the collapsed source disclosure', async () => {
  mount();
  await screen.findByRole('heading', {name: 'CBAM 直接排放（钢铁）'});
  const disclosure = screen.getAllByText('来源与版本')[0].closest('details') as HTMLDetailsElement;
  expect(disclosure.open).toBe(false);
  expect(within(disclosure).getByText('cbam.eu.iron-steel.bf-bof-direct-trial@1.2.3')).toBeInTheDocument();
  expect(within(disclosure).getByText('blast-furnace::co2-bf-raceway-out')).toBeInTheDocument();
});

it('states declared coverage and the undeclared remainder instead of implying completeness', async () => {
  mount();
  const card = (await screen.findByRole('heading', {name: 'CBAM 直接排放（钢铁）'})).closest('section') as HTMLElement;
  expect(within(card).getByText(/已声明 6 条过程流规则，模型共 28 个交换流/)).toBeInTheDocument();
  expect(within(card).getByText(/22 个交换流没有声明规则/)).toBeInTheDocument();
  const pcf = screen.getByRole('heading', {name: '产品碳足迹（钢铁）'}).closest('section') as HTMLElement;
  expect(within(pcf).getByText(/没有逐流规则声明/)).toBeInTheDocument();
});

it('opens the frozen template rules in the editor bound to the exact source revision', async () => {
  mount();
  const card = (await screen.findByRole('heading', {name: '组织范围规则'})).closest('section') as HTMLElement;
  fireEvent.click(within(card).getByRole('button', {name: '编辑'}));
  expect(await screen.findByLabelText('规则编辑器')).toHaveTextContent('source-app|source-revision|user-method-1');
  await waitFor(() => expect(screen.getByLabelText('当前位置')).toHaveTextContent('method=user-method-1'));
});

it('offers no edit action on an official package scheme', async () => {
  mount();
  const card = (await screen.findByRole('heading', {name: 'CBAM 直接排放（钢铁）'})).closest('section') as HTMLElement;
  expect(within(card).getByRole('button', {name: '查看来源'})).toBeInTheDocument();
  expect(within(card).queryByRole('button', {name: '编辑'})).not.toBeInTheDocument();
  expect(within(card).getByRole('button', {name: '复制并调整'})).toBeInTheDocument();
});

it('reopens a copied scheme after a refresh, bound to the same exact revision', async () => {
  mount();
  const card = (await screen.findByRole('heading', {name: 'CBAM·我的调整'})).closest('section') as HTMLElement;
  // A working method of your own is edited in place; the copy action belongs to the official schemes only.
  expect(within(card).queryByRole('button', {name: '复制并调整'})).not.toBeInTheDocument();
  fireEvent.click(within(card).getByRole('button', {name: '编辑'}));
  expect(await screen.findByLabelText('规则编辑器')).toHaveTextContent('source-app|source-revision|copied-method');
});

it('copies an official scheme under a name the reader gives and opens the copy', async () => {
  mount();
  // The workspace re-reads after a copy, so the new draft has to appear in the aggregation for the
  // editor to open it: a copy that only returns an id would be unreachable after a refresh.
  let current = payload;
  vi.mocked(templateMethodsApi.forTemplate).mockImplementation(() => Promise.resolve(current));
  const copy = vi.spyOn(templateMethodsApi, 'copyOfficial').mockImplementation(async (_id, request) => {
    current = {...current, methods: [...current.methods, sourceCard('new-copy', request.name, 'cbam', 'cbam')]};
    return {
      schema_version: 'nebula_one.template-method-copy.v1',
      method: {method: {id: 'new-copy', name: request.name, purpose: 'cbam'}, latest_version: 1, versions: []} as never,
      transcription: {
        template_id: 'steel', method_key: 'cbam.eu.iron-steel.bf-bof-direct-trial@1.2.3', package_kind: 'cbam_trial',
        purpose: 'cbam', base_method_ref: {package_id: 'cbam.eu.iron-steel.bf-bof-direct-trial', version: '1.2.3', content_sha256: 'c'.repeat(64)},
        application_id: 'source-app', model_revision_id: 'source-revision', cbam_boundary_ref: 'boundary-2',
        rule_count: 7, port_count: 28, undeclared_port_count: 21, declared_but_absent_from_model: [],
        declared_exchange_ids: [], reporting_dimensions: [], reference_product_exchange_id: 'continuous-casting::crude-steel-slab-out',
        notes: [{code: 'PACKAGE_PENDING_RULE', message: '电力间接排放待确认，未替你决定', source_path: 'pending_activity_rules', exchange_id: 'ore-sintering::grid-electricity-in', clause: 'ST-12'}],
      },
    };
  });
  const card = (await screen.findByRole('heading', {name: 'CBAM 直接排放（钢铁）'})).closest('section') as HTMLElement;
  const listed = vi.mocked(templateMethodsApi.forTemplate).mock.calls.length;
  fireEvent.click(within(card).getByRole('button', {name: '复制并调整'}));
  const dialog = await screen.findByRole('dialog');
  expect(within(dialog).getByLabelText('方案名称')).toHaveValue('CBAM 直接排放（钢铁） · 我的调整');
  expect(within(dialog).getByText(/副本会带上内置方案已声明的 6 条逐流规则（模型共 28 个交换流）/)).toBeInTheDocument();
  // Two frozen boundaries exist, so the copy must not silently pick one.
  expect(within(dialog).getByRole('button', {name: '创建副本'})).toBeDisabled();
  fireEvent.click(within(dialog).getByLabelText('CBAM 冻结边界'));
  // A stored boundary name can be an engineering record name, so the choice reads as what the frozen
  // boundary actually covers; the two boundaries here differ by their own counts, not by a label.
  fireEvent.click(await screen.findByRole('option', {name: 'CBAM 冻结边界（3 个过程 · 4 条流规则）'}));
  const boundarySource = within(dialog).getByText('来源与版本').closest('details') as HTMLDetailsElement;
  expect(boundarySource.open).toBe(false);
  expect(within(boundarySource).getByText('二号转炉边界')).toBeInTheDocument();
  expect(within(boundarySource).getByText('boundary-2')).toBeInTheDocument();
  fireEvent.change(within(dialog).getByLabelText('方案名称'), {target: {value: 'CBAM·排除电力'}});
  fireEvent.click(within(dialog).getByRole('button', {name: '创建副本'}));
  await waitFor(() => expect(copy).toHaveBeenCalledOnce());
  expect(copy.mock.calls[0]).toEqual(['steel', {
    method_key: 'cbam.eu.iron-steel.bf-bof-direct-trial@1.2.3', name: 'CBAM·排除电力', cbam_boundary_ref: 'boundary-2',
  }]);
  expect(await screen.findByLabelText('规则编辑器')).toHaveTextContent('source-app|source-revision|new-copy');
  // The workspace re-reads the aggregation, so the new draft is still reachable after a refresh.
  await waitFor(() => expect(vi.mocked(templateMethodsApi.forTemplate).mock.calls.length).toBeGreaterThan(listed));
  // What the copy could not take over is stated, not hidden behind a success message.
  expect(screen.getByText('副本自述的 1 项说明')).toBeInTheDocument();
  expect(screen.getByText('电力间接排放待确认，未替你决定')).toBeInTheDocument();
  expect(screen.getByText('ST-12')).toBeInTheDocument();
});

it('refuses to submit a CBAM copy while the source has no frozen boundary', async () => {
  const withoutBoundary: TemplateAccountingMethods = {
    ...payload,
    methods: payload.methods.map(method => method.method_group === 'cbam' && method.origin === 'official_package'
      ? {...method, cbam_boundaries: []} : method),
  };
  vi.spyOn(templateMethodsApi, 'forTemplate').mockResolvedValue(withoutBoundary);
  const copy = vi.spyOn(templateMethodsApi, 'copyOfficial');
  render(<QueryClientProvider client={new QueryClient({defaultOptions: {queries: {retry: false}}})}>
    <MemoryRouter initialEntries={['/templates/steel/config?tab=methods']}>
      <Routes><Route path="/templates/:templateId/config" element={<TemplateConfigPage />} /></Routes>
    </MemoryRouter>
  </QueryClientProvider>);
  const card = (await screen.findByRole('heading', {name: 'CBAM 直接排放（钢铁）'})).closest('section') as HTMLElement;
  fireEvent.click(within(card).getByRole('button', {name: '复制并调整'}));
  const dialog = await screen.findByRole('dialog');
  expect(within(dialog).getByText(/还没有冻结的 CBAM 边界/)).toBeInTheDocument();
  fireEvent.change(within(dialog).getByLabelText('方案名称'), {target: {value: 'CBAM·尝试'}});
  expect(within(dialog).getByRole('button', {name: '创建副本'})).toBeDisabled();
  expect(copy).not.toHaveBeenCalled();
});

it('copies a scheme with no per-flow declaration as an empty draft that says so', async () => {
  mount();
  let current = payload;
  vi.mocked(templateMethodsApi.forTemplate).mockImplementation(() => Promise.resolve(current));
  const copy = vi.spyOn(templateMethodsApi, 'copyOfficial').mockImplementation(async (_id, request) => {
    current = {...current, methods: [...current.methods, sourceCard('pcf-copy', request.name, 'pcf', 'product')]};
    return {
      schema_version: 'nebula_one.template-method-copy.v1',
      method: {method: {id: 'pcf-copy', name: request.name, purpose: 'pcf'}, latest_version: 1, versions: []} as never,
      transcription: {
        template_id: 'steel', method_key: 'pcf.iron-steel.native-model-boundary@1.0.3', package_kind: 'product_carbon_footprint',
        purpose: 'pcf', base_method_ref: {package_id: 'pcf.iron-steel.native-model-boundary', version: '1.0.3', content_sha256: 'd'.repeat(64)},
        application_id: 'source-app', model_revision_id: 'source-revision', cbam_boundary_ref: null,
        rule_count: 0, port_count: 28, undeclared_port_count: 28, declared_but_absent_from_model: [],
        declared_exchange_ids: [], reporting_dimensions: [], reference_product_exchange_id: null,
        notes: [{code: 'NO_PER_FLOW_DECLARATION', message: '副本从空规则开始，需要逐个流设置核算范围', source_path: 'classification_rules'}],
      },
    };
  });
  const card = (await screen.findByRole('heading', {name: '产品碳足迹（钢铁）'})).closest('section') as HTMLElement;
  fireEvent.click(within(card).getByRole('button', {name: '复制并调整'}));
  const dialog = await screen.findByRole('dialog');
  expect(within(dialog).getByText(/副本会带上内置方案已声明的 0 条逐流规则（模型共 28 个交换流）/)).toBeInTheDocument();
  // No CBAM boundary is asked for on a product-footprint copy.
  expect(within(dialog).queryByLabelText('CBAM 冻结边界')).not.toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole('button', {name: '创建副本'}));
  await waitFor(() => expect(copy).toHaveBeenCalledOnce());
  expect(copy.mock.calls[0][1]).toEqual({method_key: 'pcf.iron-steel.native-model-boundary@1.0.3',
    name: '产品碳足迹（钢铁） · 我的调整', cbam_boundary_ref: null});
  expect(await screen.findByLabelText('规则编辑器')).toHaveTextContent('source-app|source-revision|pcf-copy');
  expect(screen.getByText('副本从空规则开始，需要逐个流设置核算范围')).toBeInTheDocument();
});

it('saves this exact template version with the working schemes the reader ticks', async () => {
  const save = mountSave();
  const invalidate = vi.spyOn(QueryClient.prototype, 'invalidateQueries');
  fireEvent.click(await screen.findByRole('button', {name: '保存为我的模板'}));
  const dialog = await screen.findByRole('dialog');
  // The name and version are offered, not asked from scratch: this is a confirmation, not a form.
  const name = await within(dialog).findByDisplayValue('BF-BOF steel · 我的模板');
  expect(within(dialog).getByLabelText('模板名称')).toBe(name);
  expect(within(dialog).getByLabelText('版本号')).toHaveDisplayValue('1.1.1');
  expect(within(dialog).getByText('一起冻结的内置方案：1 个')).toBeInTheDocument();
  expect(within(dialog).getByRole('checkbox', {name: /CBAM·我的调整/})).toBeChecked();
  const unchecked = within(dialog).getByRole('checkbox', {name: /未检查的组织范围/});
  expect(unchecked).not.toBeChecked();
  expect(unchecked).toBeDisabled();
  // A scheme that cannot be frozen says why in business words instead of disappearing.
  expect(within(dialog).getByText('还没通过检查，请先在方案编辑器里检查')).toBeInTheDocument();
  fireEvent.change(within(dialog).getByLabelText('模板名称'), {target: {value: '钢铁·我的模板'}});
  fireEvent.click(within(dialog).getByRole('button', {name: '保存模板'}));
  await waitFor(() => expect(save).toHaveBeenCalledOnce());
  expect(save.mock.calls[0]).toEqual(['steel', {title: '钢铁·我的模板', version: '1.1.1',
    user_methods: [{method_id: 'copied-method', version: 1, content_sha256: '9'.repeat(64)}]}]);
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(await screen.findByText('已保存为「钢铁·我的模板」1.1.1')).toBeInTheDocument();
  // The saved template has to show up in the catalogue without a manual reload.
  expect(invalidate.mock.calls.some(call => call[0]?.queryKey?.[0] === 'seed-project-templates')).toBe(true);
});

it('keeps a working scheme the reader unticks out of the frozen set', async () => {
  const save = mountSave();
  fireEvent.click(await screen.findByRole('button', {name: '保存为我的模板'}));
  const dialog = await screen.findByRole('dialog');
  fireEvent.click(await within(dialog).findByRole('checkbox', {name: /CBAM·我的调整/}));
  expect(within(dialog).getByText(/当前没有已通过检查的我的方案/)).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole('button', {name: '保存模板'}));
  await waitFor(() => expect(save).toHaveBeenCalledOnce());
  expect(save.mock.calls[0][1].user_methods).toEqual([]);
});

it('refuses to save while a bound official package cannot be resolved', async () => {
  const save = mountSave(savePlanFixture({method_pins: [], unresolved_method_package_refs: ['missing.package@9.9.9']}));
  fireEvent.click(await screen.findByRole('button', {name: '保存为我的模板'}));
  const dialog = await screen.findByRole('dialog');
  expect(await within(dialog).findByText(/有 1 个绑定的方案包无法解析，暂不能保存为我的模板：missing\.package@9\.9\.9/))
    .toBeInTheDocument();
  expect(within(dialog).getByRole('button', {name: '保存模板'})).toBeDisabled();
  expect(save).not.toHaveBeenCalled();
});

it('ignores a second submit while the save is still in flight', async () => {
  mount();
  vi.spyOn(templateMethodsApi, 'savePlan').mockResolvedValue(savePlanFixture());
  let release: (value: TemplateSaveResult) => void = () => {};
  const save = vi.spyOn(templateMethodsApi, 'saveTemplate')
    .mockImplementation(() => new Promise<TemplateSaveResult>(resolve => { release = resolve; }));
  fireEvent.click(await screen.findByRole('button', {name: '保存为我的模板'}));
  const dialog = await screen.findByRole('dialog');
  await within(dialog).findByDisplayValue('BF-BOF steel · 我的模板');
  const submit = within(dialog).getByRole('button', {name: '保存模板'});
  fireEvent.click(submit);
  fireEvent.click(submit);
  // One save request per save: a double click must not publish two templates.
  await waitFor(() => expect(save).toHaveBeenCalledOnce());
  release(savedResult);
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
});

it('says so when this template version binds no scheme at all', async () => {
  mount('/templates/steel/config?tab=methods', {...payload, methods: []});
  expect(await screen.findByText('这个模板版本还没有绑定核算方案。')).toBeInTheDocument();
  expect(screen.queryByRole('heading', {name: 'CBAM'})).not.toBeInTheDocument();
});

it('sends one copy request when the submit is clicked twice', async () => {
  mount();
  const copy = vi.spyOn(templateMethodsApi, 'copyOfficial')
    .mockImplementation(() => new Promise<TemplateMethodCopyResult>(() => {}));
  const card = (await screen.findByRole('heading', {name: '产品碳足迹（钢铁）'})).closest('section') as HTMLElement;
  fireEvent.click(within(card).getByRole('button', {name: '复制并调整'}));
  const submit = within(await screen.findByRole('dialog')).getByRole('button', {name: '创建副本'});
  fireEvent.click(submit);
  fireEvent.click(submit);
  // A double click must not create two methods with the same name.
  await waitFor(() => expect(copy).toHaveBeenCalledOnce());
});

it('shows model scale and the exact data version on the model tab', async () => {
  mount('/templates/steel/config?tab=model');
  expect(await screen.findByText('5 个过程 · 28 项清单数据')).toBeInTheDocument();
  fireEvent.click(screen.getByText('来源与版本'));
  expect(await screen.findByText('定稿数据')).toBeInTheDocument();
  expect(screen.getByText('当前上下文')).toBeInTheDocument();
});

/** A task-declaring scheme set: the backend groups the same flat methods into three reader tasks,
 * the organisation task binding two official presets behind one current default. */
function taskPayload(): TemplateAccountingMethods {
  const lifecycle: TemplateAccountingMethod = {
    method_key: 'nebula.organization-lifecycle-carbon.steel-model@1.0.10', purpose: 'organization_lifecycle_carbon',
    method_group: 'organization', origin: 'official_package', display_name: {zh: '生命周期范围分类'}, editable: false,
    actions: ['view', 'copy_and_adjust'],
    base_method_ref: {package_id: 'nebula.organization-lifecycle-carbon.steel-model', version: '1.0.10', content_sha256: '1'.repeat(64)},
    rule_source: {kind: 'official_package_classification', declared: [], declared_count: 8, port_count: 28,
      undeclared_port_count: 20, declared_but_absent_from_model: [], provenance: []},
    coverage_gaps: [], user_method: null,
    check: {status: 'ready', status_basis: 'official_package_declaration', problem_count: 0, problems: []},
  };
  const period: TemplateAccountingMethod = {
    method_key: 'ghg.iron-steel.organization-period-model@1.0.6', purpose: 'organization_period_inventory',
    method_group: 'organization', origin: 'official_package', display_name: {zh: '期间清单对照'}, editable: false,
    actions: ['view', 'copy_and_adjust'],
    base_method_ref: {package_id: 'ghg.iron-steel.organization-period-model', version: '1.0.6', content_sha256: '2'.repeat(64)},
    rule_source: {kind: 'official_package_classification', declared: [], declared_count: 6, port_count: 28,
      undeclared_port_count: 22, declared_but_absent_from_model: [], provenance: []},
    coverage_gaps: [], user_method: null,
    check: {status: 'ready', status_basis: 'official_package_declaration', problem_count: 0, problems: []},
  };
  const pcf: TemplateAccountingMethod = payload.methods[1];
  const cbam: TemplateAccountingMethod = payload.methods[0];
  return {
    ...payload,
    methods: [pcf, cbam, lifecycle, period],
    tasks: [
      {role: 'complete_model', default_ref: 'pcf.iron-steel.native-model-boundary@1.0.3',
        preset_keys: ['pcf.iron-steel.native-model-boundary@1.0.3'], user_scheme_keys: []},
      {role: 'cbam', default_ref: 'cbam.eu.iron-steel.bf-bof-direct-trial@1.2.3',
        preset_keys: ['cbam.eu.iron-steel.bf-bof-direct-trial@1.2.3'], user_scheme_keys: []},
      {role: 'scope_classification', default_ref: 'nebula.organization-lifecycle-carbon.steel-model@1.0.10',
        preset_keys: ['nebula.organization-lifecycle-carbon.steel-model@1.0.10', 'ghg.iron-steel.organization-period-model@1.0.6'],
        user_scheme_keys: []},
    ],
    other_scheme_keys: [],
  };
}

it('lists only the accounting rules in the rules tab, not the default LCIA as a card', async () => {
  mount('/templates/steel/config?tab=methods', taskPayload());
  // The rules tab declares only CBAM and 范围1–3 (plus user rules); each appears once.
  expect(await screen.findByRole('heading', {name: 'CBAM'})).toBeInTheDocument();
  expect(screen.getAllByRole('heading', {name: '范围1–3'})).toHaveLength(1);
  // The default LCIA is a calculation setting, not a rule: no 产品碳足迹 card here.
  expect(screen.queryByRole('heading', {name: '产品碳足迹'})).not.toBeInTheDocument();
  // Two official organisation presets still collapse into one 范围1–3 row, not a card each.
  expect(screen.queryByRole('heading', {name: '期间清单对照'})).not.toBeInTheDocument();
});

it('shows the default evaluation indicator on the model tab as a calculation setting', async () => {
  mount('/templates/steel/config?tab=model', taskPayload());
  expect(await screen.findByRole('heading', {name: '默认评价指标'})).toBeInTheDocument();
  // Reaching for the source opens the read-only indicator dialog, without any rule editor.
  fireEvent.click(screen.getByRole('button', {name: '查看来源'}));
  expect(await screen.findByRole('dialog')).toBeInTheDocument();
});

it('resolves the declared official LCIA before an earlier legacy characterization', async () => {
  const data = taskPayload();
  const detail = {jurisdiction: null, assurance_level: null, boundary_schema: {}, output_schema: {},
    accepted_units: {}, formula_graph: {lcia_method: 'declared-public-climate', result_unit: 'kg CO2-Eq'}};
  const selected = {...data.methods[0], method_key: `official:${data.tasks![0].default_ref}`, package_detail: detail};
  const legacy = {...selected, method_key: 'official:legacy@1.0.0', package_detail: {...detail,
    formula_graph: {...detail.formula_graph, lcia_method: 'legacy-characterization'}}};
  data.methods = [legacy, selected, ...data.methods.slice(1)];
  mount('/templates/steel/config?tab=model', data);
  expect(await screen.findByText('declared-public-climate')).toBeInTheDocument();
  expect(screen.queryByText('legacy-characterization')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', {name: '查看来源'}));
  expect(within(await screen.findByRole('dialog')).getByText('declared-public-climate')).toBeInTheDocument();
});

it('does not substitute a legacy LCIA for an unresolved declared default', async () => {
  const data = taskPayload();
  data.tasks![0].default_ref = 'missing-public-method@1.0.0';
  data.methods[0] = {...data.methods[0], package_detail: {jurisdiction: null, assurance_level: null,
    boundary_schema: {}, output_schema: {}, accepted_units: {}, formula_graph: {lcia_method: 'legacy-characterization'}}};
  mount('/templates/steel/config?tab=model', data);
  expect(await screen.findByText('定稿数据')).toBeInTheDocument();
  expect(screen.queryByText('legacy-characterization')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', {name: '查看来源'})).not.toBeInTheDocument();
});

it('creates a custom result category inside the template workspace without the legacy package catalogue', async () => {
  mount('/templates/steel/config?tab=methods', taskPayload());
  fireEvent.click(await screen.findByRole('button', {name: '新建结果分类'}));
  const dialog = await screen.findByRole('dialog');
  expect(within(dialog).getByPlaceholderText('分类名称')).toBeInTheDocument();
  expect(within(dialog).queryByText('核算目的')).not.toBeInTheDocument();
  const create = vi.spyOn(api, 'createCalculationMethod').mockRejectedValue(new Error('stop after request'));
  fireEvent.change(within(dialog).getByPlaceholderText('方法名称'), {target: {value: '地区分析'}});
  fireEvent.click(within(dialog).getByRole('button', {name: '创建并编辑'}));
  await waitFor(() => expect(create).toHaveBeenCalledWith('source-app', expect.objectContaining({
    name: '地区分析', semantics: 'result_category.v1', purpose: 'custom', model_revision_id: 'source-revision',
    reporting_dimensions: [expect.objectContaining({id: 'result_category'})],
  })));
  expect(screen.queryByText('内置计算配置与历史版本')).not.toBeInTheDocument();
});

it('offers no complete-model indicator action in the rules tab now that default LCIA left it', async () => {
  mount('/templates/steel/config?tab=methods', taskPayload());
  // No 产品碳足迹 rule row, so no 查看指标 forward action anywhere on the rules tab.
  expect(await screen.findByRole('heading', {name: 'CBAM'})).toBeInTheDocument();
  expect(screen.queryByRole('button', {name: '查看指标'})).not.toBeInTheDocument();
});

it('routes the CBAM task forward action to view-and-adjust, opening a copy for the official preset', async () => {
  mount('/templates/steel/config?tab=methods', taskPayload());
  const row = (await screen.findByRole('heading', {name: 'CBAM'})).closest('article') as HTMLElement;
  fireEvent.click(within(row).getByRole('button', {name: '查看与调整'}));
  // An official preset with no working copy yet opens the copy dialog from the task row.
  expect(await screen.findByRole('dialog')).toBeInTheDocument();
});

it('keeps the flat per-package view for an older template that binds no task-declaring scheme set', async () => {
  mount('/templates/steel/config?tab=methods', payload);
  // tasks is null, so the reader still sees the grouped cards rather than an empty task list.
  expect(await screen.findByRole('heading', {name: 'CBAM 直接排放（钢铁）'})).toBeInTheDocument();
  expect(screen.queryByRole('heading', {name: '完整模型计算'})).not.toBeInTheDocument();
});

it('adjusts the exact pinned direct component instead of creating an empty partial-review copy', async () => {
  const data = taskPayload();
  const direct = data.methods[1];
  const partial: TemplateAccountingMethod = {...direct, method_key: 'partial-review',
    package_detail: {jurisdiction: null, assurance_level: null, boundary_schema: {}, output_schema: {},
      accepted_units: {}, formula_graph: {source_direct_method: {
        reference: `${direct.base_method_ref!.package_id}@${direct.base_method_ref!.version}`,
        content_sha256: direct.base_method_ref!.content_sha256,
      }}}, display_name: {zh: '部分复核'}};
  data.methods.push(partial);
  data.tasks![1].preset_keys.unshift(partial.method_key);
  mount('/templates/steel/config?tab=methods', data);
  fireEvent.click(await screen.findByRole('button', {name: '调整直接排放'}));
  expect(await screen.findByRole('dialog')).toBeInTheDocument();
  expect(screen.getByLabelText('方案名称')).toHaveValue('CBAM 直接排放（钢铁） · 我的调整');
});

