import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { ScopePanel } from './ScopePanel';

afterEach(cleanup);

it('shows transfers and product quantity without contribution controls, while keeping emissions and purchases editable', () => {
  render(<ScopePanel graph={{nodes: [
    {id: 'p', name: 'Process', inputs: [{id: 'internal', name: 'Internal metal'}, {id: 'power', name: 'Purchased power'}],
      outputs: [{id: 'product', name: 'Final product'}], emissions: [{id: 'co2', name: 'Direct CO2'}]},
  ], edges: [{fromNode: 'supplier', toNode: 'p', targetPortId: 'internal'}]}}
    workspace={undefined} loading={false} error={null} editable rules={[]} dimensions={[]}
    onDimensions={vi.fn()} onEdit={vi.fn()} onRemove={vi.fn()} />);
  for (const label of ['Internal metal', 'Final product']) {
    const row = screen.getByText(label, {exact: false}).closest('tr')!;
    expect(within(row).getByRole('checkbox')).toBeDisabled();
    expect(within(row).queryByRole('combobox', {name: '是否计入'})).not.toBeInTheDocument();
  }
  for (const label of ['Purchased power', 'Direct CO2']) {
    const row = screen.getByText(label, {exact: false}).closest('tr')!;
    expect(within(row).getByRole('checkbox')).not.toBeDisabled();
    expect(within(row).getByRole('combobox', {name: '是否计入'})).toBeInTheDocument();
  }
});
