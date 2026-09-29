import { expect, it, vi } from 'vitest';
import { processDisplayNodes, processName } from './ContributionChart';

vi.mock('echarts-for-react', () => ({ default: () => null }));

it('uses frozen exchange identity for localized foreground names and explicit supply receipts for background', () => {
  const nodes = processDisplayNodes({
    workspaceNodes: [{ id: 'sinter-role', name: 'Sintering strand' }],
    exchanges: [
      { process_id: 'foreground-uuid', exchange_id: 'sinter-role::co2-out' },
      { process_id: 'background-expanded', exchange_id: 'expanded-supply::co2-out' },
    ],
    mfaNodes: [{ process_id: 'foreground-uuid', label: 'Old name' }],
    backgroundReceipts: [{ source_process_uuid: 'background-source', expanded_node_id: 'expanded-supply' }],
    backgroundLabel: 'Linked background supply',
  });
  expect(processName('foreground-uuid', nodes)).toBe('Sintering strand');
  expect(processName('background-source', nodes)).toBe('Linked background supply');
  expect(processName('background-expanded', nodes)).toBe('Linked background supply');
});

it('does not choose a name when one solved process maps to conflicting roles', () => {
  const nodes = processDisplayNodes({
    workspaceNodes: [{ id: 'one', name: 'One' }, { id: 'two', name: 'Two' }],
    exchanges: [
      { process_id: 'same', exchange_id: 'one::output' },
      { process_id: 'same', exchange_id: 'two::output' },
    ],
    mfaNodes: [{ process_id: 'same', label: 'same' }],
    backgroundReceipts: [],
    backgroundLabel: 'Background',
  });
  expect(processName('same', nodes, 'Name unavailable')).toBe('Name unavailable');
});
