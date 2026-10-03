import type { ProjectWorkspace } from '../api/types';
import { useI18n } from '../i18n';

export function CalculationTarget({ workspace, demand = workspace?.demand }: {
  workspace?: ProjectWorkspace;
  demand?: ProjectWorkspace['demand'];
}) {
  const { t, formatNumber } = useI18n();
  if (!demand?.length) return null;
  if (demand.length !== 1) return <p>{t('calculation.multipleTargets')}</p>;
  const target = demand[0];
  const names = [...new Set((workspace?.fields ?? []).filter(field => field.reference_product
    && field.flow_uuid === target.reference_flow_uuid).map(field => field.label))];
  return <p>{t('calculation.product')}: <strong>{names.length === 1 ? names[0] : t('mfa.unnamedFlow')}</strong>
    {' · '}<span style={{ whiteSpace: 'nowrap' }}>{formatNumber(target.amount)} {target.unit}</span></p>;
}
