import { describe, expect, it } from 'vitest';
import type { CalculationMethodRule, ProjectWorkspace } from '../../api/types';
import { buildScopeRows, exchangeIdOf, isContributionRow, modelPorts, overrideFor, processDefaultRows, processEntries } from './flowRows';

it('only edits elementary contributions and external purchases, never intermediate transfers or product quantity', () => {
  expect(isContributionRow({direction: 'emission', internal: false})).toBe(true);
  expect(isContributionRow({direction: 'resource', internal: false})).toBe(true);
  expect(isContributionRow({direction: 'input', internal: false})).toBe(true);
  expect(isContributionRow({direction: 'input', internal: true})).toBe(false);
  expect(isContributionRow({direction: 'output', internal: false})).toBe(false);
});

const rule = (patch: Partial<CalculationMethodRule>): CalculationMethodRule => ({
  process_instance_id: 'p1', exchange_id: null, flow_uuid: null, direction: 'emission',
  boundary_status: 'pending', location_role: 'other', scope: null, cbam_relevant: false,
  classification_basis: 'user', ...patch,
});

const graph = {
  nodes: [
    { id: 'p1', name: '炼钢', inputs: [{ id: 'e1', name: '电力', flowUuid: 'flow-power', unit: 'kWh' }],
      outputs: [], emissions: [{ id: 'e9', name: '二氧化碳', flowUuid: 'flow-co2', unit: 'kg' }, { id: 'e10', name: '甲烷', flowUuid: 'flow-co2', unit: 'kg' }] },
    { id: 'p2', name: '烧结', inputs: [], outputs: [], emissions: [{ id: 'e10', name: '甲烷', flowUuid: 'flow-co2', unit: 'kg' }] },
  ],
  edges: [],
};

/** The same model with one input another process feeds: the engine's domain for it is foreground. */
const linkedGraph = {
  nodes: [
    { id: 'p1', name: '炼钢', inputs: [{ id: 'e1', name: '电力', flowUuid: 'flow-power', unit: 'kWh' },
      { id: 'e2', name: '铁水', flowUuid: 'flow-metal', unit: 'kg' }], outputs: [], emissions: [] },
    { id: 'p2', name: '烧结', inputs: [], outputs: [{ id: 'e3', name: '铁水', flowUuid: 'flow-metal', unit: 'kg' }], emissions: [] },
  ],
  exchanges: [{ fromNode: 'p2', sourcePortId: 'e3', toNode: 'p1', targetPortId: 'e2' }],
};

const workspace = {
  application_id: 'app', revision_id: 'r', content_sha256: 'c'.repeat(64), template_title: '钢铁',
  fields: [
    { key: 'power', label: '电力', process: '炼钢', process_id: 'p1', port_id: 'e1', group: 'inputs', flow_type: 'technosphere', value: 1, unit: 'kWh' },
    { key: 'unmapped', label: '无端口', process: '炼钢', value: 1, unit: 'kg' },
  ],
  demand: [], source: '', saved: true, capabilities: [], blocked_capabilities: [], background_options: [], background_note: '',
  process_graph: { nodes: [{ id: 'p1', name: '炼钢' }], edges: [] },
} as unknown as ProjectWorkspace;

