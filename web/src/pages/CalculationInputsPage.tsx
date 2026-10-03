import { Select } from '@arco-design/web-react';
import { useQuery } from '@tanstack/react-query';
import { useParams, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import { useI18n } from '../i18n';
import { PageHeader } from '../components/ui/PageHeader';
import { ErrorState, LoadingState } from '../components/ui/States';
import { ReadOnlyProjectInventory } from '../components/ReadOnlyProjectInventory';
import { ReturnToProject } from '../components/ReturnToProject';

export function CalculationInputsPage() {
  const { applicationId = '' } = useParams();
  const [params, setParams] = useSearchParams();
  const { t, lang, formatDate } = useI18n();
  const application = useQuery({ queryKey: ['application', applicationId, lang], queryFn: () => api.application(applicationId, lang) });
  const snapshots = useQuery({ queryKey: ['solved-snapshots', applicationId], queryFn: () => api.solvedSnapshots(applicationId) });
  const snapshot = snapshots.data?.find(item => item.id === params.get('snapshot'));
  const workspace = useQuery({ queryKey: ['workspace', applicationId, snapshot?.system_revision_id, lang],
    queryFn: () => api.workspace(applicationId, snapshot!.system_revision_id, lang), enabled: !!snapshot });
  const error = application.error || snapshots.error || workspace.error;
  return <main className="app-page compact-result-page">
    <PageHeader title={t('inventory.calculationInputs')} description={application.data?.name ?? ''} action={<ReturnToProject applicationId={applicationId} />} />
    {snapshot ? <div className="result-page-header__records">
      <label htmlFor="inventory-record">{t('analysis.recordSelectorAria')}</label>
      <Select id="inventory-record" value={snapshot.id} options={snapshots.data?.map((item, index) => ({ value: item.id,
        label: t('results.record', { number: index + 1, date: formatDate(item.created_at) }) }))}
        onChange={id => setParams({ snapshot: id })} />
    </div> : null}
    {error ? <ErrorState error={error} /> : snapshots.isLoading || workspace.isLoading ? <LoadingState />
      : !snapshot ? <ErrorState error={new Error(t('results.unknownSnapshot'))} />
      : workspace.data ? <ReadOnlyProjectInventory workspace={workspace.data} snapshot={snapshot} /> : null}
  </main>;
}
