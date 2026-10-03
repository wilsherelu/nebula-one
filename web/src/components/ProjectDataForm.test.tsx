import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '../api/client';
import { seedProjectsApi } from '../api/seedProjects';
import type { ProjectWorkspace } from '../api/types';
import { ProjectDataForm } from './ProjectDataForm';
import { MemoryRouter } from 'react-router-dom';

const workspace: ProjectWorkspace = {
  application_id: 'project-a', revision_id: 'revision-1', content_sha256: 'a'.repeat(64), template_title: 'Template',
  fields: [{ key: 'feed', label: '原料', process: '生产', unit: 'kg', value: 1.1 }],
  demand: [{ reference_flow_uuid: 'product', amount: 1000, unit: 'kg' }], source: '模板示例值', saved: false,
  capabilities: ['mfa.solved.v1'], blocked_capabilities: [], background_options: [], background_note: '',
};
function mount(value = workspace, onSaved = vi.fn(), onReload = vi.fn()) {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { mutations: { retry: false } } })}><MemoryRouter><ProjectDataForm workspace={value} onSaved={onSaved} onReload={onReload} /></MemoryRouter></QueryClientProvider>);
}
afterEach(() => { cleanup(); vi.restoreAllMocks(); localStorage.clear(); });

describe('Project data editing', () => {
  it('keeps edits in different processes and sends their shared connection as one value', async () => {
    const inventory = {...workspace, inventory_editing: true, fields: [
      {key:'shared', process_id:'a',port_id:'out',process:'烧结',label:'烧结矿',unit:'kg',value:10,group:'outputs',reference_product:true},
      {key:'shared', process_id:'b',port_id:'in',process:'高炉',label:'烧结矿',unit:'kg',value:10,group:'inputs',linked:true},
      {key:'fuel', process_id:'b',port_id:'fuel',process:'高炉',label:'焦炭',unit:'kg',value:4,group:'inputs'},
    ]};
    const request = vi.spyOn(api,'saveProjectInputs').mockResolvedValue({...inventory,saved:true});
    mount(inventory);
    fireEvent.change(screen.getByRole('spinbutton',{name:'烧结 / 烧结矿'}),{target:{value:'12'}});
    await userEvent.click(screen.getByRole('combobox',{name:'选择生产过程'}));
    fireEvent.click(screen.getByRole('option',{name:'高炉'}));
    expect(screen.getByRole('spinbutton',{name:'高炉 / 烧结矿'})).toHaveValue('12');
    fireEvent.change(screen.getByRole('spinbutton',{name:'高炉 / 焦炭'}),{target:{value:'5'}});
    await userEvent.click(screen.getByRole('button',{name:'保存数据'}));
    await waitFor(() => expect(request).toHaveBeenCalledWith('project-a',expect.objectContaining({values:{shared:12,fuel:5}}),'zh'));
  });
  it('uses the final product output as the batch solve demand', async () => {
    const inventory = {...workspace, inventory_editing: true, fields: [
      {key:'steel', process_id:'cast', port_id:'product', process:'连铸', label:'粗钢', unit:'kg', flow_uuid:'product', value:1000, group:'outputs', reference_product:true},
      {key:'ore', process_id:'cast', port_id:'ore', process:'连铸', label:'原料', unit:'kg', value:1490, group:'inputs'},
    ]};
    const request = vi.spyOn(api,'saveProjectInputs').mockResolvedValue({...inventory,saved:true});
    mount(inventory);
    expect(screen.queryByRole('spinbutton',{name:'核算规模 1'})).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole('spinbutton',{name:'连铸 / 粗钢'}),{target:{value:'2000'}});
    await userEvent.click(screen.getByRole('button',{name:'保存数据'}));
    await waitFor(() => expect(request).toHaveBeenCalledWith('project-a',expect.objectContaining({
      amounts:[2000], demand_mode:'reference_output', values:{steel:2000,ore:1490},
    }), 'zh'));
  });
  it('clicking a process on the graph shows that process\'s rows and carries the shared value', async () => {
    const inventory = {...workspace, inventory_editing: true,
      process_graph: { nodes: [{ id: 'a', name: '烧结' }, { id: 'b', name: '高炉' }], edges: [{ source: 'a', target: 'b', label: '烧结矿' }] },
      fields: [
        {key:'shared', process_id:'a',port_id:'out',process:'烧结',label:'烧结矿',unit:'kg',value:10,group:'outputs',reference_product:true},
        {key:'shared', process_id:'b',port_id:'in',process:'高炉',label:'烧结矿',unit:'kg',value:10,group:'inputs',linked:true},
        {key:'fuel', process_id:'b',port_id:'fuel',process:'高炉',label:'焦炭',unit:'kg',value:4,group:'inputs'},
      ]};
    mount(inventory);
    // Both real processes are drawn; nothing is hard-coded and the edge is the graph's own exchange.
    expect(screen.getByRole('group', { name: '工艺图，点击过程填写数据' })).toBeInTheDocument();
    // Editing the first process, then clicking the second node on the graph switches the form to it.
    fireEvent.change(screen.getByRole('spinbutton', { name: '烧结 / 烧结矿' }), { target: { value: '12' } });
    fireEvent.click(screen.getByRole('button', { name: '高炉' }));
    expect(screen.getByRole('spinbutton', { name: '高炉 / 烧结矿' })).toHaveValue('12');
    expect(screen.getByRole('spinbutton', { name: '高炉 / 焦炭' })).toBeInTheDocument();
  });
  it('saves edited quantities against the exact parent and keeps unit/structure out of the request', async () => {
    const saved = { ...workspace, revision_id: 'revision-2', saved: true };
    const request = vi.spyOn(api, 'saveProjectInputs').mockResolvedValue(saved);
    const onSaved = vi.fn(); mount(workspace, onSaved);
    fireEvent.change(screen.getByRole('spinbutton', { name: '核算规模 1' }), { target: { value: '2000' } });
    fireEvent.change(screen.getByRole('spinbutton', { name: '原料' }), { target: { value: '1.05' } });
    await userEvent.click(screen.getByRole('button', { name: '保存数据' }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(saved, 'revision-1'));
    // The source field was removed from the form, so the version's own provenance is carried through unchanged.
    expect(request).toHaveBeenCalledExactlyOnceWith('project-a', { revision_id: 'revision-1', expected_content_sha256: 'a'.repeat(64), amounts: [2000], values: { feed: 1.05 }, source: '模板示例值' }, 'zh');
    expect(localStorage.getItem('nebula-one:project:project-a:revision-1')).toBeNull();
  });
  it('keeps a draft scoped to its own project and revision, and refuses an empty output', () => {
    mount();
    fireEvent.change(screen.getByRole('spinbutton', { name: '核算规模 1' }), { target: { value: '' } });
    expect(screen.getByRole('button', { name: '保存数据' })).toBeDisabled();
    expect(screen.getByRole('status')).toHaveTextContent('保存前还需：目标产品产出须为大于 0 的数字。');
    // The untyped draft belongs to this revision only; the next version starts from its own saved values.
    expect(localStorage.getItem('nebula-one:project:project-a:revision-1')).toContain('"amounts"');
    cleanup(); mount({ ...workspace, revision_id: 'revision-2' });
    expect(screen.getByRole('spinbutton', { name: '核算规模 1' })).toHaveValue('1000');
  });
  it('offers a reload on a stale data version and keeps what was typed', async () => {
    const onReload = vi.fn();
    vi.spyOn(api, 'saveProjectInputs').mockRejectedValue(new ApiError('数据版本已改变，请重新加载。', 409, 'PROJECT_INPUT_CONFLICT'));
    mount(workspace, vi.fn(), onReload);
    fireEvent.change(screen.getByRole('spinbutton', { name: '原料' }), { target: { value: '2.5' } });
    await userEvent.click(screen.getByRole('button', { name: '保存数据' }));
    expect(await screen.findByText('数据版本已改变，请重新加载后再保存。')).toBeInTheDocument();
    expect(screen.getByRole('spinbutton', { name: '原料' })).toHaveValue('2.5');
    fireEvent.click(screen.getByRole('button', { name: '重新加载' }));
    expect(onReload).toHaveBeenCalledOnce();
  });
  it('does not offer a reload for a refusal that a reload cannot fix', async () => {
    vi.spyOn(api, 'saveProjectInputs').mockRejectedValue(new ApiError('参考产品数量必须大于零。', 422, 'PROJECT_REFERENCE_AMOUNT_INVALID'));
    mount();
    await userEvent.click(screen.getByRole('button', { name: '保存数据' }));
    expect(await screen.findByText('参考产品的数量必须大于 0。')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '重新加载' })).not.toBeInTheDocument();
  });
  it('opens an in-place background dialog from the process input row and saves the association against that exchange', async () => {
    const pin = { schema_version: 'provider.background-process-pin.v1', consumer_exchange_id: 'b::electricity', source_namespace: 'tiangong_open_data',
      process_uuid: 'e4a1c2b3-0000-4000-8000-000000000001', version: '01.00.000', expected_process_content_hash: 'c'.repeat(64),
      expected_process_snapshot_hash: 'd'.repeat(64), quantitative_reference_exchange_internal_id: 'q1', claim_role: 'partial_background_leaf' } as const;
    const inventory = {...workspace, inventory_editing: true,
      process_graph: { nodes: [{ id: 'a', name: '烧结' }, { id: 'b', name: '高炉' }], edges: [] },
      fields: [{key:'elec', process_id:'b', port_id:'electricity', process:'高炉', label:'电力', unit:'kWh', value:100, group:'inputs', flow_type:'technosphere'}],
      background_ports: [{exchange_id:'b::electricity', process:'高炉', label:'电力', unit:'kWh', flow_uuid:'f1', version:'01.00.000', source_namespace:'tiangong_open_data', exact_binding_supported:true}],
    };
    vi.spyOn(seedProjectsApi, 'resolveBackground').mockResolvedValue({ pin, name: '区域电力', claim_role: 'partial_background_leaf' } as never);
    const request = vi.spyOn(api, 'saveProjectInputs').mockResolvedValue({...inventory, saved: true, background_process_pins: [pin]});
    mount(inventory);
    fireEvent.click(screen.getByRole('button', { name: '高炉' }));
    await userEvent.click(screen.getByRole('button', { name: '选择背景数据' }));
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('combobox', {name: '背景来源'}));
    // jsdom has no layout for Arco's virtual option list; exercise its selection event.
    fireEvent.click(screen.getByText('精确引用', {exact:true}));
    // The one in-place picker stays locked to the same exchange through source selection.
    fireEvent.change(screen.getByLabelText('背景过程 UUID'), { target: { value: pin.process_uuid } });
    fireEvent.change(screen.getByLabelText('数据版本'), { target: { value: pin.version } });
    await userEvent.click(screen.getByRole('button', { name: '校验背景数据' }));
    await userEvent.click(await screen.findByRole('button', { name: '确认关联' }));
    await waitFor(() => expect(request).toHaveBeenCalledWith('project-a', expect.objectContaining({
      background_process_pins: [expect.objectContaining({ consumer_exchange_id: 'b::electricity', process_uuid: pin.process_uuid })],
    }), 'zh'));
  });
  it('lets an existing association be removed from the row dialog and persists without it', async () => {
    const pin = { schema_version: 'provider.background-process-pin.v1', consumer_exchange_id: 'b::electricity', source_namespace: 'tiangong_open_data',
      process_uuid: 'e4a1c2b3-0000-4000-8000-000000000001', version: '01.00.000', expected_process_content_hash: 'c'.repeat(64),
      expected_process_snapshot_hash: 'd'.repeat(64), quantitative_reference_exchange_internal_id: 'q1', claim_role: 'partial_background_leaf' } as const;
    const inventory = {...workspace, inventory_editing: true, saved: true,
      process_graph: { nodes: [{ id: 'b', name: '高炉' }], edges: [] },
      fields: [{key:'elec', process_id:'b', port_id:'electricity', process:'高炉', label:'电力', unit:'kWh', value:100, group:'inputs', flow_type:'technosphere'}],
      background_ports: [{exchange_id:'b::electricity', process:'高炉', label:'电力', unit:'kWh', flow_uuid:'f1', version:'01.00.000', source_namespace:'tiangong_open_data', exact_binding_supported:true}],
      background_process_pins: [pin],
    };
    const request = vi.spyOn(api, 'saveProjectInputs').mockResolvedValue({...inventory, background_process_pins: []});
    mount(inventory);
    await userEvent.click(screen.getByRole('button', { name: '更换背景数据' }));
    await userEvent.click(await screen.findByRole('button', { name: '移除此背景关联' }));
    await waitFor(() => expect(request).toHaveBeenCalledWith('project-a', expect.objectContaining({ background_process_pins: [] }), 'zh'));
  });
});