describe('modelPorts', () => {
  it('reads the exact model graph when one is present', () => {
    const ports = modelPorts(graph, workspace);
    expect(ports.map(port => exchangeIdOf(port))).toEqual(['p1::e1', 'p1::e9', 'p1::e10', 'p2::e10']);
    expect(ports[0]).toMatchObject({ processName: '炼钢', name: '电力', unit: 'kWh', flowUuid: 'flow-power', direction: 'input' });
    expect(ports[1].direction).toBe('emission');
  });

  it('falls back to the workspace inventory and skips fields with no port identity', () => {
    const ports = modelPorts(undefined, workspace);
    expect(ports).toEqual([{ processId: 'p1', processName: '炼钢', portId: 'e1', name: '电力', unit: 'kWh', flowUuid: null, direction: 'input', internal: false }]);
  });

  it('reads an input off the graph edges as internally fed, never off its flow name', () => {
    const ports = modelPorts(linkedGraph, undefined);
    expect(ports.map(port => [exchangeIdOf(port), port.internal])).toEqual([
      ['p1::e1', false], ['p1::e2', true], ['p2::e3', false],
    ]);
  });

  it('keeps a background-supplied input as a contribution when the same flow reaches the process internally at another port', () => {
    // One flow, two provider paths into the same process: an internal transfer at e1 and an
    // external purchase at e2. Excluding e1 (its emissions ride the producing node's edge) must
    // never discard e2's real background contribution -- so the split is per consumer port, not per flow.
    const sharedFlow = {
      nodes: [
        { id: 'p1', name: '炼钢', inputs: [{ id: 'e1', name: '电力', flowUuid: 'flow-power', unit: 'kWh' },
          { id: 'e2', name: '电力(外购)', flowUuid: 'flow-power', unit: 'kWh' }], outputs: [], emissions: [] },
        { id: 'p2', name: '发电', inputs: [], outputs: [{ id: 'e3', name: '电力', flowUuid: 'flow-power', unit: 'kWh' }], emissions: [{ id: 'e4', name: '二氧化碳', flowUuid: 'flow-co2', unit: 'kg' }] },
      ],
      exchanges: [{ fromNode: 'p2', sourcePortId: 'e3', toNode: 'p1', targetPortId: 'e1' }],
    };
    const ports = modelPorts(sharedFlow, undefined);
    const byExchange = new Map(ports.map(port => [exchangeIdOf(port), port]));
    expect(byExchange.get('p1::e1')!.internal).toBe(true);   // internally fed -> not a contribution
    expect(byExchange.get('p1::e2')!.internal).toBe(false);  // external purchase -> a contribution
    expect(isContributionRow(byExchange.get('p1::e1')!)).toBe(false);
    expect(isContributionRow(byExchange.get('p1::e2')!)).toBe(true);
    const rows = buildScopeRows('p1', [], ports);
    expect(rows.map(row => row.flowLabel)).toEqual(['电力', '电力(外购)']);
    // two independently editable identities, so the external one is never hidden by the internal one
    expect(rows[0].identity).toContain('p1::e1');
    expect(rows[1].identity).toContain('p1::e2');
  });

  it('treats an input the workspace lists as a background port as coming from outside the model', () => {
    const mapped = { ...workspace, background_ports: [{ exchange_id: 'p1::e1' }] } as unknown as ProjectWorkspace;
    expect(modelPorts(undefined, mapped).map(port => port.internal)).toEqual([false]);
    const unmapped = { ...workspace, background_ports: [] } as unknown as ProjectWorkspace;
    expect(modelPorts(undefined, unmapped).map(port => port.internal)).toEqual([true]);
  });
});

