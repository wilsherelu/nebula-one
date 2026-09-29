import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/client';
import type { Application, CapabilityCatalogResponse, CasePackCatalogResponse, CasePackMaterializeResult, SetupStatus } from '../api/types';
import { CasePacksPage } from './CasePacksPage';

const catalog: CasePackCatalogResponse = {
  schema_version: 'nebula.casepack-catalog.v1',
  issues: [],
  items: [{
    id: 'petrochemical-refinery-reference', version: '0.1.0', title: '低硫柴油炼化产业生态参考案例', lifecycle_status: 'executable', claim_level: 'demonstration',
    provider: 'nebula-lca', provider_contract: 'provider.v1', expected_graph_sha256: 'graph-hash-123', case_pack_sha256: 'casepack-hash-123', license_audit_status: 'complete', publication_gate: 'eligible',
    system_summary: {
      functional_unit: '1 kg low-sulfur diesel', process_count: 5, flow_count: 14, elementary_flow_count: 1, connection_count: 4,
      processes: [
        { id: 'distillation', name: 'Crude distillation', node_kind: 'unit_process' },
        { id: 'cracking', name: 'Catalytic cracking', node_kind: 'unit_process' },
      ],
      flow_sources: [
        { source_namespace: 'tiangong_open_data', flow_count: 3 },
        { source_namespace: 'casepack', flow_count: 11 },
      ],
    },
    showcase: {
      title: '统一石化母案例',
      description: '从同一份冻结 System 进入不同可持续分析任务。',
      modules: [
        { key: 'material-flow', title: '物质流全景', description: '追踪年度输入、转换与输出。', application_case_id: 'refinery-annual-mfa', capability_keys: ['mfa.solved.v1'] },
        { key: 'product-footprint', title: '产品碳足迹', description: '核算单位产品的气候变化影响。', application_case_id: 'diesel-product-lca', capability_keys: ['pcf.product.v1'] },
        { key: 'organization-inventory', title: '组织温室气体清单', description: '查看组织边界的范围 1–3。', application_case_id: 'diesel-product-lca', capability_keys: ['organization.ghg.v1'] },
        { key: 'cbam', title: 'CBAM 试算', description: '查看嵌入排放的试算结果。', application_case_id: 'diesel-product-lca', capability_keys: ['cbam.trial.v1'] },
      ],
    },
    applications: [
      { id: 'diesel-product-lca', version: '0.1.0', title: '低硫柴油产品 LCA', case_type: 'integration', lifecycle_status: 'executable', study_frame_id: 'product-frame', study_frame_title: '低硫柴油产品核算研究框架', study_frame_status: 'frozen', demand_type: 'scaled_reference_product', demand: [{ amount: 1000, unit: 'kg', reference_flow_uuid: 'flow-final' }], capabilities: ['mfa.solved.v1', 'lcia.nebula.v1'], blocked_capabilities: [], method_packages: [], resolved_case_sha256: 'resolved-product' },
      { id: 'refinery-annual-mfa', version: '0.1.0', title: '炼厂年度物质流分析', case_type: 'integration', lifecycle_status: 'executable', study_frame_id: 'annual-frame', study_frame_title: '炼厂年度物质流研究框架', study_frame_status: 'frozen', demand_type: 'annual_production', demand: [{ amount: 1000000, unit: 'kg', reference_flow_uuid: 'flow-final' }], capabilities: ['mfa.solved.v1'], blocked_capabilities: [], method_packages: [], resolved_case_sha256: 'resolved-annual' },
    ],
  }],
};

const capabilities: CapabilityCatalogResponse = {
  schema_version: 'nebula_one.capabilities.v1', engine: { status: 'ready' },
  items: [
    { key: 'mfa.solved.v1', name: 'Solved-system MFA and Sankey', execution: 'nebula_one_snapshot', basis: 'scaled exchanges', limits: [], status: 'ready' },
    { key: 'lcia.nebula.v1', name: 'Nebula LCA LCIA', execution: 'nebula_lca', basis: 'provider', limits: [], status: 'ready' },
  ],
};

