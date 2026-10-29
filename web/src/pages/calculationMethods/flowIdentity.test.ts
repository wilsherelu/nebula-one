import { expect, it } from 'vitest';
import { modelFlows, overrideFor } from './flowRows';
import type { CalculationMethodRule } from '../../api/types';
import { buildRows } from './labels';
import { processDefaultFor } from './ruleDefaults';

const graph = { nodes: [{ id: 'p1', name: '过程一', inputs: [], outputs: [
  { id: 'co2', name: 'CO2', flowUuid: 'co2-flow', type: 'biosphere', unit: 'kg' },
  { id: 'ch4', name: 'CH4', flowUuid: 'ch4-flow', type: 'biosphere', unit: 'kg' },
] }, { id: 'p2', name: '过程二', inputs: [{ id: 'power', name: 'Electricity', flowUuid: 'power-flow', type: 'technosphere', unit: 'kWh' }], outputs: [] }] };

it('keeps process/port identities and labels separate for gases and purchased energy', () => {
  const flows = modelFlows(graph);
  expect(flows.map(flow => [flow.processId, flow.portId, flow.direction])).toEqual([
    ['p1', 'co2', 'emission'], ['p1', 'ch4', 'emission'], ['p2', 'power', 'input'],
  ]);
});

it('does not classify purchased inputs as onsite emissions through a process default', () => {
  const emission = { process_instance_id: 'p1', direction: 'emission', contribution_target: 'direct', scope: 'scope_1' } as CalculationMethodRule;
  const input = { process_instance_id: 'p1', exchange_id: 'p1::power', direction: 'input', contribution_target: 'upstream' } as CalculationMethodRule;
  expect(processDefaultFor(input, [emission])).toBeUndefined();
  expect(processDefaultFor({ ...emission, exchange_id: 'p1::co2' }, [emission])).toBe(emission);
});

it('adds a selected gas override inheriting its process defaults, without touching the other gas', () => {
  const base: CalculationMethodRule = { process_instance_id: 'p1', exchange_id: null, flow_uuid: null,
    direction: 'emission', boundary_status: 'selected', location_role: 'onsite', scope: 'scope_1',
    classification_basis: 'user', cbam_relevant: true };
  const flow = modelFlows(graph).find(item => item.processId === 'p1' && item.portId === 'ch4')!;
  const override = overrideFor(flow, [base]);
  expect(override).toEqual({ ...base, exchange_id: 'p1::ch4', flow_uuid: 'ch4-flow', contribution_target: 'direct' });
  const row = buildRows([override], undefined, graph)[0];
  expect(row.flowLabel).toBe('CH4');
  expect(row.processName).toBe('过程一');
  expect(row.unit).toBe('kg');
});
