import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/client';
import type { CasePackCatalogResponse, SolvedSystemSnapshot } from '../api/types';
import { ScenariosPage } from './ScenariosPage';
beforeEach(() => {
  vi.spyOn(api, 'capabilities').mockResolvedValue({ schema_version: 'nebula_one.capabilities.v1', engine: { status: 'ready' }, items: [
    { key: 'mfa.solved.v1', name: 'MFA', execution: 'snapshot', basis: '', limits: [], status: 'ready' },
    { key: 'lcia.nebula.v1', name: 'LCIA', execution: 'provider', basis: '', limits: [], status: 'ready' },
    { key: 'pcf.product.v1', name: 'PCF', execution: 'snapshot', basis: '', limits: [], status: 'ready' },
  ] });
});

const resolvedHash = 'a'.repeat(64);
const revisionHash = 'b'.repeat(64);
const catalog: CasePackCatalogResponse = {
  schema_version: 'nebula.casepack-catalog.v1', issues: [], items: [{
    id: 'petrochemical-refinery-reference', version: '0.1.2', title: '石化案例', lifecycle_status: 'executable', claim_level: 'demonstration',
    provider: 'nebula-lca', provider_contract: 'provider.v1', expected_graph_sha256: 'graph-hash', case_pack_sha256: 'c'.repeat(64), license_audit_status: 'complete', publication_gate: 'eligible', system_summary: null,
    showcase: { title: '石化案例', description: '', modules: [{ key: 'pcf', title: '产品碳足迹', description: '', application_case_id: 'diesel-product-lca', capability_keys: ['pcf.product.v1'] }] },
    applications: [{ id: 'diesel-product-lca', version: '0.1.1', title: '低硫柴油产品 LCA', case_type: 'integration', lifecycle_status: 'executable', study_frame_id: 'frame-1', study_frame_title: '产品研究框架', study_frame_status: 'frozen', demand_type: 'scaled_reference_product', demand: [{ reference_flow_uuid: 'flow-final', amount: 1, unit: 'kg', unit_group_uuid: 'mass', unit_group_version: '1' }], capabilities: ['mfa.solved.v1', 'lcia.nebula.v1', 'pcf.product.v1'], blocked_capabilities: [], method_packages: [{ path: 'methods/pcf.json', package_id: 'pcf.bound', version: '2.0.0', content_sha256: 'method-hash' }], resolved_case_sha256: resolvedHash }],
  }],
};
const solved: SolvedSystemSnapshot = {
  id: 'snapshot-new', application_id: 'app-1', system_revision_id: 'revision-1', inventory_snapshot_id: null, parameter_set_id: null, solve_hash: 'solve-hash', provider: 'nebula-lca', provider_receipt: {}, functional_unit: {}, database_release: 'EF3.1', solver_version: 'provider-v1', activity_vector: [], scaled_technosphere_exchanges: [], scaled_elementary_exchanges: [], internal_transfers: [], boundary_flows: [], process_balance_residuals: [], contribution_graph: {}, lcia_results: {}, content_sha256: 'd'.repeat(64), created_at: '2026-08-31T08:00:00Z',
};

function LocationProbe() { const location = useLocation(); return <div data-testid="location">{location.pathname}{location.search}</div>; }

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.restoreAllMocks();
});

