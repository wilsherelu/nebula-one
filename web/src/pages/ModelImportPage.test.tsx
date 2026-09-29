import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/client';
import type { ModelSourcePreview } from '../api/types';
import { ModelImportPage } from './ModelImportPage';

const application = {
  id: 'app-1', name: '石化母案例', application_type: 'system_analysis', description: null,
  context: {}, status: 'active', created_at: '2026-09-02T00:00:00Z', updated_at: '2026-09-02T00:00:00Z',
};

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter><ModelImportPage /></MemoryRouter></QueryClientProvider>);
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('Model import workbench', () => {
  it('previews and explicitly confirms a TIDAS import', async () => {
    vi.spyOn(api, 'applications').mockResolvedValue([application]);
    vi.spyOn(api, 'engine').mockResolvedValue({ provider: 'nebula_lca', base_url: 'http://127.0.0.1:8001', status: 'ready', contracts: { tidas_bundle_import: true } });
    vi.spyOn(api, 'modelSources').mockResolvedValue([]);
    const preview: ModelSourcePreview = {
      schema_version: 'nebula_one.model-source-preview.v1', source_type: 'tidas_bundle', file_name: 'refinery.zip',
      file_sha256: 'a'.repeat(64), status: 'ready', preview_sha256: 'b'.repeat(64), summary: {}, external_dependencies: [], issues: [],
    };
    vi.spyOn(api, 'previewTidasBundle').mockResolvedValue(preview);
    const importCall = vi.spyOn(api, 'importTidasBundle').mockResolvedValue({
      id: 'source-1', application_id: 'app-1', system_model_id: null, name: '炼厂模型', source_type: 'tidas_bundle', provider: 'nebula_lca',
      provider_base_url: 'http://127.0.0.1:8001', status: 'ready_to_attach', file_name: 'refinery.zip', file_sha256: preview.file_sha256,
      upstream_project_id: null, upstream_version: null, graph_sha256: null, import_receipt: {}, candidate_versions: [], external_dependencies: [], issues: [],
      content_sha256: 'c'.repeat(64), created_at: application.created_at, attached_at: null,
    });
    const view = mount();
    await screen.findByText('石化母案例');
    await userEvent.click(screen.getByRole('tab', { name: '导入 TIDAS 包' }));
    await userEvent.type(screen.getByPlaceholderText('导入后在 Nebula One 中显示的名称'), '炼厂模型');
    const file = new File(['bundle'], 'refinery.zip', { type: 'application/zip' });
    const input = view.container.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, file);
    await userEvent.click(screen.getByRole('button', { name: '检查兼容性' }));
    expect(await screen.findByRole('button', { name: '查看检查回执' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('checkbox'));
    await userEvent.click(screen.getByRole('button', { name: '导入 TIDAS 包' }));
    await waitFor(() => expect(importCall).toHaveBeenCalledWith('app-1', file, '炼厂模型', preview.preview_sha256));
  });

  it('disables source mutations when the Nebula LCA API is unavailable', async () => {
    vi.spyOn(api, 'applications').mockResolvedValue([application]);
    vi.spyOn(api, 'engine').mockResolvedValue({ provider: 'nebula_lca', base_url: 'http://127.0.0.1:8001', status: 'unavailable', contracts: {} });
    vi.spyOn(api, 'modelSources').mockResolvedValue([]);
    mount();
    expect(await screen.findByText('Nebula LCA API 未就绪')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '连接并固定版本' })).toBeDisabled();
  });
});
