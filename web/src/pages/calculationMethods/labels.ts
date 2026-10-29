import type { CalculationMethodRule, ProjectWorkspace } from '../../api/types';
import { useI18n } from '../../i18n';
import { modelFlows } from './flowRows';

/** A rule joined with the readable process/flow identity the exact model version carries.
 * Ids stay the save keys; labels are display only and never substituted for identity. */
export interface RuleRow extends CalculationMethodRule {
  index: number;
  processName: string;
  flowLabel: string;
  unit: string;
  haystack: string;
}

export const ruleIdentity = (rule: CalculationMethodRule) =>
  `${rule.process_instance_id}::${rule.exchange_id ?? ''}::${rule.flow_uuid ?? ''}::${rule.direction}`;

export const PURPOSES = ['cbam', 'organization', 'custom'];
export const DIRECTIONS = ['input', 'output', 'emission', 'resource'];
export const BOUNDARIES = ['selected', 'excluded', 'pending'];
export const LOCATIONS = ['onsite', 'purchased_energy', 'upstream_supply', 'other'];
export const SCOPES: Array<'scope_1' | 'scope_2' | 'scope_3'> = ['scope_1', 'scope_2', 'scope_3'];
/** The GHG location role each Scope is declared against. Mirrors the backend `_SCOPE_LOCATION`
 * guard: it is used only to flag a row whose chosen Scope contradicts its evidence-based location,
 * never to fabricate a location from the Scope choice (§2.2 / plan §115). */
export const SCOPE_LOCATION: Record<string, 'onsite' | 'purchased_energy' | 'upstream_supply'> = {
  scope_1: 'onsite', scope_2: 'purchased_energy', scope_3: 'upstream_supply',
};
/** The engine's two contribution domains; a process default only applies inside the one it names. */
export const DOMAINS = ['direct', 'upstream'];

type Translate = ReturnType<typeof useI18n>['t'];

export const purposeText = (t: Translate, purpose: string) => PURPOSES.includes(purpose) ? t(`cm.purpose.${purpose}` as never) : purpose;
export const statusText = (t: Translate, status: string) => status === 'ready' ? t('cm.status.ready') : status === 'retired' ? t('cm.status.retired') : t('cm.status.draft');
export const directionText = (t: Translate, direction: string) => DIRECTIONS.includes(direction) ? t(`cm.dir.${direction}` as never) : direction;
export const boundaryText = (t: Translate, status: string) => BOUNDARIES.includes(status) ? t(`cm.boundary.${status}` as never) : status;
export const locationText = (t: Translate, role: string) => ['onsite', 'purchased_energy', 'upstream_supply', 'other'].includes(role) ? t(`cm.location.${role}` as never) : role;
export const scopeText = (t: Translate, scope: string | null) => scope ? t(`cm.scope.${scope}` as never) : t('cm.scope.none');
export const domainText = (t: Translate, domain: string | undefined) => DOMAINS.includes(domain ?? '') ? t(`cm.domain.${domain}` as never) : t('cm.domain.direct');

/** Built-in package kinds are engineering enums; the list shows the accounting purpose they serve. */
const PACKAGE_KIND_KEYS = [
  'product_carbon_footprint', 'period_carbon_management', 'spatial_distribution', 'accounting',
  'cbam_trial', 'cbam_complex_trial', 'cbam_partial_review', 'cbam_electricity_factor',
  'organization_ghg_inventory', 'organization_ghg_inventory_trial', 'organization_lifecycle_carbon',
  'organization_lifecycle_factor', 'organization_period_inventory', 'province_electricity_factor',
] as const;
export const packageKindText = (t: Translate, kind: string) =>
  (PACKAGE_KIND_KEYS as readonly string[]).includes(kind) ? t(`cm.packageKind.${kind}` as never) : kind;

export function buildRows(rules: CalculationMethodRule[], workspace: ProjectWorkspace | undefined, graph?: Record<string, unknown>): RuleRow[] {
  const nodeName = new Map((workspace?.process_graph?.nodes ?? []).map(node => [node.id, node.name]));
  const fields = workspace?.fields ?? [];
  const flows = modelFlows(graph);
  return rules.map((rule, index) => {
    const field = fields.find(item => item.process_id === rule.process_instance_id
      && (rule.exchange_id ? item.port_id === rule.exchange_id : item.flow_uuid === rule.flow_uuid))
      ?? fields.find(item => item.process_id === rule.process_instance_id && item.flow_uuid === rule.flow_uuid);
    const flow = flows.find(item => item.processId === rule.process_instance_id && `${item.processId}::${item.portId}` === rule.exchange_id);
    const processName = flow?.processName ?? flows.find(item => item.processId === rule.process_instance_id)?.processName ?? nodeName.get(rule.process_instance_id) ?? rule.process_instance_id;
    const flowLabel = flow?.name ?? field?.label ?? rule.exchange_id ?? rule.flow_uuid ?? '';
    return {
      ...rule,
      index,
      processName,
      flowLabel,
      unit: flow?.unit ?? field?.unit ?? '',
      haystack: `${processName} ${flowLabel} ${rule.flow_uuid ?? ''} ${rule.exchange_id ?? ''}`.toLowerCase(),
    };
  });
}