const setupStatus: SetupStatus = {
  schema_version: 'nebula_one.setup-status.v1', status: 'ready',
  database: { status: 'ready', backend: 'sqlite', message: '本地数据存储已就绪。' },
  casepacks: { status: 'ready', count: 1, issue_count: 0, message: '案例目录已就绪。' },
  provider: { status: 'ready', base_url: 'http://127.0.0.1:8001', message: 'Nebula LCA 已连接，可以执行求解。', remediation: null, error: null },
};

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}{location.search}</div>;
}

function renderPage(entry: string, applications: Application[] = []) {
  vi.spyOn(api, 'casepacks').mockResolvedValue(catalog);
  vi.spyOn(api, 'capabilities').mockResolvedValue(capabilities);
  vi.spyOn(api, 'applications').mockResolvedValue(applications);
  vi.spyOn(api, 'setupStatus').mockResolvedValue(setupStatus);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/casepacks" element={<CasePacksPage />} />
          <Route path="/applications/:applicationId/workbench" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('CasePack catalog page', () => {
  it('restores the selected application case from the URL and keeps hashes in the audit drawer', async () => {
    renderPage('/casepacks?pack=petrochemical-refinery-reference&case=refinery-annual-mfa');
    const annual = await screen.findByRole('row', { name: /炼厂年度物质流分析/ });
    expect(annual).toHaveClass('catalog-table__selected');
    expect(screen.getAllByText('1,000,000 kg')).toHaveLength(1);
    expect(screen.queryByRole('heading', { name: 'System 基线' })).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: '统一石化母案例' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /物质流全景/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /产品碳足迹/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /组织温室气体清单/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /CBAM 试算/ })).toBeInTheDocument();
    expect(screen.queryByText('Crude distillation')).not.toBeInTheDocument();
    expect(screen.queryByText('mfa.solved.v1')).not.toBeInTheDocument();
    expect(within(annual).getByRole('button', { name: '使用案例' })).toBeEnabled();
    expect(screen.queryByRole('button', { name: '创建分析' })).not.toBeInTheDocument();
    expect(screen.queryByText('casepack-hash-123')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '审计证据' }));
    expect(await screen.findByText('casepack-hash-123')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('tab', { name: '模型与能力' }));
    expect(await screen.findByRole('heading', { name: 'System 基线' })).toBeInTheDocument();
    expect(screen.getByText('Crude distillation')).toBeInTheDocument();
    expect(await screen.findByRole('row', { name: /Solved-system MFA and Sankey/ })).toHaveTextContent('已覆盖');
    expect(screen.getByRole('row', { name: /Nebula LCA LCIA/ })).toHaveTextContent('未纳入');
  });

  it('uses a showcase module to select its backend-bound application case', async () => {
    renderPage('/casepacks?pack=petrochemical-refinery-reference&case=refinery-annual-mfa');
    expect(await screen.findByRole('row', { name: /炼厂年度物质流分析/ })).toBeInTheDocument();
    const pcfModule = screen.getByRole('button', { name: /产品碳足迹/ });
    await userEvent.click(pcfModule);
    expect(await screen.findByText('低硫柴油产品核算研究框架')).toBeInTheDocument();
    expect(pcfModule).toHaveAttribute('aria-pressed', 'true');
  });

  it('opens the exact materialized application matched by resolved case hash', async () => {
    renderPage('/casepacks?pack=petrochemical-refinery-reference&case=diesel-product-lca', [{
      id: 'app-product', name: 'Product app', application_type: 'system_analysis', description: null,
      context: { case_pack_id: 'petrochemical-refinery-reference', resolved_case_sha256: 'resolved-product' },
      status: 'active', created_at: '2026-08-31T00:00:00Z', updated_at: '2026-08-31T00:00:00Z',
    }]);
    const button = await screen.findByRole('button', { name: /产品碳足迹/ });
    await waitFor(() => expect(button).toBeEnabled());
    await userEvent.click(button);
    expect(await screen.findByTestId('location')).toHaveTextContent('/applications/app-product/workbench');
    expect(screen.getByTestId('location')).toHaveTextContent('case=diesel-product-lca&module=product-footprint');
  });

  it('materializes the selected exact CasePack once and opens its workbench', async () => {
    let finish: (result: CasePackMaterializeResult) => void = () => undefined;
    const pending = new Promise<CasePackMaterializeResult>((resolve) => { finish = resolve; });
    const materialize = vi.spyOn(api, 'materializeCasePack').mockReturnValue(pending);
    renderPage('/casepacks?pack=petrochemical-refinery-reference&case=diesel-product-lca');
    await userEvent.click(await screen.findByRole('button', { name: '产品碳足迹' }));
    const button = await screen.findByRole('button', { name: '创建分析' });
    await userEvent.click(button);
    await waitFor(() => expect(button).toBeDisabled());
    await userEvent.click(button);
    expect(materialize).toHaveBeenCalledTimes(1);
    expect(materialize).toHaveBeenCalledWith(
      'petrochemical-refinery-reference',
      '0.1.0',
      'diesel-product-lca',
      '0.1.0',
      {
        expected_case_pack_sha256: 'casepack-hash-123',
        expected_resolved_case_sha256: 'resolved-product',
      },
    );
    await act(async () => finish({
      status: 'created',
      application: {
        id: 'imported-app', name: '低硫柴油产品 LCA', application_type: 'system_analysis', description: null,
        context: { case_pack_id: 'petrochemical-refinery-reference', resolved_case_sha256: 'resolved-product' },
        status: 'active', created_at: '2026-08-31T00:00:00Z', updated_at: '2026-08-31T00:00:00Z',
      },
      system_model: {
        id: 'model-1', application_id: 'imported-app', name: '石化模型', provider: 'nebula_lca', provider_base_url: 'http://127.0.0.1:8001',
        upstream_project_id: 'casepack:petrochemical', upstream_version: 1, graph_sha256: 'graph-hash-123', upstream_receipt: {}, created_at: '2026-08-31T00:00:00Z',
      },
      base_revision: {
        id: 'revision-1', system_model_id: 'model-1', parent_revision_id: null, revision_number: 1, label: 'CasePack base', revision_kind: 'base',
        graph_sha256: 'graph-hash-123', content_sha256: 'revision-hash', status: 'draft', created_at: '2026-08-31T00:00:00Z', published_at: null,
      },
      demand: catalog.items[0].applications[0].demand,
      capabilities: ['mfa.solved.v1', 'lcia.nebula.v1'], blocked_capabilities: [], method_packages: [],
      case_pack_sha256: 'casepack-hash-123', resolved_case_sha256: 'resolved-product',
    }));
    expect(await screen.findByTestId('location')).toHaveTextContent('/applications/imported-app/workbench');
    expect(screen.getByTestId('location')).toHaveTextContent('case=diesel-product-lca&module=product-footprint');
  });

  it('filters cases without treating a same-name application with a different hash as a match', async () => {
    const materialize = vi.spyOn(api, 'materializeCasePack');
    renderPage('/casepacks?pack=petrochemical-refinery-reference&case=diesel-product-lca', [{
      id: 'old-product', name: '低硫柴油产品 LCA', application_type: 'system_analysis', description: null,
      context: { case_pack_id: 'petrochemical-refinery-reference', resolved_case_sha256: 'older-product' },
      status: 'active', created_at: '2026-08-31T00:00:00Z', updated_at: '2026-08-31T00:00:00Z',
    }]);
    const search = await screen.findByRole('textbox', { name: '搜索案例' });
    await userEvent.type(search, '低硫柴油');
    expect(screen.queryByRole('row', { name: /炼厂年度物质流分析/ })).not.toBeInTheDocument();
    const product = screen.getByRole('row', { name: /低硫柴油产品 LCA/ });
    expect(within(product).queryByRole('button', { name: '进入分析' })).not.toBeInTheDocument();
    await userEvent.click(within(product).getByRole('button', { name: '使用案例' }));
    expect(await screen.findByRole('button', { name: '创建分析' })).toBeEnabled();
    expect(materialize).not.toHaveBeenCalled();
  });
});
