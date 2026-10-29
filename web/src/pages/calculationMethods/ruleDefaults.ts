import type { CalculationMethodRule } from '../../api/types';

/** Defaults apply within their declared direction and contribution domain, never by name. */
export function processDefaultFor(rule: CalculationMethodRule, rules: CalculationMethodRule[]) {
  return rules.find(base => base.process_instance_id === rule.process_instance_id && !base.exchange_id && !base.flow_uuid
    && (!base.direction || base.direction === rule.direction)
    && (base.contribution_target ?? 'direct') === (rule.contribution_target ?? 'direct'));
}
