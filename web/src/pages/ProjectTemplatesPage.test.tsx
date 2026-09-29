import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {MemoryRouter, useLocation} from 'react-router-dom';
import {afterEach, expect, it, vi} from 'vitest';
import {api} from '../api/client';
import {seedProjectsApi} from '../api/seedProjects';
import {ProjectCreateDialog, ProjectTemplatesPage} from './ProjectTemplatesPage';

const seed = {id: 'steel', title: '高炉—转炉钢铁', version: '1.1.0', template_sha256: 'a'.repeat(64),
  seed_id: 'steel-template', installed_application_id: 'installed-app', source_application_id: 'source-app', source_model_id: 'source-model', source_revision_id: 'source-revision',
  process_count: 5, field_count: 28, capabilities: ['mfa.solved.v1']};
function Location() {const location = useLocation(); return <output aria-label="当前位置">{location.pathname}{location.search}</output>;}
function mount() {
  vi.spyOn(seedProjectsApi, 'catalog').mockResolvedValue({items: [seed]});
  render(<QueryClientProvider client={new QueryClient({defaultOptions: {queries: {retry: false}}})}>
    <MemoryRouter><ProjectCreateDialog onClose={vi.fn()} /><Location /></MemoryRouter>
  </QueryClientProvider>);
}
afterEach(() => {cleanup(); vi.restoreAllMocks();});

it('opens the exact installed template model for editing', async () => {
  vi.spyOn(seedProjectsApi, 'catalog').mockResolvedValue({items: [seed]});
  vi.spyOn(api, 'casepacks').mockResolvedValue({schema_version: 'nebula.casepack-catalog.v1', items: [], issues: []});
  const open = vi.spyOn(window, 'open').mockReturnValue(null);
  render(<QueryClientProvider client={new QueryClient({defaultOptions: {queries: {retry: false}}})}>
    <MemoryRouter><ProjectTemplatesPage /></MemoryRouter>
  </QueryClientProvider>);
  fireEvent.click(await screen.findByRole('button', {name: '修改模板'}));
  expect(open).toHaveBeenCalledWith('/modeling?application=source-app&model=source-model&launch=1&revision=source-revision&lang=zh', '_blank', 'noopener,noreferrer');
});

it('creates an installed template even when the separate example catalog fails', async () => {
  vi.spyOn(api, 'casepacks').mockRejectedValue(new Error('Example catalog offline'));
  const create = vi.spyOn(seedProjectsApi, 'create').mockResolvedValue({application_id: 'new-steel', system_model_id: 'm1', revision_id: 'r1'});
  mount();
  fireEvent.click(await screen.findByText(seed.title, {selector: 'strong'}));
  fireEvent.change(screen.getByRole('textbox', {name: '用产品、工厂或报告期间区分项目'}), {target: {value: '钢厂年度台账'}});
  fireEvent.click(screen.getByRole('button', {name: '创建项目，填写数据'}));
  await waitFor(() => expect(create).toHaveBeenCalledWith('steel', expect.objectContaining({name: '钢厂年度台账', expected_template_sha256: seed.template_sha256})));
  await waitFor(() => expect(screen.getByLabelText('当前位置')).toHaveTextContent('/applications/new-steel/workbench?step=data&model=m1&revision=r1'));
});

it('keeps the selected template and project name while searching, with an honest empty state', async () => {
  vi.spyOn(api, 'casepacks').mockResolvedValue({schema_version: 'nebula.casepack-catalog.v1', items: [], issues: []});
  mount();
  fireEvent.click(await screen.findByText(seed.title, {selector: 'strong'}));
  const name = screen.getByRole('textbox', {name: '用产品、工厂或报告期间区分项目'});
  fireEvent.change(name, {target: {value: '我的钢铁项目'}});
  fireEvent.change(screen.getByRole('textbox', {name: '搜索工艺模板'}), {target: {value: '不存在的工艺'}});
  expect(await screen.findByText('没有匹配的模板，请换个关键词。')).toBeInTheDocument();
  expect(screen.getByText(`已选：${seed.title}`)).toBeInTheDocument();
  expect(name).toHaveValue('我的钢铁项目');
  fireEvent.change(screen.getByRole('textbox', {name: '搜索工艺模板'}), {target: {value: '钢铁'}});
  expect(screen.getByText(seed.title, {selector: 'strong'})).toBeInTheDocument();
  expect(screen.queryByText('尚未配置工艺模板')).not.toBeInTheDocument();
});
