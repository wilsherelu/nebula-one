import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useNavigate, useSearchParams } from 'react-router-dom';
import type { ComponentProps, ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '../api/client';
import type { BoundaryDefinition, CbamComplexTrialResult, CbamTrialResult, ReportingPeriod, SolvedSystemSnapshot } from '../api/types';
import { CbamRuleTrialPanel } from './CbamRuleTrialPanel';
import { I18nProvider, LANGUAGE_STORAGE_KEY } from '../i18n';

const snapshot: SolvedSystemSnapshot = {
  id: 'snapshot-1', application_id: 'app-1', system_revision_id: 'revision-1', inventory_snapshot_id: null, parameter_set_id: null,
  solve_hash: 'solve-hash', provider: 'nebula-lca', provider_receipt: {}, functional_unit: { amount: 1, unit: 'kg' }, database_release: 'EF3.1', solver_version: 'provider-v1',
  activity_vector: [], scaled_technosphere_exchanges: [], scaled_elementary_exchanges: [], internal_transfers: [], boundary_flows: [], process_balance_residuals: [], contribution_graph: {}, lcia_results: {},
  content_sha256: 'snapshot-hash', created_at: '2026-09-01T08:00:00Z',
};

const precursorSnapshot: SolvedSystemSnapshot = { ...snapshot, id: 'snapshot-2', functional_unit: { amount: 2, unit: 'kg hydrogen' }, content_sha256: 'precursor-snapshot-hash', created_at: '2026-09-01T07:00:00Z' };

const result: CbamComplexTrialResult = {
  schema_version: 'nebula_one.cbam.complex-trial.v1', capability_key: 'cbam.complex-trial.v1',
  method_package: { ref: 'cbam.complex@1.0.0', content_sha256: 'method-hash', jurisdiction: 'EU', rule_source_sha256: 'rule-source-hash' },
  source_snapshot: { id: snapshot.id, content_sha256: snapshot.content_sha256, application_id: snapshot.application_id },
  reporting_period: { id: 'period-2026', key: 'calendar-2026', name: 'Calendar year 2026', start_date: '2026-01-01', end_date: '2026-12-31', resolution: 'year' },
  goods: { cn_code: '2814 10 00', aggregated_goods_category: 'Ammonia', production_process_uuid: 'ammonia-process' },
  activity_level: { value: '0.001', unit: 't product', source_value: '1', source_unit: 'kg' },
  attributed_emissions: {
    final_process_direct: { value: '0.0001', unit: 't CO2e', source_value: '0.1', source_unit: 'kg CO2e' },
    precursor_embedded_direct: { value: '0.000036', unit: 't CO2e' },
    total_direct_component: { value: '0.000136', unit: 't CO2e' }, indirect: null,
  },
  precursors: [{ exchange_id: 'hydrogen-in', method_package_ref: 'cbam.simple@1.0.0', mass: { value: '0.00018', unit: 't precursor', source_value: '0.18', source_unit: 'kg' }, specific_mass_consumption: { value: '0.18', unit: 't precursor/t product' }, specific_embedded_emissions: { value: '0.2', unit: 't CO2e/t precursor' }, embedded_emissions: { value: '0.000036', unit: 't CO2e' }, result_content_sha256: 'precursor-result-hash' }],
  specific_embedded_emissions: { value: '0.136000000000', unit: 't CO2e/t product', component: 'direct', formula: 'ae_g + sum(m_i * SEE_i)', regulatory_equation: 'Equation 62' },
  status: 'trial_passed', audit: { status: 'trial_passed', checks: { precursor_result_hashes_valid: true } }, claim_boundary: { trial_only: true, not_a_cbam_declaration: true }, content_sha256: 'result-hash',
};

const simpleResult = {
  schema_version: 'nebula_one.cbam.trial.v1', capability_key: 'cbam.trial.v1',
  method_package: { ref: 'cbam.simple@1.0.0', content_sha256: 'simple-method-hash', jurisdiction: 'EU', rule_source_sha256: 'simple-rule-hash' },
  source_snapshot: { id: snapshot.id, content_sha256: snapshot.content_sha256, application_id: snapshot.application_id },
  reporting_period: { id: 'period-2026', key: 'calendar-2026', name: 'Calendar year 2026', start_date: '2026-01-01', end_date: '2026-12-31', resolution: 'year' },
  goods: { cn_code: '2814 10 00', aggregated_goods_category: 'Ammonia simple goods', production_process_uuid: 'ammonia-process' },
  activity_level: { value: '0.001', unit: 't product', source_value: '1', source_unit: 'kg' },
  attributed_emissions: { direct: { value: '0.0001', unit: 't CO2e', source_value: '0.1', source_unit: 'kg CO2e' }, indirect: null, precursors: [] },
  specific_embedded_emissions: { value: '0.1', unit: 't CO2e/t product', formula: 'ae_g / AL' },
  status: 'trial_passed', audit: { status: 'trial_passed' }, claim_boundary: { trial_only: true }, content_sha256: 'simple-result-hash',
} as CbamTrialResult;

const reportingPeriods = [
  { id: 'period-2026', application_id: 'app-1', key: 'calendar-2026', name: 'Calendar year 2026', start_date: '2026-01-01', end_date: '2026-12-31', resolution: 'year', created_at: snapshot.created_at },
  { id: 'period-2025', application_id: 'app-1', key: 'calendar-2025', name: 'Calendar year 2025', start_date: '2025-01-01', end_date: '2025-12-31', resolution: 'year', created_at: snapshot.created_at },
] as ReportingPeriod[];

/** The frozen CBAM boundary the seed installed for this application, as the boundaries API returns it. */
const cbamBoundary = {
  id: 'boundary-cbam-1', application_id: 'app-1', name: 'nebula.iron-steel.bf-bof-crude-steel@1.0.0 boundaries/cbam.json',
  boundary_type: 'cbam_trial', included_entity_ids: [], included_process_ids: [], included_flow_rules: [], excluded_items: [],
  consolidation_policy: {}, period_id: null, geographic_scope: {}, method_package_ref: 'cbam.simple@1.0.0',
  content_sha256: 'boundary-content-hash', status: 'frozen', created_at: snapshot.created_at, frozen_at: snapshot.created_at,
} as BoundaryDefinition;

/** A cbam.trial.v2 body as the live API returned it for the steel seed, reduced to what the panel reads. */
const v2Result = {
  ...simpleResult, schema_version: 'nebula_one.cbam.trial.v2', capability_key: 'cbam.trial.v2',
  goods: { cn_code: '7207', aggregated_goods_category: 'Crude steel', production_process_uuid: 'steel-process' },
  attributed_emissions: { direct: { value: '1.940739734', unit: 't CO2e', source_value: '1940.739734', source_unit: 'kg CO2e' }, indirect: null, precursors: [] },
  specific_embedded_emissions: { value: '1.940739734000', unit: 't CO2e/t product', formula: 'attributed_direct_emissions_t_CO2e / activity_level_t_product' },
  content_sha256: 'v2-result-hash',
  coverage: {
    schema: 'nebula_one.cbam.boundary-coverage.v1',
    universe_sources: { boundary_definition_id: cbamBoundary.id, boundary_name: cbamBoundary.name, boundary_content_sha256: cbamBoundary.content_sha256 },
    totals: { ports: 28, counted_kg_co2e: '1940.739734' },
    open_items: [{ clause: 'ST-18', item: 'flue gas cleaning exchanges', effect: 'no reagent exchange is authored for them', gap_ref: 'MG-S09', state: 'open_coverage_limitation' }],
    refusals: [],
  },
} as CbamTrialResult;

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.removeItem(LANGUAGE_STORAGE_KEY);
});

