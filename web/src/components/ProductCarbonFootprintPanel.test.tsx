import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ReactElement } from 'react';
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
  snapshotId: 'snapshot-1',
  methodPackages: [{ reference: 'pcf.bound@1.0.0', label: 'Bound package' }],
  selectedMethodPackageRef: 'pcf.bound@1.0.0',
  onMethodPackageChange: vi.fn(),
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
  return render(element, { wrapper: I18nProvider });
}

afterEach(() => {
  cleanup();
  window.localStorage.removeItem(LANGUAGE_STORAGE_KEY);
  vi.restoreAllMocks();
});

describe('Product carbon footprint panel', () => {
  it('uses English result labels and a localized missing-name state without changing source identity', () => {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, 'en');
    renderPanel(<ProductCarbonFootprintPanel {...baseProps} />);
    expect(screen.getAllByText('Foreground climate change result')).toHaveLength(2);
    expect(screen.getByText('Process name unavailable')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Export' })).toBeInTheDocument();
    expect(screen.queryByText('process-hotspot')).not.toBeInTheDocument();
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
    await waitFor(() => expect(api.productCarbonFootprintExport).toHaveBeenCalledWith('snapshot-1', 'pcf.bound@1.0.0'));
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
});
