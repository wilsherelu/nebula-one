import type { CalculationMethodRule, ProjectWorkspace } from '../../api/types';
import { processDefaultFor } from './ruleDefaults';

export interface ModelFlow {
  processId: string; processName: string; portId: string; name: string;
  flowUuid: string | null; direction: CalculationMethodRule['direction']; unit: string;
  /** Whether another modelled process feeds this port; only inputs can be internally fed. */
  internal: boolean;
  description?: string;
}

/** The exchanges the exact model graph declares, per process. Ports come from the graph, never from
 * a flow name, so the same flow in two processes stays two independently editable identities. */
export function modelFlows(graph: Record<string, unknown> | undefined): ModelFlow[] {
  const nodes = Array.isArray(graph?.nodes) ? graph.nodes : [];
  const internal = internalTargets(graph);
  return nodes.flatMap(node => {
    if (!node || typeof node.id !== 'string') return [];
    return ['inputs', 'outputs', 'emissions'].flatMap(group => (Array.isArray(node[group]) ? node[group] : []).map((port: Record<string, unknown>) => {
      const portId = String(port.id);
      return {
        processId: node.id, processName: node.name || node.id, portId, name: String(port.name || port.id),
        flowUuid: typeof port.flowUuid === 'string' ? port.flowUuid : null, unit: String(port.unit || ''),
        direction: port.type === 'biosphere' || port.type === 'elementary' || group === 'emissions' ? (group === 'inputs' ? 'resource' : 'emission') : group === 'inputs' ? 'input' : 'output',
        internal: internal.has(`${node.id}::${portId}`),
        description: typeof port.display_description === 'string' ? port.display_description : undefined,
      };
    }));
  });
}

/** The `process::port` identities another modelled process feeds, read off the graph's own edges. */
function internalTargets(graph: Record<string, unknown> | undefined): Set<string> {
  const edges = Array.isArray(graph?.exchanges) ? graph.exchanges : Array.isArray(graph?.edges) ? graph.edges : [];
  return new Set(edges
    .filter((edge): edge is Record<string, unknown> => !!edge && typeof edge === 'object')
    .filter(edge => typeof edge.toNode === 'string' && edge.targetPortId !== undefined)
    .map(edge => `${edge.toNode}::${edge.targetPortId}`));
}

export interface PortInfo {
  description?: string;
  processId: string;
  processName: string;
  portId: string;
  name: string;
  unit: string;
  flowUuid: string | null;
  direction: CalculationMethodRule['direction'];
  /** Whether another modelled process feeds this port: the engine's contribution domain depends on it. */
  internal: boolean;
}

/** Where a row's classification comes from: an explicit per-flow rule, the process default, or nothing. */
export type RuleSource = 'override' | 'process_default' | 'unset' | 'process_default_rule' | 'port_missing';

export interface ScopeRow {
  /** Stable key: the identity of the rule this row edits, or of the rule it would create. */
  identity: string;
  processId: string;
  processName: string;
  portId: string | null;
  flowLabel: string;
  unit: string;
  direction: CalculationMethodRule['direction'];
  flowUuid: string | null;
  internal: boolean;
  rule: CalculationMethodRule | null;
  /** What the calculation will actually use for this exchange: the row's own rule, else the default. */
  effective: CalculationMethodRule | null;
  source: RuleSource;
  modified: boolean;
  haystack: string;
}

const directionOf = (group: string, flowType: string | undefined): CalculationMethodRule['direction'] =>
  flowType === 'biosphere' || flowType === 'elementary' || group === 'emissions'
    ? (group === 'inputs' ? 'resource' : 'emission')
    : group === 'inputs' ? 'input' : 'output';

/** The exact model version's ports. The graph snapshot wins; the workspace inventory is the fallback
 * for a page that only has field data, so the flow list is never empty just because a graph is absent. */
