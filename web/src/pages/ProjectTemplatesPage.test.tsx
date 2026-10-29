import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import {cleanup, fireEvent, render, screen, waitFor, within} from '@testing-library/react';
import {MemoryRouter, Route, Routes, useLocation} from 'react-router-dom';
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
/** Render the catalog at `entry` with the config workspace replaced by a location probe. */
function mountAt(entry: string, items = [seed]) {
  vi.spyOn(seedProjectsApi, 'catalog').mockResolvedValue({items});
  vi.spyOn(api, 'casepacks').mockResolvedValue({schema_version: 'nebula.casepack-catalog.v1', items: [], issues: []});
  render(<QueryClientProvider client={new QueryClient({defaultOptions: {queries: {retry: false}}})}>
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/templates" element={<ProjectTemplatesPage />} />
        <Route path="/templates/:templateId/config" element={<Location />} />
        <Route path="/applications/:applicationId/calculation-methods" element={<Location />} />
      </Routes>
    </MemoryRouter>
  </QueryClientProvider>);
}
afterEach(() => {cleanup(); vi.restoreAllMocks();});

it('gives each template card exactly two actions and no bare configuration links', async () => {
  mountAt('/templates');
  const heading = await screen.findByText(seed.title, {selector: 'h2'});
  const card = heading.closest('section') as HTMLElement;
  expect(within(card).getAllByRole('button').map(button => button.textContent)).toEqual(['新建项目', '配置模板']);
  expect(screen.queryByRole('link', {name: '核算方法'})).not.toBeInTheDocument();
  expect(screen.queryByRole('link', {name: '定稿模型与规则'})).not.toBeInTheDocument();
  expect(screen.queryByText('定稿新模板')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', {name: '配置模板'}));
  await waitFor(() => expect(screen.getByLabelText('当前位置')).toHaveTextContent('/templates/steel/config?tab=methods'));
});

it('carries an old template deep link into the configuration workspace', async () => {
  mountAt('/templates?source=source-app&model=source-model&revision=source-revision&template=1');
  await waitFor(() => expect(screen.getByLabelText('当前位置')).toHaveTextContent('/templates/steel/config?tab=methods'));
});

it('lets the reader choose when one modelling source has several template versions', async () => {
  mountAt('/templates?source=source-app', [seed, {...seed, id: 'steel-2', version: '1.2.0'}]);
  expect(await screen.findByText('选择模板版本')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('radio', {name: /1\.2\.0/}));
  await waitFor(() => expect(screen.getByLabelText('当前位置')).toHaveTextContent('/templates/steel-2/config?tab=model'));
});

it('reports an unresolvable template link instead of opening some template', async () => {
  mountAt('/templates?source=another-app');
  expect(await screen.findByText('无法确定要配置的模板版本。请返回工艺模板列表重新进入。')).toBeInTheDocument();
  expect(screen.queryByText(seed.title, {selector: 'h2'})).not.toBeInTheDocument();
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
