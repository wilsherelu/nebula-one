import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import { api, ApiError } from '../api/client';
import { createAppQueryClient } from '../api/queryClient';
import { I18nProvider, LANGUAGE_STORAGE_KEY } from '../i18n';
import type { BoundaryDefinition, MethodPackage, SolvedSystemSnapshot } from '../api/types';
import { CbamPartialReviewPanel } from './CbamPartialReviewPanel';

const basis = { purpose: 'cbam', demand: [{ flow_uuid: 'steel', amount: 1, unit: 'kg' }],
  model_derivation: { source_graph_sha256: 'graph-hash' } };
const makeSnapshot = (id: string): SolvedSystemSnapshot => ({
  id, application_id: 'app', system_revision_id: 'revision', inventory_snapshot_id: null,
  parameter_set_id: null, solve_hash: id, provider: 'provider', provider_receipt: { calculation_basis: basis },
  functional_unit: {}, database_release: 'release', solver_version: '1', activity_vector: [],
  scaled_technosphere_exchanges: [], scaled_elementary_exchanges: [], internal_transfers: [], boundary_flows: [],
  process_balance_residuals: [], contribution_graph: {}, lcia_results: {}, content_sha256: id,
  created_at: '2026-09-25T00:00:00Z',
});
const method = { package_id: 'partial', version: '1.0.2', package_kind: 'cbam_partial_review',
  manifest: { formula_graph: { source_direct_method: { reference: 'direct@1' } } } } as unknown as MethodPackage;
const boundary = { id: 'boundary', method_package_ref: 'direct@1', status: 'frozen', period_id: 'period',
  geographic_scope: { graph_sha256: 'graph-hash', source_system_revision_id: 'revision' } } as unknown as BoundaryDefinition;

afterEach(() => { cleanup(); window.localStorage.removeItem(LANGUAGE_STORAGE_KEY); vi.restoreAllMocks(); });

it('shows an English missing-boundary state without making up an emissions total', async () => {
  window.localStorage.setItem(LANGUAGE_STORAGE_KEY, 'en');
  vi.spyOn(api, 'periods').mockResolvedValue([]);
  render(<I18nProvider><QueryClientProvider client={createAppQueryClient()}><CbamPartialReviewPanel applicationId="app"
    snapshot={makeSnapshot('selected')} snapshots={[makeSnapshot('selected')]} method={method}
    boundaries={[]} /></QueryClientProvider></I18nProvider>);
  expect(await screen.findByText('This record has no matching frozen CBAM boundary. Add evidence or return to the project and calculate again.')).toBeInTheDocument();
  expect(screen.getByText('Trial result, not for official filing')).toBeInTheDocument();
  expect(screen.queryByText('0', { selector: 'strong' })).not.toBeInTheDocument();
});

it.each([['earlier first', ['earlier', 'selected']], ['selected first', ['selected', 'earlier']]])(
  'uses the selected CBAM solve for request and export when %s', async (_name, order) => {
    vi.spyOn(api, 'periods').mockResolvedValue([{ id: 'period', name: '2026' }] as Awaited<ReturnType<typeof api.periods>>);
    const request = vi.spyOn(api, 'cbamPartialReview').mockResolvedValue({
      components: { direct: { value: '1.0', unit: 't CO2e/t product', exchanges: [] },
        sinter_precursor_indirect: { electricity_activity: { value: '0.1', unit: 'MWh/t product' }, value: null, unit: 't CO2e/t product' } },
      specific_embedded_emissions: { value: null, unit: 't CO2e/t product' }, coverage: { missing: ['eligible_sinter_electricity_factor'] }, method_package: { reference: 'partial@1.0.2' },
      source_snapshot: { id: 'selected' }, content_sha256: 'hash',
    } as unknown as Awaited<ReturnType<typeof api.cbamPartialReview>>);
    const report = vi.spyOn(api, 'cbamPartialReviewReport').mockResolvedValue(new Blob(['report']));
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:report') });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<I18nProvider><QueryClientProvider client={client}><CbamPartialReviewPanel applicationId="app"
      snapshot={makeSnapshot('selected')} snapshots={order.map(makeSnapshot)} method={method}
      boundaries={[boundary]} /></QueryClientProvider></I18nProvider>);
    await waitFor(() => expect(request).toHaveBeenCalledWith('selected', expect.objectContaining({ boundary_definition_id: 'boundary' })));
    await userEvent.click(await screen.findByRole('button', { name: '下载复核记录' }));
    await waitFor(() => expect(report).toHaveBeenCalledWith('selected', expect.objectContaining({ boundary_definition_id: 'boundary' })));
  },
);

