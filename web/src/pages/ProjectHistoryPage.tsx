import { useQuery } from '@tanstack/react-query';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import type { SolvedSystemSnapshot } from '../api/types';
import { useI18n } from '../i18n';
import { PageHeader } from '../components/ui/PageHeader';
import { EmptyState, ErrorState, LoadingState } from '../components/ui/States';
import { ReturnToProject } from '../components/ReturnToProject';

function snapshotTask(snapshot: SolvedSystemSnapshot): 'cbam' | 'pcf' | 'mfa' | 'organization' {
  const declared = snapshot.provider_receipt.analysis_task;
  if (declared === 'cbam' || declared === 'pcf' || declared === 'mfa' || declared === 'organization') return declared;
  const basis = snapshot.provider_receipt.calculation_basis as { purpose?: string; model_derivation?: { purpose?: string } } | undefined;
  if ((basis?.model_derivation?.purpose ?? basis?.purpose) === 'cbam') return 'cbam';
  if (snapshot.native_background_climate || (Array.isArray(snapshot.provider_receipt.project_background_process_receipts) && snapshot.provider_receipt.project_background_process_receipts.length)) return 'pcf';
  return 'mfa';
}

export function ProjectHistoryPage() {
  const { applicationId = '' } = useParams();
  const [params] = useSearchParams();
  const { t, lang, formatDate } = useI18n();
  const application = useQuery({ queryKey: ['application', applicationId, lang], queryFn: () => api.application(applicationId, lang) });
  const models = useQuery({ queryKey: ['models', applicationId], queryFn: () => api.models(applicationId) });
  const model = models.data?.[0]?.id ?? '';
  const revisions = useQuery({ queryKey: ['revisions', model], queryFn: () => api.revisions(model), enabled: !!model });
  const snapshots = useQuery({ queryKey: ['solved-snapshots', applicationId], queryFn: () => api.solvedSnapshots(applicationId) });
  const records = useQuery({ queryKey: ['organization-lifecycle', applicationId], queryFn: () => api.organizationLifecycleInventories(applicationId) });
  const revision = params.get('revision');
  const items = (snapshots.data ?? []).filter(item => (!revision || item.system_revision_id === revision)
    && !(item.provider_receipt.analysis_task === 'organization' && (records.data ?? []).some(record => record.solved_snapshot_id === item.id))).map(item => {
    const task = snapshotTask(item);
    return { id: item.id, snapshotId: item.id, date: item.created_at, revision: item.system_revision_id,
      label: task === 'organization' ? t('workspace.orgPending') : t(`task.${task}`),
      href: task === 'organization' ? `/applications/${applicationId}/organization?snapshot=${item.id}`
        : `/applications/${applicationId}/results?snapshot=${item.id}&view=${task}` };
  });
  const organizationItems = (records.data ?? []).filter(item => !revision || (snapshots.data ?? []).some(snapshot => snapshot.id === item.solved_snapshot_id && snapshot.system_revision_id === revision)).map(item => ({
    id: item.id, snapshotId: item.solved_snapshot_id, date: (snapshots.data ?? []).find(snapshot => snapshot.id === item.solved_snapshot_id)?.created_at ?? '', revision: (snapshots.data ?? []).find(snapshot => snapshot.id === item.solved_snapshot_id)?.system_revision_id ?? '',
    label: t('task.organization'), href: `/applications/${applicationId}/organization?snapshot=${item.solved_snapshot_id}&record=${item.id}`,
  }));
  return <main className="app-page"><PageHeader title={t('workspace.history')} description={application.data?.name ?? ''} action={<ReturnToProject applicationId={applicationId} />} />
    {snapshots.isLoading || records.isLoading ? <LoadingState /> : null}
    {application.isError || snapshots.isError || records.isError ? <ErrorState error={application.error || snapshots.error || records.error} /> : null}
    {!snapshots.isLoading && !records.isLoading && !items.length && !organizationItems.length ? <EmptyState description={t('workspace.historyEmpty')} /> : null}
    {[...items, ...organizationItems].sort((a, b) => b.date.localeCompare(a.date)).map(item => <div key={item.id} className="history-record">
      <Link className="home-project-row" to={item.href}><strong>{item.label}</strong><span>{formatDate(item.date)} · {t('workspace.dataVersion')} {revisions.data?.find(row => row.id === item.revision)?.revision_number ?? item.revision.slice(0, 8)} →</span></Link>
      <Link to={`/applications/${applicationId}/calculation-inputs?snapshot=${item.snapshotId}`}>{t('inventory.viewCalculationInputs')}</Link>
    </div>)}
  </main>;
}
