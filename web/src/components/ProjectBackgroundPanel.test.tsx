import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { api, ApiError } from '../api/client';
import { seedProjectsApi } from '../api/seedProjects';
import type { BackgroundProcessPin, ProjectWorkspace } from '../api/types';
import { ProjectBackgroundPanel } from './ProjectBackgroundPanel';

const pin: BackgroundProcessPin = {
  schema_version: 'provider.background-process-pin.v1', consumer_exchange_id: 'steel::power',
  source_namespace: 'tiangong_open_data', process_uuid: '00000000-0000-4000-8000-000000000001',
  version: '01.00.000', expected_process_content_hash: 'a'.repeat(64), expected_process_snapshot_hash: 'b'.repeat(64),
  quantitative_reference_exchange_internal_id: '0', claim_role: 'partial_background_leaf',
};
const workspace: ProjectWorkspace = {
  application_id: 'steel', revision_id: 'r2', content_sha256: 'c'.repeat(64), template_title: 'Steel',
  fields: [{key: 'power', label: '电力', process: '炼钢', value: 50, unit: 'MJ'}],
  demand: [{reference_flow_uuid: 'steel', amount: 1000, unit: 'kg'}], source: '生产台账', saved: true,
  capabilities: [], blocked_capabilities: [], background_options: [], background_note: '',
  background_ports: [{exchange_id: 'steel::power', process: '炼钢', label: '电力', unit: 'MJ',
    flow_uuid: 'power', version: '01.00.000', source_namespace: 'tiangong_open_data', exact_binding_supported: true}],
};
function mount(value = workspace, onSaved = vi.fn(), onReload = vi.fn()) {
  render(<QueryClientProvider client={new QueryClient({defaultOptions: {mutations: {retry: false}}})}>
    <ProjectBackgroundPanel workspace={value} onSaved={onSaved} onContinue={vi.fn()} onReload={onReload} />
  </QueryClientProvider>);
}
async function select() {
  fireEvent.click(screen.getByRole('button', {name: '关联背景过程'}));
  fireEvent.change(await screen.findByRole('textbox', {name: '背景过程 UUID'}), {target: {value: pin.process_uuid}});
  fireEvent.change(screen.getByRole('textbox', {name: '数据版本'}), {target: {value: pin.version}});
  fireEvent.click(screen.getByRole('button', {name: '校验背景数据'}));
}
afterEach(() => {cleanup(); vi.restoreAllMocks();});

it('does not let a late validation response approve a different version', async () => {
  let finish!: (result: {pin: BackgroundProcessPin; name: string}) => void;
  const resolve = vi.spyOn(seedProjectsApi, 'resolveBackground').mockImplementation(() => new Promise(done => {finish = done;}));
  const save = vi.spyOn(api, 'saveProjectInputs');
  mount(); await select();
  await waitFor(() => expect(resolve).toHaveBeenCalledOnce());
  fireEvent.change(screen.getByRole('textbox', {name: '数据版本'}), {target: {value: '02.00.000'}});
  await act(async () => finish({pin, name: 'Old provider'}));
  expect(screen.queryByRole('button', {name: '确认关联并保存'})).not.toBeInTheDocument();
  expect(save).not.toHaveBeenCalled();
});

it('preserves other bindings and saves an exact validated pin against the displayed revision', async () => {
  const other = {...pin, consumer_exchange_id: 'steel::ore'};
  vi.spyOn(seedProjectsApi, 'resolveBackground').mockResolvedValue({pin, name: 'Open electricity leaf'});
  let finish!: (result: ProjectWorkspace) => void;
  const save = vi.spyOn(api, 'saveProjectInputs').mockImplementation(() => new Promise(done => {finish = done;}));
  const onSaved = vi.fn(); mount({...workspace, background_process_pins: [other]}, onSaved); await select();
  fireEvent.click(await screen.findByRole('button', {name: '确认关联并保存'}));
  await waitFor(() => expect(save).toHaveBeenCalledExactlyOnceWith('steel', {
    revision_id: 'r2', expected_content_sha256: workspace.content_sha256, amounts: [1000], demand_mode: undefined,
    values: {power: 50}, source: '生产台账', background_process_pins: [other, pin], project_background_pins: [],
  }, 'zh'));
  expect(screen.getByRole('textbox', {name: '数据版本'})).toBeDisabled();
  expect(screen.getByRole('button', {name: '确认关联并保存'})).toBeDisabled();
  await act(async () => finish({...workspace, revision_id: 'r3', background_process_pins: [other, pin]}));
  await waitFor(() => expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({revision_id: 'r3'})));
});

it('removes only the selected binding through a new saved revision', async () => {
  const other = {...pin, consumer_exchange_id: 'steel::ore'};
  const save = vi.spyOn(api, 'saveProjectInputs').mockResolvedValue({...workspace, revision_id: 'r3'});
  mount({...workspace, background_process_pins: [pin, other]});
  fireEvent.click(screen.getByRole('button', {name: '移除'}));
  await waitFor(() => expect(save).toHaveBeenCalledWith('steel', expect.objectContaining({revision_id: 'r2', background_process_pins: [other]}), 'zh'));
});

it('explains unavailable mapping without sending a guessed provider request', async () => {
  const resolve = vi.spyOn(seedProjectsApi, 'resolveBackground');
  mount({...workspace, background_ports: workspace.background_ports!.map(p => ({...p, exact_binding_supported: false}))});
  fireEvent.click(screen.getByRole('button', {name: '关联背景过程'}));
  expect(await screen.findByText(/不能仅按流名称关联/)).toBeInTheDocument();
  expect(screen.queryByRole('button', {name: '校验背景数据'})).not.toBeInTheDocument();
  expect(resolve).not.toHaveBeenCalled();
});