export function modelPorts(graph: Record<string, unknown> | undefined, workspace: ProjectWorkspace | undefined): PortInfo[] {
  const fromGraph = modelFlows(graph);
  if (fromGraph.length) {
    return fromGraph.map(flow => ({
      processId: flow.processId, processName: flow.processName, portId: flow.portId,
      name: flow.name, unit: flow.unit, flowUuid: flow.flowUuid, direction: flow.direction,
      internal: flow.internal, description: flow.description,
    }));
  }
  const names = new Map((workspace?.process_graph?.nodes ?? []).map(node => [node.id, node.name]));
  // Without a graph the mapped background ports are the only real evidence about an input's domain:
  // a port the workspace lists as background comes from outside the model. No list means no claim,
  // so inputs stay on the purchased-background side rather than being declared foreground.
  const background = workspace?.background_ports ? new Set(workspace.background_ports.map(port => port.exchange_id)) : null;
  return (workspace?.fields ?? [])
    .filter(field => field.process_id && field.port_id)
    .map(field => {
      const exchangeId = `${field.process_id}::${field.port_id}`;
      return {
        processId: field.process_id as string,
        processName: names.get(field.process_id as string) ?? field.process ?? (field.process_id as string),
        portId: field.port_id as string,
        name: field.label,
        unit: field.unit,
        flowUuid: field.flow_uuid ?? null,
        direction: directionOf(field.group ?? 'outputs', field.flow_type),
        internal: background ? !background.has(exchangeId) : false,
      };
    });
}

export const exchangeIdOf = (row: { processId: string; portId: string }) => `${row.processId}::${row.portId}`;

/** Carbon contributions come from elementary exchanges or purchased inputs, not transfers/products. */
export const isContributionRow = (row: { direction: CalculationMethodRule['direction']; internal: boolean }): boolean =>
  row.direction === 'emission' || row.direction === 'resource' || (row.direction === 'input' && !row.internal);

/** The contribution domain the engine will really use for this port: an input another modelled
 * process feeds is a foreground transfer, an input from outside the model is a purchased path. */
export const contributionDomainOf = (port: { direction: CalculationMethodRule['direction']; internal?: boolean }): string =>
  port.direction !== 'input' || port.internal ? 'direct' : 'upstream';

const rowIdentity = (rule: CalculationMethodRule) =>
  `${rule.process_instance_id}::${rule.exchange_id ?? ''}::${rule.flow_uuid ?? ''}::${rule.direction}`;

/** The rule a per-flow edit would create for this port, starting from the process default it inherits. */
export function overrideFor(row: Pick<ScopeRow, 'processId' | 'portId' | 'flowUuid' | 'direction' | 'internal'>, rules: CalculationMethodRule[]): CalculationMethodRule {
  const contributionTarget = contributionDomainOf(row);
  const base = processDefaultFor(
    { process_instance_id: row.processId, direction: row.direction, contribution_target: contributionTarget } as CalculationMethodRule,
    rules,
  );
  return {
    boundary_status: 'pending', location_role: 'other', scope: null, cbam_relevant: false,
    ...base,
    process_instance_id: row.processId,
    exchange_id: row.portId ? exchangeIdOf({ processId: row.processId, portId: row.portId }) : null,
    flow_uuid: row.flowUuid,
    direction: row.direction,
    contribution_target: contributionTarget,
    classification_basis: 'user',
  };
}

/**
 * Join the model's ports with the method's rules for one process.
 *
 * Every port of the process is listed, including the ones nobody set a rule for, so the reader sees
 * the real inventory instead of an empty table. A rule whose exchange no longer exists in this model
 * version is kept as its own row (`port_missing`) rather than dropped: silently hiding it would lose
 * the user's decision after a data-version change.
 */
