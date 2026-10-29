import type { MessageKey } from '../../i18n';

type Translate = (key: MessageKey, vars?: Record<string, string | number>) => string;

/**
 * The backend emits stable rationale/basis/status code strings and never a translation, so the UI owns
 * the wording. Each set below mirrors exactly the codes `classification_suggestion.py` can produce; a
 * code the table does not know is shown verbatim rather than blanked or invented, so a new backend
 * rationale degrades honestly instead of silently.
 */
const RATIONALE = new Set([
  'onsite_direct_emission',
  'purchased_energy_path',
  'non_energy_supply_path',
  'purchased_input_energy_unresolved',
  'foreground_internal_transfer',
  'not_an_emission',
  'manual_rule_present',
]);

const BASIS = new Set([
  'rule.manual',
  'flow_type.elementary',
  'flow_type.technosphere',
  'direction.input',
  'direction.output',
  'direction.emission',
  'direction.resource',
  'contribution_domain.direct',
  'contribution_domain.upstream',
  'consumer_path.internal',
  'consumer_path.purchased',
  'energy_property.declared_energy',
  'energy_property.not_declared_energy',
  'energy_property.unresolved',
]);

const STATUS = new Set(['suggested', 'already_classified', 'not_applicable', 'pending_evidence']);
const CONFIDENCE = new Set(['high', 'medium', 'insufficient', 'none']);

/** The operator-facing meaning of each Scope grouping, kept separate from the raw `Scope N` label. */
const BUSINESS_SCOPE: Record<string, MessageKey> = {
  scope_1: 'cm.suggest.business.scope_1',
  scope_2: 'cm.suggest.business.scope_2',
  scope_3: 'cm.suggest.business.scope_3',
};

export const rationaleText = (t: Translate, code: string): string =>
  RATIONALE.has(code) ? t(`cm.suggest.rationale.${code}` as MessageKey) : code;

export const basisText = (t: Translate, code: string): string =>
  BASIS.has(code) ? t(`cm.suggest.basis.${code}` as MessageKey) : code;

export const suggestStatusText = (t: Translate, code: string): string =>
  STATUS.has(code) ? t(`cm.suggest.status.${code}` as MessageKey) : code;

export const confidenceText = (t: Translate, code: string): string =>
  CONFIDENCE.has(code) ? t(`cm.suggest.confidence.${code}` as MessageKey) : code;

export const businessScopeText = (t: Translate, scope: string | null): string | null =>
  scope && BUSINESS_SCOPE[scope] ? t(BUSINESS_SCOPE[scope]) : null;
