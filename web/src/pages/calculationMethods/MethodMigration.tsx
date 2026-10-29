import { Alert, Button, Select } from '@arco-design/web-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { api } from '../../api/client';
import type { MethodPurpose } from '../../api/types';
import { useI18n } from '../../i18n';
import { ErrorState } from '../../components/ui/States';

export function MethodMigration({ applicationId, revisionId, modelRevisionIds, onCreated }: {
  applicationId: string; revisionId: string; modelRevisionIds: string[]; onCreated: (id: string) => void;
}) {
  const { t } = useI18n();
  const client = useQueryClient();
  const [source, setSource] = useState('');
  const [version, setVersion] = useState<number>();
  const all = useQuery({ queryKey: ['calculation-methods-all', applicationId], queryFn: () => api.calculationMethods(applicationId) });
  // A legacy method (tag scheme or pre-caliber ordinary) is read-only and converts through its own
  // action, never through a clone.
  const legacy = (method: { semantics?: string | null; purpose: string }) =>
    method.semantics === 'flow_tag.v1' || (method.semantics == null && method.purpose === 'custom');
  const candidates = all.data?.filter(method => method.model_revision_id !== revisionId
    && modelRevisionIds.includes(method.model_revision_id) && !legacy(method)) ?? [];
  const detail = useQuery({ queryKey: ['calculation-method', source], queryFn: () => api.calculationMethod(source), enabled: !!source });
  const migrate = useMutation({ mutationFn: () => api.cloneCalculationMethod(source, version!, {
    name: detail.data!.method.name, purpose: detail.data!.method.purpose as MethodPurpose, model_revision_id: revisionId,
  }), onSuccess: created => {
    client.invalidateQueries({ queryKey: ['calculation-methods', applicationId] });
    client.invalidateQueries({ queryKey: ['calculation-methods-all', applicationId] });
    onCreated(created.method.id);
  } });
  if (!candidates.length && !all.error) return null;
  return <section className="section-panel">
    <h2>{t('cm.migrateTitle')}</h2><p className="helper-text">{t('cm.migrateHint')}</p>
    <div className="form-actions">
      <Select aria-label={t('cm.migrateSource')} style={{ width: 260 }} value={source || undefined}
        options={candidates.map(method => ({ value: method.id, label: method.name }))}
        onChange={value => { setSource(value); setVersion(undefined); migrate.reset(); }} />
      <Select aria-label={t('cm.migrateVersion')} style={{ width: 150 }} value={version}
        options={detail.data?.versions.map(item => ({ value: item.version, label: `v${item.version}` }))}
        onChange={setVersion} />
      <Button disabled={!detail.data || !version} loading={migrate.isPending} onClick={() => migrate.mutate()}>{t('cm.migrateApply')}</Button>
    </div>
    {detail.data?.method.purpose === 'cbam' ? <Alert type="info" content={t('cm.migrateCbamHint')} /> : null}
    {all.error || detail.error || migrate.error ? <ErrorState error={all.error || detail.error || migrate.error} /> : null}
  </section>;
}