it('keeps the bound provider identity behind a source disclosure', () => {
  mount({...workspace, background_process_pins: [pin]});
  expect(screen.getByText('已关联背景过程')).toBeInTheDocument();
  expect(screen.getByText(`版本 ${pin.version} · 部分背景清单`)).toBeInTheDocument();
  const ids = screen.getAllByText(new RegExp(pin.process_uuid));
  expect(ids).toHaveLength(1);
  expect(ids[0].closest('details')?.querySelector('summary')?.textContent).toBe('查看来源');
});

it('keeps the exact input flow identity behind the readable upstream label', () => {
  const port = {...workspace.background_ports![0], label: '交流电',
    flow_uuid: '3d76981f-964a-4865-b588-0e067a2a1163', version: '01.01.003'};
  mount({...workspace, background_ports: [port]});
  expect(screen.getByText('交流电')).toBeInTheDocument();
  expect(screen.getByText('尚未关联')).toBeInTheDocument();
  const ids = screen.getAllByText(new RegExp(port.flow_uuid));
  expect(ids).toHaveLength(1);
  const details = ids[0].closest('details');
  expect(details?.querySelector('summary')?.textContent).toBe('查看来源');
  expect(details?.textContent).toContain('投入流 交流电 · tiangong_open_data · 3d76981f-964a-4865-b588-0e067a2a1163 · 版本 01.01.003');
});

it('shows a stale data version inside the open dialog and reloads on request', async () => {
  const onReload = vi.fn();
  vi.spyOn(seedProjectsApi, 'resolveBackground').mockResolvedValue({ pin, name: 'Open electricity leaf' });
  const save = vi.spyOn(api, 'saveProjectInputs').mockRejectedValue(new ApiError('数据版本已改变，请重新加载。', 409, 'PROJECT_INPUT_CONFLICT'));
  mount(workspace, vi.fn(), onReload);
  await select();
  fireEvent.click(await screen.findByRole('button', { name: '确认关联并保存' }));
  await waitFor(() => expect(save).toHaveBeenCalledOnce());
  const refusal = await screen.findByText('数据版本已改变，请重新加载后再保存。');
  expect(refusal.closest('.arco-modal')).not.toBeNull();
  expect(screen.getByRole('textbox', { name: '背景过程 UUID' })).toHaveValue(pin.process_uuid);
  fireEvent.click(screen.getByRole('button', { name: '重新加载' }));
  expect(onReload).toHaveBeenCalledOnce();
});

it('binds a second electricity input to the same provider process without dropping the first', async () => {
  const second = { ...workspace.background_ports![0], exchange_id: 'casting::power' };
  const two = { ...workspace, background_ports: [workspace.background_ports![0], second] };
  const first = { ...workspace.background_ports![0] };
  vi.spyOn(seedProjectsApi, 'resolveBackground').mockImplementation(async (_a, _r, selection) => ({
    pin: { ...pin, consumer_exchange_id: selection.consumer_exchange_id }, name: '同源电力',
  }));
  const save = vi.spyOn(api, 'saveProjectInputs');
  const bound = { ...two, revision_id: 'r3', content_sha256: 'd'.repeat(64), background_process_pins: [{ ...pin, consumer_exchange_id: first.exchange_id }] as BackgroundProcessPin[] };
  save.mockResolvedValue(bound);
  const tree = (value: ProjectWorkspace) => <QueryClientProvider client={new QueryClient({ defaultOptions: { mutations: { retry: false } } })}>
    <ProjectBackgroundPanel workspace={value} onSaved={vi.fn()} onContinue={vi.fn()} onReload={vi.fn()} />
  </QueryClientProvider>;
  const { rerender } = render(tree(two));
  fireEvent.click(screen.getAllByRole('button', { name: '关联背景过程' })[0]);
  fireEvent.change(await screen.findByRole('textbox', { name: '背景过程 UUID' }), { target: { value: pin.process_uuid } });
  fireEvent.change(screen.getByRole('textbox', { name: '数据版本' }), { target: { value: pin.version } });
  fireEvent.click(screen.getByRole('button', { name: '校验背景数据' }));
  fireEvent.click(await screen.findByRole('button', { name: '确认关联并保存' }));
  await waitFor(() => expect(save).toHaveBeenCalledWith('steel', expect.objectContaining({
    revision_id: 'r2', background_process_pins: [{ ...pin, consumer_exchange_id: first.exchange_id }],
  }), 'zh'));
  rerender(tree(bound));
  fireEvent.click(screen.getAllByRole('button', { name: '关联背景过程' })[1]);
  fireEvent.change(await screen.findByRole('textbox', { name: '背景过程 UUID' }), { target: { value: pin.process_uuid } });
  fireEvent.change(screen.getByRole('textbox', { name: '数据版本' }), { target: { value: pin.version } });
  fireEvent.click(screen.getByRole('button', { name: '校验背景数据' }));
  fireEvent.click(await screen.findByRole('button', { name: '确认关联并保存' }));
  await waitFor(() => expect(save).toHaveBeenCalledWith('steel', expect.objectContaining({
    revision_id: 'r3', expected_content_sha256: 'd'.repeat(64),
    background_process_pins: [{ ...pin, consumer_exchange_id: first.exchange_id }, { ...pin, consumer_exchange_id: second.exchange_id }],
  }), 'zh'));
});