describe('buildScopeRows', () => {
  const ports = modelPorts(graph, undefined);

  it('lists every port of the process, including the ones no rule covers', () => {
    const rows = buildScopeRows('p1', [rule({ exchange_id: 'p1::e9', flow_uuid: 'flow-co2', boundary_status: 'selected' })], ports);
    expect(rows.map(row => [row.flowLabel, row.source])).toEqual([
      ['电力', 'unset'], ['二氧化碳', 'override'], ['甲烷', 'unset'],
    ]);
    expect(rows.every(row => row.processId === 'p1')).toBe(true);
  });

  it('keeps the same flow in two processes as two independently editable identities', () => {
    const methaneInP2 = buildScopeRows('p2', [], ports);
    expect(methaneInP2).toHaveLength(1);
    expect(methaneInP2[0].identity).not.toBe(buildScopeRows('p1', [], ports)[2].identity);
    expect(methaneInP2[0].identity).toContain('p2::e10');
  });

  it('shows an unset flow inheriting the process default of its own direction only', () => {
    const defaultRule = rule({ direction: 'emission', boundary_status: 'selected', scope: 'scope_1' });
    const rows = buildScopeRows('p1', [defaultRule], ports);
    const [power, co2, methane] = rows;
    expect([power.source, co2.source, methane.source]).toEqual(['unset', 'process_default', 'process_default']);
    expect(power.effective).toBeNull();
    expect(methane.effective).toMatchObject({ boundary_status: 'selected', scope: 'scope_1' });
    expect(rows.every(row => row.identity.includes('::e'))).toBe(true);
  });

  it('does not turn a process default into a flow row, and keeps a rule whose port is gone', () => {
    const rules = [rule({ direction: 'input', contribution_target: 'upstream' }), rule({ exchange_id: 'p1::old', flow_uuid: 'gone' })];
    const rows = buildScopeRows('p1', rules, ports);
    expect(rows.map(row => row.source)).toEqual(['process_default', 'unset', 'unset', 'port_missing']);
    expect(processDefaultRows('p1', rules).map(row => [row.direction, row.source])).toEqual([['input', 'process_default_rule']]);
  });

  it('does not let a default that states no domain inherit, because the engine ignores it too', () => {
    const rows = buildScopeRows('p1', [rule({ direction: 'input' })], ports);
    expect(rows[0].source).toBe('unset');
    expect(rows[0].effective).toBeNull();
  });
});

describe('overrideFor', () => {
  it('starts a per-flow rule from the default it inherited and pins the exact exchange identity', () => {
    const defaultRule = rule({ direction: 'emission', boundary_status: 'selected', location_role: 'onsite', scope: 'scope_1', cbam_relevant: true });
    const created = overrideFor({ processId: 'p1', portId: 'e10', flowUuid: 'flow-co2', direction: 'emission', internal: false }, [defaultRule]);
    expect(created).toEqual(rule({
      exchange_id: 'p1::e10', flow_uuid: 'flow-co2', direction: 'emission', boundary_status: 'selected',
      location_role: 'onsite', scope: 'scope_1', cbam_relevant: true, contribution_target: 'direct',
    }));
  });

  it('derives the contribution domain from the model edges, never from a flow name', () => {
    const purchased = overrideFor({ processId: 'p1', portId: 'e1', flowUuid: 'flow-power', direction: 'input', internal: false }, []);
    expect(purchased.contribution_target).toBe('upstream');
    expect(purchased.boundary_status).toBe('pending');
    const internal = overrideFor({ processId: 'p1', portId: 'e2', flowUuid: 'flow-metal', direction: 'input', internal: true }, []);
    expect(internal.contribution_target).toBe('direct');
  });

  it('inherits only the process default declared for the same direction and domain', () => {
    const upstreamDefault = rule({ direction: 'input', contribution_target: 'upstream', boundary_status: 'selected', scope: 'scope_2' });
    const rows = buildScopeRows('p1', [upstreamDefault], modelPorts(linkedGraph, undefined));
    const [power, metal] = rows;
    expect([power.source, metal.source]).toEqual(['process_default', 'unset']);
    expect(power.effective).toMatchObject({ scope: 'scope_2' });
    expect(metal.effective).toBeNull();
  });

  it('ignores a default declared for another direction', () => {
    const created = overrideFor({ processId: 'p1', portId: 'e10', flowUuid: 'flow-co2', direction: 'emission', internal: false }, [rule({ direction: 'input', boundary_status: 'excluded' })]);
    expect(created.boundary_status).toBe('pending');
  });
});

describe('processEntries', () => {
  it('counts each process ports and how many flows the reader has set', () => {
    const entries = processEntries([rule({ exchange_id: 'p1::e9' }), rule({ process_instance_id: 'p3' })], modelPorts(graph, undefined));
    expect(entries).toEqual([
      { id: 'p1', name: '炼钢', portCount: 3, modifiedCount: 1 },
      { id: 'p2', name: '烧结', portCount: 1, modifiedCount: 0 },
      { id: 'p3', name: 'p3', portCount: 0, modifiedCount: 0 },
    ]);
  });
});
