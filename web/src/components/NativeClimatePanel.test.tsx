import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/client';
import type { NativeClimateAnswer, NativeClimateEnvelope } from '../api/types';
import { NativeClimatePanel } from './NativeClimatePanel';

const answer: NativeClimateAnswer = {
  schema_version: 'provider.native-background-climate-total.response.v1',
  method_package_id: 'ecoinvent-ef31-climate-total-3.11',
  method_package_version: '1.0.0',
  method_package_sha256: 'f'.repeat(64),
  runtime_manifest_sha256: 'e'.repeat(64),
  indicator: { method: 'EF v3.1', category: 'climate change', name: 'GWP100', unit: 'kg CO2-Eq' },
  merge_status: 'merged',
  merge_blockers: [],
  unified_climate_total: 2.0883914,
  domains: {
    foreground: { source_namespace: 'inline_custom', contribution_value: 1.5, indicator_unit: 'kg CO2-Eq', coverage: { explicit_nonzero: 12 }, negative_cf_exchange_count: 0, terms: [] },
    native_background: { source_namespace: 'tiangong_open_data', contribution_value: 0.5883914, indicator_unit: 'kg CO2-Eq', coverage: { explicit_nonzero: 83, no_cf: 2654 }, negative_cf_exchange_count: 1, terms: [] },
  },
  provider_system_model_evidence: 'not_asserted_by_local_vector_metadata',
  carbon_storage_permanence: 'not_assessed',
  claim_limit: 'Partial background coverage only; this is not a complete product carbon footprint.',
};