it('settles a transient CBAM failure after the bounded retry', async () => {
  vi.spyOn(api, 'periods').mockResolvedValue([{ id: 'period', name: '2026' }] as Awaited<ReturnType<typeof api.periods>>);
  const request = vi.spyOn(api, 'cbamPartialReview').mockRejectedValue(new ApiError('CBAM service temporarily unavailable', 503));
  render(<I18nProvider><QueryClientProvider client={createAppQueryClient()}><CbamPartialReviewPanel applicationId="app"
    snapshot={makeSnapshot('selected')} snapshots={[makeSnapshot('selected')]} method={method}
    boundaries={[boundary]} /></QueryClientProvider></I18nProvider>);
  expect(await screen.findByText('CBAM service temporarily unavailable', undefined, { timeout: 4_000 })).toBeInTheDocument();
  expect(request).toHaveBeenCalledTimes(2);
  await new Promise(resolve => setTimeout(resolve, 1_200));
  expect(request).toHaveBeenCalledTimes(2);
});

it('keeps the partial result readable and opens the real evidence inputs on demand', async () => {
  vi.spyOn(api, 'periods').mockResolvedValue([{ id: 'period', name: '2026' }] as Awaited<ReturnType<typeof api.periods>>);
  vi.spyOn(api, 'cbamPartialReview').mockResolvedValue({
    components: { direct: { value: '1.951739734', unit: 't CO2e/t product', exchanges: [] },
      sinter_precursor_indirect: { electricity_activity: { value: '0.166667', unit: 'MWh/t product' },
        value: null, unit: 't CO2e/t product' },
      user_supply_electricity_trial: { value: '0.089906111', unit: 't CO2/t product',
        source_project_id: 'my-supply', source_version: 3, status: 'user_declared_trial_not_eligible_cbam_factor' } },
    specific_embedded_emissions: { value: null, unit: 't CO2e/t product' },
    coverage: { missing: ['eligible_sinter_electricity_factor', 'article_4_9'] },
    method_package: { reference: 'partial@1.0.2' }, source_snapshot: { id: 'selected' }, content_sha256: 'result-hash',
  } as unknown as Awaited<ReturnType<typeof api.cbamPartialReview>>);
  const evidenceMethod = { ...method, manifest: { formula_graph: { source_direct_method: { reference: 'direct@1' },
    required_condition_keys: ['article_4_9'], condition_labels: { article_4_9: '同一设施归属' },
    condition_rules: { article_4_9: { allowed_statuses: [{ code: 'verified', label: '已核验' }] } } } } } as MethodPackage;
  render(<I18nProvider><QueryClientProvider client={createAppQueryClient()}><CbamPartialReviewPanel applicationId="app"
    snapshot={makeSnapshot('selected')} snapshots={[makeSnapshot('selected')]} method={evidenceMethod}
    boundaries={[boundary]} /></QueryClientProvider></I18nProvider>);
  expect(await screen.findByText('待补充：适用电力因子、归属证据')).toBeInTheDocument();
  expect(screen.getByText('1.95174')).toBeInTheDocument();
  expect(screen.getByText('待补充', { selector: 'strong' })).toBeInTheDocument();
  expect(screen.getByText('未计算', { selector: 'strong' })).toBeInTheDocument();
  expect(screen.getByText('自建供电过程的本地试算')).toBeInTheDocument();
  expect(screen.getByText(/未计入上方间接分项或合计/)).toBeInTheDocument();
  expect(screen.queryByText('暂无适用因子。登记符合当前方法、活动与报告期的因子后，可继续计算间接分项。')).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: '补充资料' }));
  expect(screen.getByText('暂无适用因子。登记符合当前方法、活动与报告期的因子后，可继续计算间接分项。')).toBeInTheDocument();
  expect(screen.getByText('同一设施归属')).toBeInTheDocument();
  await userEvent.click(screen.getByText('计算依据'));
  expect(screen.getByText(/result-hash/)).toBeInTheDocument();
});