describe('Unified analysis workbench', () => {
  it('runs one exact CasePack demand and restores the frozen result route', async () => {
    vi.spyOn(api, 'application').mockResolvedValue({ id: 'app-1', name: '产品分析', application_type: 'system_analysis', description: null, context: { case_pack_id: 'petrochemical-refinery-reference', resolved_case_sha256: resolvedHash, method_package_refs: ['pcf.bound@2.0.0'] }, status: 'active', created_at: solved.created_at, updated_at: solved.created_at });
    vi.spyOn(api, 'methodPackages').mockResolvedValue([{
      id: 'method-1', package_id: 'pcf.bound', version: '2.0.0', package_kind: 'product_carbon_footprint', jurisdiction: null, valid_from: null, valid_to: null,
      manifest: { formula_graph: { lcia_method: 'Case-bound climate method' } }, content_sha256: 'method-hash', status: 'active', created_at: solved.created_at,
    }]);
    vi.spyOn(api, 'casepacks').mockResolvedValue(catalog);
    vi.spyOn(api, 'models').mockResolvedValue([{ id: 'model-1', application_id: 'app-1', name: '石化 System', provider: 'nebula-lca', provider_base_url: 'http://provider.test', upstream_project_id: 'inline', upstream_version: 1, graph_sha256: 'graph-hash', upstream_receipt: {}, created_at: solved.created_at }]);
    vi.spyOn(api, 'revisions').mockResolvedValue([{ id: 'revision-1', system_model_id: 'model-1', parent_revision_id: null, revision_number: 1, label: 'base', revision_kind: 'base', graph_sha256: 'graph-hash', content_sha256: revisionHash, status: 'published', created_at: solved.created_at, published_at: solved.created_at }]);
    vi.spyOn(api, 'scenarios').mockResolvedValue([]);
    vi.spyOn(api, 'comparisons').mockResolvedValue([]);
    vi.spyOn(api, 'comparisonRuns').mockResolvedValue([]);
    vi.spyOn(api, 'solvedSnapshots').mockResolvedValue([]);
    const solve = vi.spyOn(api, 'solveAndFreeze').mockResolvedValue(solved);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/applications/app-1/workbench?module=pcf']}><Routes><Route path="/applications/:applicationId/workbench" element={<ScenariosPage />} /><Route path="/applications/:applicationId/results" element={<LocationProbe />} /></Routes></MemoryRouter></QueryClientProvider>);

    expect(await screen.findByText('产品研究框架')).toBeInTheDocument();
    const runButton = screen.getByRole('button', { name: '运行并冻结结果' });
    await waitFor(() => expect(runButton).toBeEnabled());
    const lciaModule = screen.getByRole('checkbox', { name: 'LCIA' });
    expect(screen.getByRole('checkbox', { name: 'PCF' })).toBeChecked();
    expect(screen.getByText(/Case-bound climate method/)).toBeInTheDocument();
    await userEvent.click(runButton);
    await waitFor(() => expect(solve).toHaveBeenCalledWith('app-1', 'revision-1', expect.objectContaining({
      demand: [{ reference_flow_uuid: 'flow-final', amount: 1, unit: 'kg', unit_group_uuid: 'mass', unit_group_version: '1' }],
      lcia_methods: ['Case-bound climate method'],
    })));
    expect(await screen.findByTestId('location')).toHaveTextContent('/applications/app-1/results?snapshot=snapshot-new&view=pcf');
  });

  it('fails closed when the bound PCF package does not declare an LCIA method', async () => {
    vi.spyOn(api, 'application').mockResolvedValue({ id: 'app-1', name: '产品分析', application_type: 'system_analysis', description: null, context: { case_pack_id: 'petrochemical-refinery-reference', resolved_case_sha256: resolvedHash, method_package_refs: ['pcf.bound@2.0.0'] }, status: 'active', created_at: solved.created_at, updated_at: solved.created_at });
    vi.spyOn(api, 'methodPackages').mockResolvedValue([{
      id: 'method-1', package_id: 'pcf.bound', version: '2.0.0', package_kind: 'product_carbon_footprint', jurisdiction: null, valid_from: null, valid_to: null,
      manifest: { formula_graph: {} }, content_sha256: 'method-hash', status: 'active', created_at: solved.created_at,
    }]);
    vi.spyOn(api, 'casepacks').mockResolvedValue(catalog);
    vi.spyOn(api, 'models').mockResolvedValue([{ id: 'model-1', application_id: 'app-1', name: '石化 System', provider: 'nebula-lca', provider_base_url: 'http://provider.test', upstream_project_id: 'inline', upstream_version: 1, graph_sha256: 'graph-hash', upstream_receipt: {}, created_at: solved.created_at }]);
    vi.spyOn(api, 'revisions').mockResolvedValue([{ id: 'revision-1', system_model_id: 'model-1', parent_revision_id: null, revision_number: 1, label: 'base', revision_kind: 'base', graph_sha256: 'graph-hash', content_sha256: revisionHash, status: 'published', created_at: solved.created_at, published_at: solved.created_at }]);
    vi.spyOn(api, 'scenarios').mockResolvedValue([]);
    vi.spyOn(api, 'comparisons').mockResolvedValue([]);
    vi.spyOn(api, 'comparisonRuns').mockResolvedValue([]);
    vi.spyOn(api, 'solvedSnapshots').mockResolvedValue([]);
    const solve = vi.spyOn(api, 'solveAndFreeze').mockResolvedValue(solved);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/applications/app-1/workbench']}><Routes><Route path="/applications/:applicationId/workbench" element={<ScenariosPage />} /></Routes></MemoryRouter></QueryClientProvider>);

    expect(await screen.findByText('产品碳足迹暂不可运行')).toBeInTheDocument();
    const lciaModule = screen.getByRole('checkbox', { name: 'LCIA' });
    await userEvent.click(lciaModule);
    expect(screen.getByRole('button', { name: '运行并冻结结果' })).toBeDisabled();
    expect(solve).not.toHaveBeenCalled();
  });
});