type PanelProps = ComponentProps<typeof CbamRuleTrialPanel>;

function Panel(props: Partial<PanelProps>) {
  return <CbamRuleTrialPanel applicationId="app-1" snapshot={snapshot} snapshots={[snapshot, precursorSnapshot]}
    simpleMethods={[{ reference: 'cbam.simple@1.0.0', label: 'Hydrogen · 1.0.0' }]}
    complexMethods={[{ reference: 'cbam.complex@1.0.0', label: 'Ammonia · 1.0.0' }]}
    boundaryRequiredFor={[]} cbamBoundaries={[]} boundariesLoading={false} boundariesError={null} onBoundariesRetry={vi.fn()}
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
    <button onClick={() => navigate(1)}>浏览器前进</button>
  </div>;
}

function Tree({ entry, panel, client }: { entry: string; panel: ReactNode; client: QueryClient }) {
  return <I18nProvider><QueryClientProvider client={client}><MemoryRouter initialEntries={[entry]}><Harness>{panel}</Harness></MemoryRouter></QueryClientProvider></I18nProvider>;
}

function renderPanel(entry: string, panel: ReactNode, client = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  return render(<Tree entry={entry} panel={panel} client={client} />);
}

function searchTerm() {
  return screen.getByTestId('search').textContent ?? '';
}