const envelope: NativeClimateEnvelope = {
  schema_version: 'nebula_one.native-background-climate.v1',
  source_contract: { repository: 'nebula-lca', commit: '2c3ebd7e72be644db47e1f9049417aa1cf8bf6d3', document: 'docs/PROVIDER_NATIVE_CLIMATE_TOTAL_V1.md', document_sha256: 'd'.repeat(64) },
  request: {
    schema_version: 'provider.native-background-climate-total.request.v1', database_release: 'ecoinvent_3.11',
    method_package_id: 'ecoinvent-ef31-climate-total-3.11', method_package_version: '1.0.0',
    method_package_sha256: 'f'.repeat(64), runtime_manifest_sha256: 'e'.repeat(64),
    flow_snapshot_hash: 'a'.repeat(64), reference_dependency_snapshot_hash: 'b'.repeat(64),
  },
  response: answer,
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('NativeClimatePanel', () => {
  it('reports the merged total, the pinned method and the coverage in operator terms', () => {
    const { container } = render(<NativeClimatePanel envelope={envelope} snapshotId="snapshot-1" />);
    expect(screen.getByText('2.0883914')).toBeInTheDocument();
    expect(screen.getByText('ecoinvent-ef31-climate-total-3.11 · 1.0.0')).toBeInTheDocument();
    // A coverage dictionary only lists the states the solve met, so a missing key is not a zero row.
    expect(screen.getByText(/有非零排放因子 83 项/).textContent).toMatch(/未纳入特征化 2,654 项/);
    expect(screen.queryByText(/因子明确为零/)).toBeNull();
    expect(screen.getByText(/抵消性的投入输出，不等于永久碳移除/)).toBeInTheDocument();
    expect(container.querySelectorAll('.native-climate-domain-row')).toHaveLength(2);
    expect(container.querySelector('.native-climate-domain-row')).toHaveTextContent(/前台生产过程\s*1\.5 kg CO2-Eq/);
  });

  it('keeps the commercial rows out of the product page and parks the identity hashes in details', () => {
    const { container } = render(<NativeClimatePanel envelope={envelope} snapshotId="snapshot-1" />);
    expect(screen.getByText(/不展示逐条背景交换明细/)).toBeInTheDocument();
    const evidence = container.querySelector('details');
    expect(evidence).not.toHaveTextContent('provider.native-background-climate-total.response.v1');
    expect(evidence).toHaveTextContent('f'.repeat(64));
    expect(evidence).toHaveTextContent(/2c3ebd7e72be\b/);
    expect(evidence).toHaveTextContent('ecoinvent_3.11');
  });

  it('shows split domains without inventing a total the source did not merge', () => {
    const split: NativeClimateEnvelope = { ...envelope, response: { ...answer, merge_status: 'split_diagnostic', unified_climate_total: null, merge_blockers: [{ domain: 'native_background', reason: 'unit_group_mismatch' }] } };
    const { container } = render(<NativeClimatePanel envelope={split} snapshotId="snapshot-1" />);
    expect(screen.queryByText('2.0883914')).toBeNull();
    expect(screen.getByText('本次结果按来源分域给出，未合并')).toBeInTheDocument();
    expect(screen.getByText(/domain: native_background · reason: unit_group_mismatch/)).toBeInTheDocument();
    // Each domain keeps its own number, and the page states the two must not be added together.
    expect(container.querySelectorAll('.native-climate-domain-row')).toHaveLength(2);
    expect(screen.getByText(/相加/)).toBeInTheDocument();
  });

  it('refuses to present a total the source did not compute', () => {
    const broken: NativeClimateEnvelope = { ...envelope, response: { ...answer, unified_climate_total: null } };
    render(<NativeClimatePanel envelope={broken} snapshotId="snapshot-1" />);
    expect(screen.getByText('合并状态缺少合计')).toBeInTheDocument();
    expect(screen.queryByText('2.0883914')).toBeNull();
  });

  it('states a machine-token claim limit in operator terms', () => {
    const literal: NativeClimateEnvelope = { ...envelope, response: { ...answer, claim_limit: 'partial_background_leaf_only_not_complete_product_carbon_footprint' } };
    render(<NativeClimatePanel envelope={literal} snapshotId="snapshot-1" />);
    expect(screen.getByText('背景覆盖止于已关联的背景供应叶子，本结果不构成完整产品碳足迹')).toBeInTheDocument();
    expect(screen.queryByText('partial_background_leaf_only_not_complete_product_carbon_footprint')).toBeNull();
  });

  it('builds both artifacts from the frozen snapshot the panel is showing', async () => {
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:artifact') });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
    const excel = vi.spyOn(api, 'nativeClimateExport').mockResolvedValue(new Blob(['xlsx']));
    const report = vi.spyOn(api, 'nativeClimateReport').mockResolvedValue(new Blob(['<html />'], { type: 'text/html' }));
    const reportWindow = { opener: window, location: { href: '' }, close: vi.fn() } as unknown as Window;
    vi.spyOn(window, 'open').mockReturnValue(reportWindow);
    render(<NativeClimatePanel envelope={envelope} snapshotId="snapshot-1" />);

    await userEvent.click(screen.getByRole('button', { name: 'Excel 明细' }));
    await waitFor(() => expect(excel).toHaveBeenCalledWith('snapshot-1'));
    expect(screen.getByRole('button', { name: 'HTML 报告' })).toBeEnabled();

    await userEvent.click(screen.getByRole('button', { name: 'HTML 报告' }));
    await waitFor(() => expect(report).toHaveBeenCalledWith('snapshot-1'));
    expect(reportWindow.location.href).toBe('blob:artifact');
    expect(reportWindow.opener).toBeNull();
  });

  it('surfaces a failed artifact and retries the same action', async () => {
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:artifact') });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
    const excel = vi.spyOn(api, 'nativeClimateExport')
      .mockRejectedValueOnce(new Error('部分背景气候结果 Excel 暂时无法下载，请稍后重试。'))
      .mockResolvedValueOnce(new Blob(['xlsx']));
    render(<NativeClimatePanel envelope={envelope} snapshotId="snapshot-1" />);

    await userEvent.click(screen.getByRole('button', { name: 'Excel 明细' }));
    expect(await screen.findByText('部分背景气候结果 Excel 暂时无法下载，请稍后重试。')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '重新加载' }));
    await waitFor(() => expect(excel).toHaveBeenCalledTimes(2));
  });
});
