import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError, retryAfterTransientFailure } from './client';

afterEach(() => vi.restoreAllMocks());

describe('Nebula One API client', () => {
  it('posts one structured comparison request to the versioned contract', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ id: 'run-1' }), { status: 200 }));
    const payload = { baseline_scenario_id: 'scenario-base', demand: [{ reference_flow_uuid: 'flow-final', amount: 1, unit: 'kg' }] };
    await api.executeComparison('comparison-1', payload);
    expect(fetchSpy).toHaveBeenCalledOnce();
    expect(fetchSpy).toHaveBeenCalledWith('/api/v1/comparisons/comparison-1/execute', expect.objectContaining({ method: 'POST', body: JSON.stringify(payload) }));
  });

  it('keeps provider failures actionable without exposing a raw response body', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ error: { code: 'PROVIDER_FAILED', message: '求解服务未完成请求', details: {} } }), { status: 409 }));
    await expect(api.comparisonRun('missing')).rejects.toEqual(expect.objectContaining({ status: 409, code: 'PROVIDER_FAILED', message: '求解服务未完成请求', name: 'ApiError' } satisfies Partial<ApiError>));
  });

  it('carries the rejection details that explain which contract was refused', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ error: {
      code: 'GHG_INVENTORY_CALCULATION_CONTRACT_UNSUPPORTED',
      message: '已固定版本的方法包未声明本实现使用的 Scope 1 计算合同。',
      details: { required_contract: 'scope1_period_scaling.v1', declared_contract: null },
    } }), { status: 409 }));
    await expect(api.comparisonRun('missing')).rejects.toEqual(expect.objectContaining({
      code: 'GHG_INVENTORY_CALCULATION_CONTRACT_UNSUPPORTED',
      details: { required_contract: 'scope1_period_scaling.v1', declared_contract: null },
    } satisfies Partial<ApiError>));
  });

  it('binds PCF result and SVG requests to the same exact method package reference', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({ content_sha256: 'pcf-hash' }), { status: 200 }))
      .mockResolvedValueOnce(new Response('<svg />', { status: 200, headers: { 'Content-Type': 'image/svg+xml' } }))
      .mockResolvedValueOnce(new Response('xlsx', { status: 200 }))
      .mockResolvedValueOnce(new Response('<html />', { status: 200, headers: { 'Content-Type': 'text/html' } }));

    await api.productCarbonFootprint('snapshot-1', 'pcf.example@1.2.3');
    await api.productCarbonFootprintChart('snapshot-1', 'pcf.example@1.2.3');
    await api.productCarbonFootprintExport('snapshot-1', 'pcf.example@1.2.3');
    await api.productCarbonFootprintReport('snapshot-1', 'pcf.example@1.2.3');

    const expectedBody = JSON.stringify({ method_package_ref: 'pcf.example@1.2.3' });
    expect(fetchSpy).toHaveBeenNthCalledWith(1, '/api/v1/solved-system-snapshots/snapshot-1/product-carbon-footprint', expect.objectContaining({ method: 'POST', body: expectedBody }));
    expect(fetchSpy).toHaveBeenNthCalledWith(2, '/api/v1/solved-system-snapshots/snapshot-1/product-carbon-footprint/chart.svg', expect.objectContaining({ method: 'POST', body: expectedBody }));
    expect(fetchSpy.mock.calls[2][0]).toBe('/api/v1/solved-system-snapshots/snapshot-1/product-carbon-footprint/export.xlsx?method_package_ref=pcf.example%401.2.3');
    expect(fetchSpy.mock.calls[3][0]).toBe('/api/v1/solved-system-snapshots/snapshot-1/product-carbon-footprint/report.html?method_package_ref=pcf.example%401.2.3');
    expect(fetchSpy.mock.calls[2][1]).not.toHaveProperty('method');
    expect(fetchSpy.mock.calls[3][1]).not.toHaveProperty('method');
  });

  it('reads native climate artifacts from the frozen snapshot with no method selection', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response('xlsx', { status: 200 }))
      .mockResolvedValueOnce(new Response('<html />', { status: 200, headers: { 'Content-Type': 'text/html' } }));

    await api.nativeClimateExport('snapshot-1');
    await api.nativeClimateReport('snapshot-1');

    expect(fetchSpy.mock.calls[0][0]).toBe('/api/v1/solved-system-snapshots/snapshot-1/native-background-climate/export.xlsx');
    expect(fetchSpy.mock.calls[1][0]).toBe('/api/v1/solved-system-snapshots/snapshot-1/native-background-climate/report.html');
    for (const call of fetchSpy.mock.calls) {
      // A saved climate answer is re-read as it was frozen: no package ref, nothing resolved as latest.
      expect(String(call[0])).not.toMatch(/method_package_ref|latest|active/);
      expect(call[1]).not.toHaveProperty('method');
    }
  });

  it('uses application-scoped binding and formal organization inventory contracts', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ content_sha256: 'organization-hash' }), { status: 200 }))
      .mockResolvedValueOnce(new Response('<svg />', { status: 200, headers: { 'Content-Type': 'image/svg+xml' } }));
    const payload = {
      method_package_ref: 'ghg.organization@1.0.0',
      pcf_method_package_ref: 'pcf.product@1.0.0',
      binding_ids: ['scope-1', 'scope-2', 'scope-3-crude', 'scope-3-transport'],
    };

    await api.systemBindings('app-1');
    await api.organizationGhgInventoryV1('app-1', payload);
    await api.organizationGhgInventoryV1Chart('app-1', payload);

    expect(fetchSpy.mock.calls[0][0]).toBe('/api/v1/applications/app-1/system-bindings');
    expect(fetchSpy).toHaveBeenNthCalledWith(2, '/api/v1/applications/app-1/organization-ghg-inventory', expect.objectContaining({ method: 'POST', body: JSON.stringify(payload) }));
    expect(fetchSpy).toHaveBeenNthCalledWith(3, '/api/v1/applications/app-1/organization-ghg-inventory/chart.svg', expect.objectContaining({ method: 'POST', body: JSON.stringify(payload) }));
  });

  it('posts the same frozen precursor contract to complex CBAM result and chart endpoints', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({ content_sha256: 'cbam-hash' }), { status: 200 }))
      .mockResolvedValueOnce(new Response('<svg />', { status: 200, headers: { 'Content-Type': 'image/svg+xml' } }));
    const payload = {
      method_package_ref: 'cbam.complex@1.0.0',
      reporting_period_id: 'period-2026',
      precursors: [{ solved_snapshot_id: 'snapshot-1', method_package_ref: 'cbam.simple@1.0.0' }],
    };

    await api.cbamComplexTrial('snapshot-1', payload);
    await api.cbamComplexTrialChart('snapshot-1', payload);

    expect(fetchSpy).toHaveBeenNthCalledWith(1, '/api/v1/solved-system-snapshots/snapshot-1/cbam-complex-trial', expect.objectContaining({ method: 'POST', body: JSON.stringify(payload) }));
    expect(fetchSpy).toHaveBeenNthCalledWith(2, '/api/v1/solved-system-snapshots/snapshot-1/cbam-complex-trial/chart.svg', expect.objectContaining({ method: 'POST', body: JSON.stringify(payload) }));
  });

  it('retries only transient conditions, never a refusal', () => {
    expect(retryAfterTransientFailure(0, new ApiError('refused', 422, 'CBAM_TRIAL_ACTIVITY_NOT_UNIQUE'))).toBe(false);
    expect(retryAfterTransientFailure(0, new ApiError('conflict', 409, 'STATE_CONFLICT'))).toBe(false);
    expect(retryAfterTransientFailure(0, new ApiError('timeout', 408))).toBe(true);
    expect(retryAfterTransientFailure(0, new ApiError('rate limited', 429))).toBe(true);
    expect(retryAfterTransientFailure(0, new ApiError('engine down', 503))).toBe(true);
    expect(retryAfterTransientFailure(1, new ApiError('engine down', 503))).toBe(false);
    expect(retryAfterTransientFailure(0, new TypeError('Failed to fetch'))).toBe(true);
    expect(retryAfterTransientFailure(1, new TypeError('Failed to fetch'))).toBe(false);
  });
});
