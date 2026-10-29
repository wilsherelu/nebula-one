import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { api } from '../api/client';
import type { ProductCarbonFootprint } from '../api/types';
import { I18nProvider, LANGUAGE_STORAGE_KEY } from '../i18n';
import { ProductCarbonFootprintPanel } from './ProductCarbonFootprintPanel';
vi.mock('echarts-for-react', () => ({ default: () => <div data-testid="contribution-chart" /> }));

const result: ProductCarbonFootprint = {
  schema_version: 'nebula_one.pcf.product.v1', capability_key: 'pcf.product.v1',
  method_package: { reference: 'pcf.bound@1.0.0', content_sha256: 'method-hash', lcia_method: 'Bound method', total_indicator_key: 'climate-total' },
  source_snapshot: { id: 'snapshot-1', content_sha256: 'snapshot-hash' },
  functional_unit: { amount: 1, unit: 'kg' },
  total_footprint: { value: 2, unit: 'kg CO2-Eq', indicator_key: 'climate-total' },
  component_results: [],
  contribution_analysis: {
    status: 'available', coverage: 'exact_exchange_contributions', reason: null,
    indicator_receipt: { content_hash: 'receipt-hash', contribution_receipts_hash: 'receipts-hash', solve_hash: 'solve-hash', provider_commit: null, runtime_assets_hash: 'assets-hash', term_count: 1 },
    hotspots: [{ rank: 1, process_id: 'process-hotspot', exchange_id: 'exchange-hotspot', flow_identity: { source_namespace: 'ef31', flow_uuid: 'flow-1', version: '1' }, amount: 1, amount_unit: 'kg', contribution_value: 2, contribution_unit: 'kg CO2-Eq', share_of_total: 1, cf_hash: 'cf-hash' }],
  },
  boundary_claim: { claim_scope: 'foreground_boundary', coverage: 'foreground_only', complete_product_declaration: false },
  data_quality: {}, audit: { status: 'passed' }, provenance: {}, content_sha256: 'pcf-hash',
};

const baseProps = {
  applicationId: 'app-steel',
  revisionId: 'revision-1',
  snapshotId: 'snapshot-1',
  methodPackages: [{ reference: 'pcf.bound@1.0.0', label: 'Bound package' }],
  selectedMethodPackageRef: 'pcf.bound@1.0.0',
  onMethodPackageChange: vi.fn(),
  basis: { result_basis: 'total' as const },
  onBasisChange: vi.fn(),
  result,
  isLoading: false,
  error: null,
  onRetry: vi.fn(),
  chart: undefined,
  chartIsLoading: false,
  chartError: null,
  onChartRetry: vi.fn(),
};

function renderPanel(element: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrap = (node: ReactElement) => <MemoryRouter><QueryClientProvider client={client}>{node}</QueryClientProvider></MemoryRouter>;
  const rendered = render(wrap(element), { wrapper: I18nProvider });
  return { ...rendered, rerender: (node: ReactElement) => rendered.rerender(wrap(node)) };
}

beforeEach(() => {
  vi.spyOn(api, 'calculationMethods').mockResolvedValue([]);
  vi.spyOn(api, 'tagGroupingHistory').mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
  window.localStorage.removeItem(LANGUAGE_STORAGE_KEY);
  vi.restoreAllMocks();
});