export function buildScopeRows(processId: string, rules: CalculationMethodRule[], ports: PortInfo[]): ScopeRow[] {
  const processPorts = ports.filter(port => port.processId === processId);
  const processRules = rules.filter(rule => rule.process_instance_id === processId);
  const byExchange = new Map(processRules.filter(rule => rule.exchange_id).map(rule => [rule.exchange_id as string, rule]));
  const rows: ScopeRow[] = processPorts.map(port => {
    const exchangeId = exchangeIdOf(port);
    const rule = byExchange.get(exchangeId) ?? null;
    const prospective = { process_instance_id: processId, exchange_id: exchangeId, flow_uuid: port.flowUuid, direction: port.direction, contribution_target: contributionDomainOf(port) } as CalculationMethodRule;
    const inherited = rule ? null : processDefaultFor(prospective, processRules) ?? null;
    return {
      identity: rule ? rowIdentity(rule) : rowIdentity({ ...prospective, boundary_status: 'pending', location_role: 'other', scope: null, cbam_relevant: false, classification_basis: 'user' } as CalculationMethodRule),
      processId,
      processName: port.processName,
      portId: port.portId,
      flowLabel: port.name,
      unit: port.unit,
      direction: port.direction,
      flowUuid: port.flowUuid,
      internal: port.internal,
      rule,
      effective: rule ?? inherited,
      source: rule ? 'override' : inherited ? 'process_default' : 'unset',
      modified: !!rule,
      haystack: `${port.processName} ${port.name} ${port.flowUuid ?? ''} ${exchangeId}`.toLowerCase(),
    };
  });
  const known = new Set(processPorts.map(exchangeIdOf));
  // Process defaults are edited in their own section, not as flow rows; a rule whose exchange no
  // longer exists in this model version stays visible so the reader can migrate it on purpose.
  rows.push(...processRules.filter(rule => rule.exchange_id && !known.has(rule.exchange_id)).map(rule => {
    const port = processPorts.find(item => exchangeIdOf(item) === rule.exchange_id) ?? null;
    return {
      identity: rowIdentity(rule),
      processId,
      processName: port?.processName ?? rule.process_instance_id,
      portId: port?.portId ?? null,
      flowLabel: (rule.exchange_id as string).split('::')[1] ?? (rule.exchange_id as string),
      unit: port?.unit ?? '',
      direction: rule.direction,
      flowUuid: rule.flow_uuid,
      internal: port?.internal ?? false,
      rule,
      effective: rule,
      source: 'port_missing' as RuleSource,
      modified: true,
      haystack: `${rule.process_instance_id} ${rule.exchange_id ?? ''} ${rule.flow_uuid ?? ''}`.toLowerCase(),
    };
  }));
  return rows;
}

/** The process-default rules of one process, as rows the defaults section can edit and remove. */
export function processDefaultRows(processId: string, rules: CalculationMethodRule[]): ScopeRow[] {
  return rules.filter(rule => rule.process_instance_id === processId && !rule.exchange_id).map(rule => ({
    identity: rowIdentity(rule),
    processId,
    processName: processId,
    portId: null,
    flowLabel: '',
    unit: '',
    direction: rule.direction,
    flowUuid: rule.flow_uuid,
    internal: false,
    rule,
    effective: rule,
    source: 'process_default_rule' as RuleSource,
    modified: true,
    haystack: `${processId} ${rule.direction}`.toLowerCase(),
  }));
}

export interface ProcessEntry { id: string; name: string; portCount: number; modifiedCount: number }

/** The navigation list: every process of the model, with how many of its flows the reader has set. */
export function processEntries(rules: CalculationMethodRule[], ports: PortInfo[]): ProcessEntry[] {
  const entries = new Map<string, ProcessEntry>();
  for (const port of ports) {
    const entry = entries.get(port.processId) ?? { id: port.processId, name: port.processName, portCount: 0, modifiedCount: 0 };
    entry.portCount += 1;
    entries.set(port.processId, entry);
  }
  for (const rule of rules) {
    if (!entries.has(rule.process_instance_id)) {
      entries.set(rule.process_instance_id, { id: rule.process_instance_id, name: rule.process_instance_id, portCount: 0, modifiedCount: 0 });
    }
  }
  for (const rule of rules.filter(item => item.exchange_id)) {
    const entry = entries.get(rule.process_instance_id);
    if (entry) entry.modifiedCount += 1;
  }
  return [...entries.values()];
}
