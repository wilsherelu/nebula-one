import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { BackgroundProcessPin, ProjectWorkspace } from '../api/types';
import { ProjectOverviewPanel } from './ProjectOverviewPanel';

const pin: BackgroundProcessPin = {
  schema_version: 'provider.background-process-pin.v1', consumer_exchange_id: 'steel::power',
  source_namespace: 'tiangong_open_data', process_uuid: '00000000-0000-4000-8000-000000000001',
  version: '01.00.000', expected_process_content_hash: 'a'.repeat(64), expected_process_snapshot_hash: 'b'.repeat(64),
  quantitative_reference_exchange_internal_id: '0', claim_role: 'partial_background_leaf',
};

const workspace: ProjectWorkspace = {
  application_id: 'steel', revision_id: 'r2', content_sha256: 'c'.repeat(64), template_title: '钢铁 BF-BOF 粗钢',
  fields: [
    { key: 'power', label: '电力', process: '炼钢', process_id: 'p-steelmaking', value: 50, unit: 'MJ', reference_product: false },
    { key: 'crude', label: '粗钢', process: '炼钢', process_id: 'p-steelmaking', value: 1, unit: 'kg', reference_product: true },
    { key: 'sinter', label: '烧结矿', process: '烧结', process_id: 'p-sintering', value: 1.6, unit: 'kg' },
  ],
  demand: [{ reference_flow_uuid: 'steel', amount: 1000, unit: 'kg' }],
  source: '生产台账', saved: true, capabilities: [], blocked_capabilities: [],
  background_options: [], background_note: '', inventory_editing: true,
  background_ports: [
    { exchange_id: 'steel::power', process: '炼钢', label: '电力', unit: 'MJ', flow_uuid: 'power', version: '01.00.000', source_namespace: 'tiangong_open_data', exact_binding_supported: true },
    { exchange_id: 'sinter::power', process: '烧结', label: '电力', unit: 'MJ', flow_uuid: 'power', version: '01.00.000', source_namespace: 'tiangong_open_data', exact_binding_supported: true },
  ],
};

function mount(value = workspace, activeProcess?: string) {
  const onStep = vi.fn();
  render(<ProjectOverviewPanel workspace={value} activeProcess={activeProcess} onStep={onStep} />);
  return onStep;
}
afterEach(() => cleanup());

it('reports unsaved template data and offers the data entry step', () => {
  const onStep = mount({ ...workspace, saved: false });
  expect(screen.getByText('当前是模板示例数据，尚未保存')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '填写生产数据' }));
  expect(onStep).toHaveBeenCalledWith('data');
});

it('routes a saved project with unbound inputs to background binding and says the gap is not zero', () => {
  const onStep = mount({ ...workspace, background_process_pins: [pin] });
  expect(screen.getByText(/已关联 1 项 · 待关联 1 项/)).toBeInTheDocument();
  expect(screen.getByText('待关联的投入不含上游排放，不按零计入结果。')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '关联背景数据' }));
  expect(onStep).toHaveBeenCalledWith('background');
});

it('routes a fully bound saved project to the analysis tasks', () => {
  const onStep = mount({ ...workspace, background_process_pins: [pin, { ...pin, consumer_exchange_id: 'sinter::power' }] });
  expect(screen.getByText(/待关联 0 项/)).toBeInTheDocument();
  expect(screen.queryByText('待关联的投入不含上游排放，不按零计入结果。')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '选择分析任务' }));
  expect(onStep).toHaveBeenCalledWith('reports');
});

it('states the reporting basis, scope and source for operators', () => {
  mount(undefined, 'p-sintering');
  expect(screen.getByText('2 个生产过程 · 3 项清单字段')).toBeInTheDocument();
  expect(screen.getByText('炼钢 · 粗钢 1 kg')).toBeInTheDocument();
  expect(screen.getByText('同一期间的投入与产出须按同一基准填报。')).toBeInTheDocument();
  expect(screen.getByText('生产台账')).toBeInTheDocument();
  expect(screen.getAllByRole('button', { name: '填写该过程' })).toHaveLength(2);
  expect(screen.getByText('当前过程').parentElement?.querySelector('dd')?.textContent).toBe('烧结');
});

it('jumps to a single process by its template id', () => {
  const onStep = mount();
  fireEvent.click(screen.getAllByRole('button', { name: '填写该过程' })[1]);
  expect(onStep).toHaveBeenCalledWith('data', 'p-sintering');
});

it('keeps template identifiers inside the version disclosure', () => {
  mount();
  const hash = screen.getByText(workspace.content_sha256);
  expect(hash.closest('details')).not.toBeNull();
  expect(hash.closest('details')?.querySelector('summary')?.textContent).toBe('模板与版本记录');
  expect(screen.getByText('数据版本 r2').closest('details')).not.toBeNull();
});

it('shows an unfilled source as missing instead of empty', () => {
  mount({ ...workspace, source: '   ' });
  expect(screen.getByText('尚未填写')).toBeInTheDocument();
});

const steelPorts = [
  ...workspace.background_ports!,
  ...Array.from({ length: 8 }, (_, index) => ({ exchange_id: `steel::raw-${index}`, process: '炼钢', label: `原料 ${index}`, unit: 'kg', flow_uuid: `raw-${index}`, version: '1.1.0', source_namespace: 'nebula.standard-lca-seed', exact_binding_supported: false })),
];

it('separates inputs the template cannot yet bind from those awaiting binding', () => {
  const onStep = mount({ ...workspace, background_ports: steelPorts });
  expect(screen.getByText(/已关联 0 项 · 待关联 2 项 · 模板尚缺映射 8 项/)).toBeInTheDocument();
  expect(screen.getByText('缺映射的投入需在 Nebula LCA 中完成上游流映射并发布新模板，不能按流名称替代。')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '关联背景数据' }));
  expect(onStep).toHaveBeenCalledWith('background');
});

it('stops offering background binding once nothing bindable is left', () => {
  const onStep = mount({ ...workspace, background_ports: steelPorts, background_process_pins: [pin, { ...pin, consumer_exchange_id: 'sinter::power' }] });
  expect(screen.getByText(/已关联 2 项 · 待关联 0 项 · 模板尚缺映射 8 项/)).toBeInTheDocument();
  expect(screen.queryByText('待关联的投入不含上游排放，不按零计入结果。')).not.toBeInTheDocument();
  expect(screen.getByText('缺映射的投入需在 Nebula LCA 中完成上游流映射并发布新模板，不能按流名称替代。')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '选择分析任务' }));
  expect(onStep).toHaveBeenCalledWith('reports');
});