describe('Product carbon footprint panel', () => {
  it('labels a known subtotal and lists unmatched flows without displaying fake zero contributions', () => {
    const partial: ProductCarbonFootprint = { ...result, data_quality: {
      characterization_coverage: { schema_version: 'provider.lcia.characterization-coverage.v1',
        status: 'partial', value_kind: 'known_subtotal', uncharacterized_exchanges: [
          { exchange_id: 'process::so2', flow_uuid: 'so2', amount: 0.2, amount_unit: 'kg', numeric_contribution: null },
        ] },
    } };
    renderPanel(<ProductCarbonFootprintPanel {...baseProps} result={partial} exchangeNames={{ 'process::so2': '二氧化硫' }} />);
    expect(screen.getAllByText('已匹配因子的贡献小计')).toHaveLength(2);
    expect(screen.getByText(/二氧化硫 · 0.2 kg/)).toBeInTheDocument();
    expect(screen.getByText(/缺因子不代表排放为零/)).toBeInTheDocument();
  });
  it('uses English result labels and a localized missing-name state without changing source identity', () => {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, 'en');
    renderPanel(<ProductCarbonFootprintPanel {...baseProps} />);
    expect(screen.getAllByText('Foreground climate change result')).toHaveLength(2);
    expect(screen.getByText('Process name unavailable')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Export' })).toBeInTheDocument();
    expect(screen.queryByText('process-hotspot')).not.toBeInTheDocument();
  });
  it('switches to the per-product basis with a defaulted mass base, reusing the same snapshot', async () => {
    const onBasisChange = vi.fn();
    renderPanel(<ProductCarbonFootprintPanel {...baseProps} onBasisChange={onBasisChange} />);
    // The reference output is a 1 kg mass, so per-product is available.
    await userEvent.click(screen.getByRole('radio', { name: '单位产品' }));
    expect(onBasisChange).toHaveBeenCalledWith({ result_basis: 'per_reference_output', base_amount: 1, base_unit: 'kg' });
  });
  it('disables the per-product basis and explains why when the reference output is not a mass unit', () => {
    const nonMass = { ...result, functional_unit: { amount: 1, unit: 'kWh' } } as ProductCarbonFootprint;
    renderPanel(<ProductCarbonFootprintPanel {...baseProps} result={nonMass} />);
    expect(screen.getByRole('radio', { name: '单位产品' })).toBeDisabled();
    expect(screen.getByText('该产品的参考产出不是受支持的质量单位（kg 或 t），暂时只能查看本次总量。')).toBeInTheDocument();
  });
  it('explains a native total without exposing an English audit reason in the main result', () => {
    const nativeTotal = { ...result, contribution_analysis: {
      status: 'unavailable' as const, coverage: 'total_only',
      reason: 'The pinned native answer exposes domain totals; product process hotspots are not asserted.',
      indicator_receipt: null, hotspots: [],
    } } as ProductCarbonFootprint;
    renderPanel(<ProductCarbonFootprintPanel {...baseProps} result={nativeTotal} />);
    expect(screen.getByText('当前冻结结果只提供气候总量或来源分项，尚无经过核验的过程热点。')).toBeInTheDocument();
    expect(screen.queryByText(nativeTotal.contribution_analysis.reason!)).not.toBeInTheDocument();
  });
  it('keeps method selection available after a calculation refusal', async () => {
    const change = vi.fn();
    const props = { ...baseProps, onMethodPackageChange: change, methodPackages: [
      { reference: 'native@1', label: 'Native method' }, { reference: 'foreground@1', label: 'Foreground method' },
    ], selectedMethodPackageRef: 'native@1' };
    const { rerender } = renderPanel(<ProductCarbonFootprintPanel {...props} result={undefined} error={new Error('Source answer required')} />);
    expect(screen.getByText('Source answer required')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('combobox', { name: '核算方法包' }));
    fireEvent.click(await screen.findByText('Foreground method'));
    expect(change).toHaveBeenCalledWith('foreground@1', expect.anything());
    rerender(<ProductCarbonFootprintPanel {...props} selectedMethodPackageRef="foreground@1" />);
    expect(screen.queryByText('Source answer required')).not.toBeInTheDocument();
    expect(screen.getAllByText('前景气候变化结果')).toHaveLength(2);
  });
  it('shows exact hotspots and locks artifact actions while downloading', async () => {
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:artifact') });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
    let finishExport: ((blob: Blob) => void) | undefined;
    vi.spyOn(api, 'productCarbonFootprintExport').mockImplementation(() => new Promise((resolve) => { finishExport = resolve; }));
    const report = vi.spyOn(api, 'productCarbonFootprintReport').mockResolvedValue(new Blob(['<html />'], { type: 'text/html' }));
    const onLoad = vi.fn();
    const print = vi.fn();
    const reportWindow = { opener: window, location: { href: '' }, addEventListener: onLoad, close: vi.fn(), print } as unknown as Window;
    vi.spyOn(window, 'open').mockReturnValue(reportWindow);
    renderPanel(<ProductCarbonFootprintPanel {...baseProps} />);

    expect(screen.getAllByText('前景气候变化结果')).toHaveLength(2);
    expect(screen.queryByText('热点可用')).not.toBeInTheDocument();
    expect(screen.getByText('未提供过程名称')).toBeInTheDocument();
    expect(screen.queryByText('exchange-hotspot')).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: '导出' }));
    fireEvent.click(await screen.findByRole('menuitem', { name: 'Excel 明细' }));
    expect(screen.getByRole('button', { name: '导出' })).toBeDisabled();
    finishExport?.(new Blob(['xlsx']));
    await waitFor(() => expect(api.productCarbonFootprintExport).toHaveBeenCalledWith('snapshot-1', 'pcf.bound@1.0.0', { result_basis: 'total' }));
    await waitFor(() => expect(screen.getByRole('button', { name: '导出' })).toBeEnabled());

    await userEvent.click(screen.getByRole('button', { name: '导出' }));
    fireEvent.click(await screen.findByRole('menuitem', { name: 'HTML 报告' }));
    await waitFor(() => expect(report).toHaveBeenCalledTimes(1));
    await userEvent.click(screen.getByRole('button', { name: '导出' }));
    fireEvent.click(await screen.findByRole('menuitem', { name: '打印 / 另存 PDF' }));
    await waitFor(() => expect(report).toHaveBeenCalledTimes(2));
    const loadHandler = onLoad.mock.calls[0][1] as () => void;
    loadHandler();
    expect(print).toHaveBeenCalledOnce();
  });

  it('surfaces export failure and retries the same action', async () => {
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:artifact') });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
    const exportFile = vi.spyOn(api, 'productCarbonFootprintExport')
      .mockRejectedValueOnce(new Error('导出服务暂时不可用'))
      .mockResolvedValueOnce(new Blob(['xlsx']));
    renderPanel(<ProductCarbonFootprintPanel {...baseProps} result={{ ...result, contribution_analysis: { status: 'unavailable', coverage: 'total_only', reason: '供应商未返回逐交换贡献回执', indicator_receipt: null, hotspots: [] } }} />);

    expect(screen.getByText('当前冻结结果只提供气候总量或来源分项，尚无经过核验的过程热点。')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '导出' }));
    fireEvent.click(await screen.findByRole('menuitem', { name: 'Excel 明细' }));
    expect(await screen.findByText('导出服务暂时不可用')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '重新加载' }));
    await waitFor(() => expect(exportFile).toHaveBeenCalledTimes(2));
  });

  it('renders the user-method grouping with its coverage gaps and never claims a complete declaration', () => {
    const grouped = {
      ...result,
      contribution_analysis: {
        ...result.contribution_analysis,
        user_method_grouping: {
          method: { method_id: 'm1', version: 2, content_sha256: 'a'.repeat(64), model_revision_id: 'rev-2', execution_plan_sha256: 'e'.repeat(64), compiler_version: 'nebula_one.method-compiler.v1' },
          grouping_mode: 'path_weighted' as const,
          execution_status: 'executed_partial',
          counts_as_complete_pcf: false,
          coverage: {
            attribution_coverage: 0.75,
            coverage_gaps: [{ rule_index: 0, code: 'METHOD_RULE_NO_WEIGHTED_CONTRIBUTION', message: 'no weighted value', exchange_id: 'u1' }],
            unattributed_exchange_ids: ['u1', 'u2', 'u3'],
            engine_gap_exchange_ids: ['g1'],
            uncharacterized_exchange_ids: ['c1'],
            zero_cf_exchange_ids: ['z1'],
          },
          grouping: null,
        },
      },
    } as ProductCarbonFootprint;
    const { container } = renderPanel(<ProductCarbonFootprintPanel {...baseProps} result={grouped}
      exchangeNames={{ u1: '焦炉煤气', g1: '外购电力' }} />);
    expect(screen.getByText('用户方法归组')).toBeInTheDocument();
    expect(screen.getByText('用户方法的归组结果为部分核算，不构成完整产品碳足迹声明。')).toBeInTheDocument();
    expect(screen.getByText('按路径加权')).toBeInTheDocument();
    // The engine's status enum never reaches the Chinese reading surface.
    expect(screen.getByText('规则已执行，仍有缺项')).toBeInTheDocument();
    expect(screen.queryByText('executed_partial')).toBeNull();
    expect(screen.getByText('路径归属覆盖')).toBeInTheDocument();
    // The value cell carries the real engine attribution fraction; the coverage row never shows a placeholder dash.
    const coverageRow = screen.getByText('路径归属覆盖').closest('div');
    expect(coverageRow?.querySelector('dd')?.textContent).toBe('75%');
    // A gap is a reason the reader can act on, naming the flow it belongs to — not "[object Object]".
    expect(screen.getByText('存在 1 处覆盖缺口')).toBeInTheDocument();
    expect(screen.getByText('已计入，但引擎没有给出该流的加权贡献值，暂不能归集')).toBeInTheDocument();
    expect(screen.getByText('· 焦炉煤气')).toBeInTheDocument();
    expect(container.textContent).not.toContain('[object Object]');
    // Four gap reasons stay four separate rows, each naming its flows.
    expect(screen.getByText('未匹配因子的流 1 条')).toBeInTheDocument();
    expect(screen.getByText('c1')).toBeInTheDocument();
    expect(screen.getByText('未关联背景的流 1 条')).toBeInTheDocument();
    expect(screen.getByText('外购电力')).toBeInTheDocument();
    expect(screen.getByText('真实零值的流 1 条')).toBeInTheDocument();
    expect(screen.getByText('z1')).toBeInTheDocument();
    expect(screen.getByText('尚未设置规则的流 3 条')).toBeInTheDocument();
    expect(container.querySelector('.pcf-result__grouping .audit-json')?.textContent).toContain('e'.repeat(64));
    expect(container.querySelector('.pcf-result__grouping .audit-json')?.textContent).toContain('nebula_one.method-compiler.v1');
  });

  it.each([
    ['complete', '现有贡献均有路径归属'],
    ['partial', '部分贡献缺少路径归属'],
    ['missing', '缺少路径归属'],
    ['foreground_only', '已归属前景贡献，未包含背景贡献'],
  ] as const)('renders the engine coverage status %s without inventing a percentage', (status, label) => {
    const grouped = { ...result, contribution_analysis: { ...result.contribution_analysis,
      user_method_grouping: { method: { method_id: 'm1', version: 1, content_sha256: 'a'.repeat(64) },
        grouping_mode: 'path_weighted', execution_status: 'executed_full',
        counts_as_complete_pcf: false, coverage: { attribution_coverage: status } } } } as ProductCarbonFootprint;
    renderPanel(<ProductCarbonFootprintPanel {...baseProps} result={grouped} />);
    expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.getByText('路径归属覆盖').closest('div')?.querySelector('dd')?.textContent).not.toContain('%');
  });

  it('renders a user-defined non-Scope category grouping with gaps shown as gaps, never zero', () => {
    const grouped = {
      ...result,
      contribution_analysis: {
        ...result.contribution_analysis,
        user_method_grouping: {
          method: { method_id: 'm1', version: 2, content_sha256: 'a'.repeat(64) },
          grouping_mode: 'path_weighted' as const,
          execution_status: 'executed_partial',
          counts_as_complete_pcf: false,
          coverage: {},
          grouping: null,
          dimension_grouping: {
            grouping: {
              indicator_unit: 'kg CO2-Eq', known_total: 45, known_term_count: 2,
              excluded: { value: 10, unit: 'kg CO2-Eq', term_count: 1, missing_count: 0 },
              pending: { term_count: 0 },
              missing_value: { count: 1, source_keys: ['m1'] },
              dimensions: {
                plant_split: {
                  categories: [
                    { id: 'onsite_production', name: '厂内生产', parent_id: null, is_leaf: true, subtotal: 40, unit: 'kg CO2-Eq', term_count: 1, missing_count: 0 },
                    { id: 'purchased_energy', name: '外购能源', parent_id: null, is_leaf: true, subtotal: 5, unit: 'kg CO2-Eq', term_count: 1, missing_count: 0 },
                    { id: 'upstream_materials', name: '上游原料', parent_id: null, is_leaf: true, subtotal: null, unit: null, term_count: 0, missing_count: 1 },
                  ],
                  unattributed: { subtotal: 0, term_count: 0 },
                  reconciled: false, requires_full_coverage: false, completeness: 'partial',
                },
              },
              reconciled: false, problems: [], reporting_statement: false,
            },
            coverage_gaps: [], uncovered_exchange_ids: [], reconciled: false, problems: [], scope_1_2_3_statement: false,
          },
        },
      },
    } as ProductCarbonFootprint;
    renderPanel(<ProductCarbonFootprintPanel {...baseProps} result={grouped} />);
    expect(screen.getByText('自定义类别归组')).toBeInTheDocument();
    expect(screen.getByText('自定义类别归组未与总量对平，差额已如实列出，不补齐、不计零。')).toBeInTheDocument();
    expect(screen.getByText('厂内生产')).toBeInTheDocument();
    expect(screen.getByText('40 kg CO2-Eq')).toBeInTheDocument();
    // A category with no weighted value stays a gap ('—'), never a fabricated 0.
    expect(screen.getByText('上游原料')).toBeInTheDocument();
    expect(screen.queryByText('0 kg CO2-Eq')).toBeNull();
    // The missing-paths row names the flow instead of a placeholder dash; an id with no known
    // name stays as the id rather than being dropped.
    const missingPathsRow = screen.getByText(/无加权数值的流/).closest('div');
    expect(missingPathsRow?.querySelector('dd')?.textContent).toBe('m1');
  });

  const readyScheme = {
    id: 't1', application_id: 'app-steel', model_revision_id: 'revision-1', purpose: 'custom', name: '能源标签',
    description: null, origin_method_id: null, status: 'ready', created_at: '', updated_at: '',
    semantics: 'flow_tag.v1', latest_version: 1, latest_content_sha256: 't'.repeat(64), latest_status: 'ready',
  };
  const tagGrouping = (overrides: Record<string, unknown> = {}) => ({
    application_id: 'app-steel', snapshot_id: 'snapshot-1', snapshot_content_sha256: 'snapshot-hash',
    indicator_key: 'climate-total', indicator_unit: 'kg CO2-Eq', mode: 'separate', semantics: 'flow_tag.v1',
    available: true, reason: null, union: null, intersection: null, overlap: {}, reconciled: true,
    problems: [], content_sha256: 'g'.repeat(64),
    schemes: [{
      scheme: { method_id: 't1', version: 1, content_sha256: 't'.repeat(64), name: '能源标签', purpose: 'custom', model_revision_id: 'revision-1' },
      dimension: { id: 'tag', name: '分类', requires_full_coverage: false, categories: [
        { id: 'tag_category_1', name: '购入能源', parent_id: null, is_leaf: true, subtotal: 1.5, unit: 'kg CO2-Eq', term_count: 1, missing_count: 0 },
      ] },
      tag_total: { value: 1.5, unit: 'kg CO2-Eq', term_count: 1 },
      uncategorized: { subtotal: 0, unit: 'kg CO2-Eq', term_count: 0 },
      matched: { term_count: 1, known_term_count: 1 }, matched_exchange_ids: ['exchange-hotspot'],
      unmatched: { term_count: 0, known_value: 0, unit: null, missing_count: 0, exchange_ids: [] },
      pending: { term_count: 0, exchange_ids: [] }, missing: { term_count: 0, exchange_ids: [], no_weighted_value_ids: [] },
      real_zero: { term_count: 0, exchange_ids: [] },
      coverage: { weighted_term_count: 1, matched_term_count: 1, unmatched_term_count: 0, pending_term_count: 0, matched_share: 1, complete: true },
      reconciled: true, problems: [], reporting_statement: false,
    }],
    ...overrides,
  });

  it('regroups the frozen snapshot by a ready tag scheme without re-solving it', async () => {
    vi.mocked(api.calculationMethods).mockResolvedValue([readyScheme]);
    const grouping = vi.spyOn(api, 'tagGrouping').mockResolvedValue(tagGrouping() as never);
    renderPanel(<ProductCarbonFootprintPanel {...baseProps} />);
    expect(await screen.findByText('标签归集')).toBeInTheDocument();
    await waitFor(() => expect(grouping).toHaveBeenCalledWith('app-steel', expect.objectContaining({
      snapshot_id: 'snapshot-1', indicator_key: 'climate-total', mode: 'separate',
      // The request cites the exact head identity, never just the method name.
      schemes: [{ method_id: 't1', version: 1, content_sha256: 't'.repeat(64) }],
    })));
    expect(await screen.findByText('购入能源')).toBeInTheDocument();
    expect(screen.getByText('已知 1 条，匹配记录 1 条')).toBeInTheDocument();
    // Tag total and the single category subtotal both state the frozen value.
    expect(screen.getAllByText('1.5 kg CO2-Eq')).toHaveLength(2);
  });

  it('switches the grouping mode and keeps unavailable reasons in the server wording', async () => {
    vi.mocked(api.calculationMethods).mockResolvedValue([readyScheme]);
    const grouping = vi.spyOn(api, 'tagGrouping').mockResolvedValue(tagGrouping() as never);
    renderPanel(<ProductCarbonFootprintPanel {...baseProps} />);
    await userEvent.click(await screen.findByRole('combobox', { name: '查看方式' }));
    fireEvent.click(await screen.findByText('交集'));
    await waitFor(() => expect(grouping).toHaveBeenCalledTimes(2));
    expect(grouping.mock.calls[1][1].mode).toBe('intersection');

    grouping.mockResolvedValue(tagGrouping({ available: false, reason: 'PATH_WEIGHTED_RECEIPT_MISSING', schemes: [] }) as never);
    await userEvent.click(screen.getByRole('combobox', { name: '查看方式' }));
    fireEvent.click(await screen.findByText('并集'));
    expect(await screen.findByText('该快照没有路径加权的贡献回执，无法把贡献归到标签而不猜测归属。')).toBeInTheDocument();
  });

  it('shows no tag section at all when the revision has no ready scheme', async () => {
    const grouping = vi.spyOn(api, 'tagGrouping').mockResolvedValue(tagGrouping() as never);
    renderPanel(<ProductCarbonFootprintPanel {...baseProps} />);
    await waitFor(() => expect(api.calculationMethods).toHaveBeenCalled());
    expect(screen.queryByText('标签归集')).toBeNull();
    expect(grouping).not.toHaveBeenCalled();
  });

  it('points draft schemes to their exact editor before grouping is available', async () => {
    vi.mocked(api.calculationMethods).mockResolvedValue([{...readyScheme, latest_status: 'draft'}]);
    const grouping = vi.spyOn(api, 'tagGrouping');
    renderPanel(<ProductCarbonFootprintPanel {...baseProps} />);
    expect(await screen.findByRole('link', {name: '检查“能源标签”'})).toHaveAttribute('href',
      '/applications/app-steel/calculation-methods?revision=revision-1&method=t1');
    expect(grouping).not.toHaveBeenCalled();
    expect(screen.queryByRole('combobox', {name: '查看方式'})).toBeNull();
  });

  it('keeps missing uncategorized and unmatched amounts separate from true zero', async () => {
    vi.mocked(api.calculationMethods).mockResolvedValue([readyScheme]);
    const grouped = tagGrouping();
    grouped.schemes[0].uncategorized = {subtotal: null, unit: null, term_count: 1} as never;
    grouped.schemes[0].unmatched = {term_count: 1, known_value: null, unit: null, missing_count: 1, exchange_ids: ['missing']} as never;
    vi.spyOn(api, 'tagGrouping').mockResolvedValue(grouped as never);
    renderPanel(<ProductCarbonFootprintPanel {...baseProps} />);
    expect((await screen.findByText('已匹配但未分类')).closest('div')?.querySelector('dd')).toHaveTextContent('—');
    expect(screen.getByText('未匹配').closest('div')?.querySelector('dd')).toHaveTextContent('— · 1 条 · 缺数值 1 条');
    expect(screen.queryByText('0 kg CO2-Eq')).toBeNull();
  });

  it('groups a frozen snapshot by result category and calls unassigned flows none, not zero', async () => {
    vi.mocked(api.calculationMethods).mockResolvedValue([{ ...readyScheme, name: '范围1–3', semantics: 'result_category.v1' }]);
    const grouped = tagGrouping({ semantics: 'result_category.v1' });
    grouped.schemes[0] = {
      ...grouped.schemes[0],
      semantics: 'result_category.v1',
      populated: true,
      unmatched: { term_count: 1, known_value: 0.4, unit: 'kg CO2-Eq', missing_count: 0, exchange_ids: ['unassigned'] },
    } as never;
    vi.spyOn(api, 'tagGrouping').mockResolvedValue(grouped as never);
    renderPanel(<ProductCarbonFootprintPanel {...baseProps} />);
    expect(await screen.findByText('结果分类归集')).toBeInTheDocument();
    expect(await screen.findByText('已分类')).toBeInTheDocument();
    expect(screen.getByText('已知 1 条，已分类记录 1 条')).toBeInTheDocument();
    expect(screen.getByText('无（未分类）').closest('div')?.querySelector('dd')).toHaveTextContent('0.4 kg CO2-Eq');
    // The legacy inclusion switch and its "matched but uncategorized" bucket must not reappear.
    expect(screen.queryByText('待确认')).toBeNull();
    expect(screen.queryByText('已匹配但未分类')).toBeNull();
    expect(screen.queryByText('旧标签方案')).toBeNull();
  });

  it('shows a result category with no assignments as not populated instead of zero', async () => {
    vi.mocked(api.calculationMethods).mockResolvedValue([{ ...readyScheme, name: '碳市场', semantics: 'result_category.v1' }]);
    const grouped = tagGrouping({ semantics: 'result_category.v1' });
    grouped.schemes[0] = {
      ...grouped.schemes[0],
      semantics: 'result_category.v1',
      populated: false,
      dimension: { ...grouped.schemes[0].dimension, categories: [
        { id: 'caliber_1', name: '履约', parent_id: null, is_leaf: true, subtotal: null, unit: null, term_count: 0, missing_count: 0 },
      ] },
      tag_total: { value: null, unit: 'kg CO2-Eq', term_count: 0 },
      matched: { term_count: 0, known_term_count: 0 },
      unmatched: { term_count: 1, known_value: 1.5, unit: 'kg CO2-Eq', missing_count: 0, exchange_ids: ['exchange-hotspot'] },
    } as never;
    vi.spyOn(api, 'tagGrouping').mockResolvedValue(grouped as never);
    renderPanel(<ProductCarbonFootprintPanel {...baseProps} />);
    expect(await screen.findByText('尚未给任何流选择结果分类，因此这套口径没有可归集的贡献。')).toBeInTheDocument();
    expect(screen.getByText('履约')).toBeInTheDocument();
    expect(screen.getByText('无（未分类）').closest('div')?.querySelector('dd')).toHaveTextContent('1.5 kg CO2-Eq');
    expect(screen.queryByText('0 kg CO2-Eq')).toBeNull();
    expect(screen.queryByText('没有已分类的已知贡献，本口径不显示为零或完整。')).toBeNull();
  });

  it('opens and exports a frozen tag result even after all schemes are archived', async () => {
    const frozen = tagGrouping({result_id: 'saved-1', created_at: '2026-10-28T00:00:00Z'});
    vi.mocked(api.tagGroupingHistory).mockResolvedValue([frozen] as never);
    const read = vi.spyOn(api, 'tagGroupingResult').mockResolvedValue(frozen as never);
    const fresh = vi.spyOn(api, 'tagGrouping');
    const download = vi.spyOn(api, 'tagGroupingExport').mockResolvedValue(new Blob(['report']));
    Object.defineProperty(URL, 'createObjectURL', {configurable: true, value: vi.fn(() => 'blob:tag-result')});
    Object.defineProperty(URL, 'revokeObjectURL', {configurable: true, value: vi.fn()});
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    renderPanel(<ProductCarbonFootprintPanel {...baseProps} />);
    await userEvent.click(await screen.findByRole('combobox', {name: '历史归集结果'}));
    fireEvent.click(await screen.findByRole('option', {name: /能源标签 v1/}));
    expect(await screen.findByText('购入能源')).toBeInTheDocument();
    expect(read).toHaveBeenCalledWith('app-steel', 'saved-1');
    expect(fresh).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', {name: '导出归集报告'}));
    await waitFor(() => expect(download).toHaveBeenCalledWith('app-steel', 'saved-1', 'html'));
    await waitFor(() => expect(click).toHaveBeenCalled());
  });
});
