import { Button } from '@arco-design/web-react';
import { useQuery } from '@tanstack/react-query';
import { useParams, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import { OrganizationLifecyclePanel } from '../components/OrganizationLifecyclePanel';
import { PageHeader } from '../components/ui/PageHeader';
import { EmptyState, ErrorState, LoadingState } from '../components/ui/States';
import { useI18n } from '../i18n';

export function OrganizationCalculationPage() {
  const { applicationId = '' } = useParams();
  const [params, setParams] = useSearchParams();
  const { t, lang } = useI18n();
  const snapshotId = params.get('snapshot') ?? '';
  const recordId = params.get('record') ?? undefined;
  const application = useQuery({ queryKey: ['application', applicationId, lang], queryFn: () => api.application(applicationId, lang) });
  const snapshots = useQuery({ queryKey: ['solved-snapshots', applicationId], queryFn: () => api.solvedSnapshots(applicationId) });
  const packages = useQuery({ queryKey: ['method-packages', applicationId], queryFn: api.methodPackages });
  const snapshot = snapshots.data?.find(item => item.id === snapshotId);
  const refs = application.data?.context.method_package_refs ?? [];
  const method = Array.isArray(refs) ? refs.slice().reverse().map(ref => packages.data?.find(item => `${item.package_id}@${item.version}` === ref))
    .find(item => item?.package_kind === 'organization_lifecycle_carbon') : undefined;
  const back = `/applications/${applicationId}/workbench${snapshot ? `?revision=${snapshot.system_revision_id}` : ''}`;
  return <main className="app-page"><PageHeader title={t('task.organization')} description={application.data?.name ?? ''}
    action={<Button href={back}>{t('analysis.backToProject')}</Button>} />
    {application.isLoading || snapshots.isLoading || packages.isLoading ? <LoadingState /> : null}
    {application.isError || snapshots.isError || packages.isError ? <ErrorState error={application.error || snapshots.error || packages.error} /> : null}
    {!snapshot || !method ? (!snapshots.isLoading && !packages.isLoading ? <EmptyState description={t('results.taskMissing')} /> : null) :
      <section className="section-panel"><OrganizationLifecyclePanel applicationId={applicationId} snapshot={snapshot} method={method}
        methodPackages={packages.data} recordId={recordId} onCreated={id => setParams({ snapshot: snapshot.id, record: id })} /></section>}
  </main>;
}