function mockReads() {
  vi.spyOn(api, 'periods').mockResolvedValue(reportingPeriods);
  vi.spyOn(api, 'cbamComplexTrial').mockResolvedValue(result);
  vi.spyOn(api, 'cbamComplexTrialChart').mockResolvedValue(new Blob(['<svg />'], { type: 'image/svg+xml' }));
  vi.spyOn(api, 'cbamTrial').mockResolvedValue(simpleResult);
  vi.spyOn(api, 'cbamTrialChart').mockResolvedValue(new Blob(['<svg />'], { type: 'image/svg+xml' }));
}

describe('CBAM rule trial panel', () => {
  it('keeps configuration hidden while the frozen result is loading', async () => {
    mockReads();
    let finish!: (value: CbamTrialResult) => void;
    const trial = vi.spyOn(api, 'cbamTrial').mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    renderPanel('/?cbam-tab=simple', <Panel complexMethods={[]} />);
    await waitFor(() => expect(trial).toHaveBeenCalled());
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    finish(simpleResult as CbamTrialResult);
    expect(await screen.findByRole('button', { name: '重新核算' })).toBeInTheDocument();
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  });
  it('discloses a partial v2 total, missing indirect factor and nitrogen basis without substituting zero', async () => {
    mockReads();
    vi.spyOn(api, 'cbamTrial').mockResolvedValue({
      ...v2Result,
      specific_embedded_emissions: { ...v2Result.specific_embedded_emissions, partial_result: true },
      attributed_emissions: { ...v2Result.attributed_emissions, indirect: {
        state: 'formula_only', value: null, unit: null,
        activity: { value: '12.5', unit: 'kWh' }, missing_factor_package: 'reviewed-electricity-factor',
      } },
      nitrogen_basis: { applies: true, value: '2.4', unit: 'kg CO2e/kg N', label: 'Declared nitrogen basis' },
      coverage: { ...v2Result.coverage!, exchanges: [{
        exchange_id: 'boiler::co2', process_uuid: 'boiler-process', disposition: 'counted',
        amount: '1.5', unit: 'kg', clause: 'source-clause', basis: 'Measured combustion exchange',
      }, {
        exchange_id: 'boiler::excluded', process_uuid: 'boiler-process', disposition: 'excluded_with_basis',
        amount: null, unit: 'kg', clause: 'exclusion-clause', basis: 'Accounted at another process',
      }] },
    });
    renderPanel('/applications/app-1/results?view=cbam&cbam-tab=simple', <Panel boundaryRequiredFor={['cbam.simple@1.0.0']} cbamBoundaries={[cbamBoundary]} />);
    // the first screen names the partial total as "已计入…" and never dresses the partial as complete
    expect(await screen.findByText('已计入直接排放强度')).toBeInTheDocument();
    expect(screen.getByText('待补因子')).toBeInTheDocument();
    // the逐端口/间接/氮基 technical detail lives behind the single 计算依据 entry
    await userEvent.click(screen.getByRole('button', { name: '详情' }));
    expect(await screen.findByText(/reviewed-electricity-factor/)).toBeInTheDocument();
    expect(screen.getByText('已记录用电量：12.5 kWh')).toBeInTheDocument();
    expect(screen.getByText('尚未量化，不能按零排放计入。')).toBeInTheDocument();
    expect(screen.getByText('2.4 kg CO2e/kg N')).toBeInTheDocument();
    expect(screen.getByText(/Measured combustion exchange/)).toBeInTheDocument();
    expect(screen.getByText('无求解数量')).toBeInTheDocument();
    expect(api.cbamTrialChart).not.toHaveBeenCalled();
  });

  it('clears all rejected references in one action without changing unrelated URL state', async () => {
    mockReads();
    renderPanel('/applications/app-1/results?view=cbam&snapshot=snapshot-1&cbam-period=missing&cbam-complex-method=missing', <Panel />);
    await screen.findByText('链接指定的引用无法使用');
    expect(api.cbamComplexTrial).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: '清除并重新选择' }));
    expect(searchTerm()).toBe('view=cbam&snapshot=snapshot-1');
    expect(await screen.findByText('Ammonia')).toBeInTheDocument();
  });

  it('renders a complex-goods result, chart and hash evidence from one frozen request', async () => {
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:cbam-chart') });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
    mockReads();
    renderPanel('/applications/app-1/results?view=cbam', <Panel />);

    expect(await screen.findByText('Ammonia')).toBeInTheDocument();
    expect(screen.getByText('0.136')).toBeInTheDocument();
    expect(screen.getByText('试算结果，不是申报结论')).toBeInTheDocument();
    expect(api.cbamComplexTrial).toHaveBeenCalledWith('snapshot-1', { method_package_ref: 'cbam.complex@1.0.0', reporting_period_id: 'period-2026', precursors: [{ solved_snapshot_id: 'snapshot-2', method_package_ref: 'cbam.simple@1.0.0' }] });
    expect(await screen.findByRole('img', { name: '复杂商品前体贡献图' })).toHaveAttribute('src', 'blob:cbam-chart');

    await userEvent.click(screen.getByRole('button', { name: '详情' }));
    expect(await screen.findByText('method-hash')).toBeInTheDocument();
    expect(screen.getByText('rule-source-hash')).toBeInTheDocument();
    expect(screen.getByText('result-hash')).toBeInTheDocument();
    expect(screen.getByText(/precursor-result-hash/)).toBeInTheDocument();
  });

  it('restores every deep-linked choice on refresh and runs the read-only trial once', async () => {
    mockReads();
    renderPanel('/applications/app-1/results?view=cbam&snapshot=snapshot-1&cbam-tab=complex&cbam-complex-method=cbam.complex@1.0.0&cbam-period=period-2025&cbam-precursor-method=cbam.simple@1.0.0&cbam-precursor-snapshot=snapshot-2', <Panel />);

    expect(await screen.findByText('Ammonia')).toBeInTheDocument();
    expect(api.cbamComplexTrial).toHaveBeenCalledTimes(1);
    expect(api.cbamComplexTrial).toHaveBeenCalledWith('snapshot-1', { method_package_ref: 'cbam.complex@1.0.0', reporting_period_id: 'period-2025', precursors: [{ solved_snapshot_id: 'snapshot-2', method_package_ref: 'cbam.simple@1.0.0' }] });
    expect(screen.getByText('Calendar year 2025')).toBeInTheDocument();
    expect(api.cbamComplexTrialChart).toHaveBeenCalledTimes(1);
    expect(searchTerm()).toContain('view=cbam');
    expect(searchTerm()).toContain('snapshot=snapshot-1');
  });

  it('never sends the product snapshot as its own precursor', async () => {
    mockReads();
    renderPanel('/applications/app-1/results?view=cbam&cbam-tab=complex', <Panel />);

    expect(await screen.findByText('Ammonia')).toBeInTheDocument();
    expect(vi.mocked(api.cbamComplexTrial).mock.calls[0][1]).toMatchObject({ precursors: [{ solved_snapshot_id: 'snapshot-2' }] });
  });

  it('rejects a deep link that points the precursor at the product itself', async () => {
    mockReads();
    renderPanel('/applications/app-1/results?view=cbam&cbam-tab=complex&cbam-precursor-snapshot=snapshot-1', <Panel />);

    expect(await screen.findByText(/前体求解快照「snapshot-1」/)).toBeInTheDocument();
    expect(screen.getByText('当前冻结求解快照不能作为自身的前体，请另选一个已冻结的前体结果。')).toBeInTheDocument();
    expect(api.cbamComplexTrial).not.toHaveBeenCalled();
  });

  it('asks for a precursor instead of sending a request that can only fail', async () => {
    mockReads();
    renderPanel('/applications/app-1/results?view=cbam&cbam-tab=complex', <Panel snapshots={[snapshot]} />);

    expect(await screen.findByText('没有可用作前体的其它冻结求解快照')).toBeInTheDocument();
    expect(api.cbamComplexTrial).not.toHaveBeenCalled();
    expect(screen.queryByText('0.136')).not.toBeInTheDocument();
  });

  it('keeps an explicit reference pending while catalogs load, then resolves it once', async () => {
    mockReads();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const entry = '/applications/app-1/results?view=cbam&cbam-period=period-2025';
    const { rerender } = renderPanel(entry, <Panel packagesLoading />, client);
    expect(await screen.findByLabelText('正在加载')).toBeInTheDocument();
    expect(api.cbamComplexTrial).not.toHaveBeenCalled();
    expect(searchTerm()).toBe('view=cbam&cbam-period=period-2025');

    rerender(<Tree entry={entry} panel={<Panel />} client={client} />);
    expect(await screen.findByText('Ammonia')).toBeInTheDocument();
    expect(api.cbamComplexTrial).toHaveBeenCalledTimes(1);
    expect(vi.mocked(api.cbamComplexTrial).mock.calls[0][1]).toMatchObject({ reporting_period_id: 'period-2025' });
  });

  it('rejects an unknown method package instead of substituting the first one, and recovers after clearing', async () => {
    mockReads();
    renderPanel('/applications/app-1/results?view=cbam&cbam-complex-method=cbam.complex@9.9.9', <Panel />);

    expect(await screen.findByText('链接指定的引用无法使用')).toBeInTheDocument();
    expect(screen.getByText(/复杂商品方法包「cbam.complex@9.9.9」不属于当前对象或已不存在/)).toBeInTheDocument();
    expect(screen.getByText('已保留其它查询参数；未使用相近的结果替代链接中的引用。')).toBeInTheDocument();
    expect(api.cbamComplexTrial).not.toHaveBeenCalled();
    expect(decodeURIComponent(searchTerm())).toContain('cbam-complex-method=cbam.complex@9.9.9');

    await userEvent.click(screen.getByRole('button', { name: '清除并重新选择' }));
    expect(await screen.findByText('Ammonia')).toBeInTheDocument();
    expect(api.cbamComplexTrial).toHaveBeenCalledTimes(1);
    expect(vi.mocked(api.cbamComplexTrial).mock.calls[0][1]).toMatchObject({ method_package_ref: 'cbam.complex@1.0.0' });
    expect(searchTerm()).toBe('view=cbam');
  });

  it('refuses a precursor snapshot owned by another application without a request', async () => {
    mockReads();
    renderPanel('/applications/app-1/results?view=cbam&cbam-precursor-snapshot=snapshot-of-other-app', <Panel />);

    expect(await screen.findByText(/前体求解快照「snapshot-of-other-app」不属于当前对象或已不存在/)).toBeInTheDocument();
    expect(api.cbamComplexTrial).not.toHaveBeenCalled();
    expect(searchTerm()).toBe('view=cbam&cbam-precursor-snapshot=snapshot-of-other-app');
  });

  it('walks back and forward through the selections the analyst made', async () => {
    mockReads();
    renderPanel('/applications/app-1/results?view=cbam', <Panel />);
    expect(await screen.findByText('Ammonia')).toBeInTheDocument();
    expect(searchTerm()).toBe('view=cbam');

    await userEvent.click(screen.getByRole('button', { name: '重新核算' }));
    await userEvent.click(screen.getByRole('tab', { name: '模型边界试算' }));
    expect(await screen.findByText('Ammonia simple goods')).toBeInTheDocument();
    expect(searchTerm()).toBe('view=cbam&cbam-tab=simple');
    expect(api.cbamTrial).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole('button', { name: '浏览器后退' }));
    await waitFor(() => expect(screen.getByText('Ammonia')).toBeInTheDocument());
    expect(searchTerm()).toBe('view=cbam');

    await userEvent.click(screen.getByRole('button', { name: '浏览器前进' }));
    await waitFor(() => expect(screen.getByText('Ammonia simple goods')).toBeInTheDocument());
    expect(searchTerm()).toBe('view=cbam&cbam-tab=simple');
  });

  it('fails closed in the UI when a complex method has no simple precursor method', async () => {
    mockReads();
    renderPanel('/applications/app-1/results?view=cbam', <Panel simpleMethods={[]} />);

    expect(await screen.findByText('缺少前体方法')).toBeInTheDocument();
    expect(api.cbamComplexTrial).not.toHaveBeenCalled();
  });

  it('surfaces a rejected complex trial instead of leaving the panel blank', async () => {
    vi.spyOn(api, 'periods').mockResolvedValue(reportingPeriods);
    vi.spyOn(api, 'cbamTrial').mockResolvedValue(simpleResult);
    vi.spyOn(api, 'cbamTrialChart').mockResolvedValue(new Blob(['<svg />'], { type: 'image/svg+xml' }));
    vi.spyOn(api, 'cbamComplexTrial').mockRejectedValue(new ApiError('the complex-goods Process must resolve once in kg', 422, 'CBAM_COMPLEX_ACTIVITY_NOT_UNIQUE'));
    renderPanel('/applications/app-1/results?view=cbam&cbam-tab=complex', <Panel />);

    expect(await screen.findByText('the complex-goods Process must resolve once in kg')).toBeInTheDocument();
    expect(screen.queryByText('Ammonia')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /重试|重新/ })).toBeInTheDocument();
  });

  it('surfaces a rejected simple trial instead of leaving the panel blank', async () => {
    vi.spyOn(api, 'periods').mockResolvedValue(reportingPeriods);
    vi.spyOn(api, 'cbamComplexTrial').mockResolvedValue(result);
    vi.spyOn(api, 'cbamComplexTrialChart').mockResolvedValue(new Blob(['<svg />'], { type: 'image/svg+xml' }));
    vi.spyOn(api, 'cbamTrial').mockRejectedValue(new ApiError('the product Process must resolve once in the activity vector', 422, 'CBAM_TRIAL_ACTIVITY_NOT_UNIQUE', { match_count: 0 }));
    renderPanel('/applications/app-1/results?view=cbam&cbam-tab=simple', <Panel />);

    expect(await screen.findByText('the product Process must resolve once in the activity vector')).toBeInTheDocument();
    expect(screen.getByText(/错误码：CBAM_TRIAL_ACTIVITY_NOT_UNIQUE（HTTP 422）/)).toBeInTheDocument();
    expect(screen.queryByText('Ammonia simple goods')).not.toBeInTheDocument();
  });

  it('explains a trial request that is held back while the page is in the background', async () => {
    vi.spyOn(api, 'periods').mockResolvedValue(reportingPeriods);
    vi.spyOn(api, 'cbamComplexTrial').mockResolvedValue(result);
    vi.spyOn(api, 'cbamComplexTrialChart').mockResolvedValue(new Blob(['<svg />'], { type: 'image/svg+xml' }));
    vi.spyOn(api, 'cbamTrial').mockRejectedValue(new ApiError('Failed to fetch', 0));
    const visibility = Object.getOwnPropertyDescriptor(document, 'visibilityState');
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' });
    try {
      renderPanel('/applications/app-1/results?view=cbam&cbam-tab=simple', <Panel />, new QueryClient({ defaultOptions: { queries: { retry: () => true } } }));
      document.dispatchEvent(new Event('visibilitychange'));

      await waitFor(() => expect(screen.getByText('试算请求未完成')).toBeInTheDocument(), { timeout: 3_000 });
      expect(screen.getByText('页面处于后台或设备离线时请求会暂停，本次没有产生试算结果。')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: '重新加载' })).toBeInTheDocument();
      expect(api.cbamTrial).toHaveBeenCalledTimes(1);
    } finally {
      if (visibility) Object.defineProperty(document, 'visibilityState', visibility);
      // react-query keeps the focus state on a module singleton, so hand it back to the next test.
      document.dispatchEvent(new Event('visibilitychange'));
    }
  });

  it('sends the frozen boundary a v2 package computes against and states open coverage behind the entry', async () => {
    mockReads();
    vi.spyOn(api, 'cbamTrial').mockResolvedValue(v2Result);
    renderPanel('/applications/app-1/results?view=cbam&cbam-tab=simple', <Panel boundaryRequiredFor={['cbam.simple@1.0.0']} cbamBoundaries={[cbamBoundary]} />);

    expect(await screen.findByText('Crude steel')).toBeInTheDocument();
    expect(api.cbamTrial).toHaveBeenCalledWith('snapshot-1', {
      method_package_ref: 'cbam.simple@1.0.0',
      reporting_period_id: 'period-2026',
      boundary_definition_id: 'boundary-cbam-1',
    });
    // the first screen carries one concise coverage line, not the port table
    expect(screen.queryByText(/已计入 [\d,]+(\.\d+)? kg CO2e/)).not.toBeInTheDocument();
    expect(screen.getByText('1 项待补资料')).toBeInTheDocument();
    expect(screen.queryByText(/边界覆盖：28 个端口/)).not.toBeInTheDocument();
    expect(screen.queryByText(/ST-18/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '详情' }));
    expect(await screen.findByText(/ST-18/)).toBeInTheDocument();
    expect(screen.getByText(/缺口引用 MG-S09/)).toBeInTheDocument();
    expect(screen.getByText(/nebula\.iron-steel\.bf-bof-crude-steel@1\.0\.0 boundaries\/cbam\.json/)).toBeInTheDocument();
    // the v1 chart renderer refuses a multi-process result, so no chart request is made for it
    expect(api.cbamTrialChart).not.toHaveBeenCalled();
  });

  it('sends no boundary for a v1 package, which accepts none', async () => {
    mockReads();
    renderPanel('/applications/app-1/results?view=cbam&cbam-tab=simple', <Panel cbamBoundaries={[cbamBoundary]} />);

    expect(await screen.findByText('Ammonia simple goods')).toBeInTheDocument();
    expect(vi.mocked(api.cbamTrial).mock.calls[0][1]).toEqual({ method_package_ref: 'cbam.simple@1.0.0', reporting_period_id: 'period-2026' });
    expect(vi.mocked(api.cbamTrial).mock.calls[0][1]).not.toHaveProperty('boundary_definition_id');
    expect(screen.queryByText('冻结核算边界')).not.toBeInTheDocument();
    expect(api.cbamTrialChart).toHaveBeenCalledTimes(1);
  });

  it('selects the boundary pinned to the edited graph instead of the original template', async () => {
    mockReads();
    vi.spyOn(api, 'cbamTrial').mockResolvedValue(v2Result);
    const edited = {...snapshot, provider_receipt: {snapshot_ref: {graph_hash: 'edited-graph'}}};
    renderPanel('/applications/app-1/results?view=cbam&cbam-tab=simple', <Panel snapshot={edited}
      boundaryRequiredFor={['cbam.simple@1.0.0']} cbamBoundaries={[
        {...cbamBoundary, geographic_scope: {graph_sha256: 'original-graph'}},
        {...cbamBoundary, id: 'edited-boundary', geographic_scope: {graph_sha256: 'edited-graph'}},
      ]} />);
    await screen.findByText('Crude steel');
    expect(api.cbamTrial).toHaveBeenCalledWith('snapshot-1', expect.objectContaining({boundary_definition_id: 'edited-boundary'}));
  });

  it('names the missing frozen boundary instead of sending a v2 request that can only be refused', async () => {
    mockReads();
    vi.spyOn(api, 'cbamTrial').mockResolvedValue(v2Result);
    renderPanel('/applications/app-1/results?view=cbam&cbam-tab=simple', <Panel boundaryRequiredFor={['cbam.simple@1.0.0']} />);

    expect(await screen.findByText('缺少冻结核算边界')).toBeInTheDocument();
    expect(screen.getByText('当前方法和报告期下没有可用的冻结边界，暂时无法试算。')).toBeInTheDocument();
    expect(screen.getByText(/请安装包含 CBAM 边界的标准模型/)).toBeInTheDocument();
    expect(api.cbamTrial).not.toHaveBeenCalled();
    expect(screen.queryByText('Crude steel')).not.toBeInTheDocument();
  });

  it('rejects a deep link to a boundary frozen for another method package rather than substituting one', async () => {
    mockReads();
    vi.spyOn(api, 'cbamTrial').mockResolvedValue(v2Result);
    renderPanel('/applications/app-1/results?view=cbam&cbam-tab=simple&cbam-boundary=boundary-of-other-package',
      <Panel boundaryRequiredFor={['cbam.simple@1.0.0']} cbamBoundaries={[cbamBoundary]} />);

    expect(await screen.findByText(/冻结核算边界「boundary-of-other-package」不属于当前对象或已不存在/)).toBeInTheDocument();
    expect(api.cbamTrial).not.toHaveBeenCalled();
  });

  it('shows the real steel CBAM trial and unresolved coverage in English', async () => {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, 'en');
    mockReads();
    vi.spyOn(api, 'cbamTrial').mockResolvedValue({
      ...v2Result,
      specific_embedded_emissions: { ...v2Result.specific_embedded_emissions, partial_result: true },
    });
    renderPanel('/applications/app-1/results?view=cbam&cbam-tab=simple',
      <Panel boundaryRequiredFor={['cbam.simple@1.0.0']} cbamBoundaries={[cbamBoundary]} />);

    expect(await screen.findByText('Crude steel')).toBeInTheDocument();
    expect(screen.getByText('Included direct emissions intensity')).toBeInTheDocument();
    expect(screen.getByText('No eligible emission factor')).toBeInTheDocument();
    expect(screen.getByText('1 missing items')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Details' }));
    expect(await screen.findByText('Unresolved coverage items')).toBeInTheDocument();
    expect(api.cbamTrial).toHaveBeenCalledWith('snapshot-1', expect.objectContaining({ boundary_definition_id: cbamBoundary.id }));
  });
});
