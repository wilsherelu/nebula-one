import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import { OrganizationLifecyclePanel } from '../components/OrganizationLifecyclePanel';
import { EmptyState, ErrorState, LoadingState } from '../components/ui/States';
import { useI18n } from '../i18n';
import { ResultActionsTarget } from '../components/ResultHeaderActions';
import { ReturnToProject } from '../components/ReturnToProject';
import { Link } from 'react-router-dom';

export function OrganizationCalculationPage() {
  const { applicationId = '' } = useParams();
  const [params, setParams] = useSearchParams();
  const { t, lang } = useI18n();
  const client = useQueryClient();
  const [actionsTarget, setActionsTarget] = useState<HTMLDivElement | null>(null);
  const attempted = useRef('');
  const snapshotId = params.get('snapshot') ?? '';
  const activeSnapshot = useRef(snapshotId);
  activeSnapshot.current = snapshotId;
  const recordId = params.get('record') ?? undefined;
  const application = useQuery({ queryKey: ['application', applicationId, lang], queryFn: () => api.application(applicationId, lang) });
  const snapshots = useQuery({ queryKey: ['solved-snapshots', applicationId], queryFn: () => api.solvedSnapshots(applicationId) });
  const packages = useQuery({ queryKey: ['method-packages', applicationId], queryFn: api.methodPackages });
  const snapshot = snapshots.data?.find(item => item.id === snapshotId);
  const refs = application.data?.context.method_package_refs ?? [];
  const method = Array.isArray(refs) ? refs.slice().reverse().map(ref => packages.data?.find(item => `${item.package_id}@${item.version}` === ref))
    .find(item => item?.package_kind === 'organization_lifecycle_carbon') : undefined;
  const calculate = useMutation({
    mutationFn: () => api.createOrganizationCurrentModel(applicationId, {
      solved_snapshot_id: snapshot!.id, method_package_ref: `${method!.package_id}@${method!.version}`,
    }),
    onSuccess: result => {
      client.invalidateQueries({ queryKey: ['organization-lifecycle', applicationId] });
      if (activeSnapshot.current !== result.solved_snapshot_id) return;
      setParams({ snapshot: result.solved_snapshot_id, record: result.id }, { replace: true });
    },
  });
  useEffect(() => {
    const key = `${applicationId}:${snapshot?.id}:${method?.content_sha256}`;
    if (!recordId && snapshot && method && attempted.current !== key) {
      attempted.current = key;
      calculate.mutate();
    }
  }, [applicationId, snapshot, method, recordId]);
  return <ResultActionsTarget.Provider value={actionsTarget}><main className="app-page compact-result-page"><header className="result-page-header">
    <div className="result-page-header__top">
      <h1>{application.data?.name ?? ''} <span>· {t('task.organization')}</span></h1>
      <div className="result-header-actions"><div ref={setActionsTarget} /><ReturnToProject applicationId={applicationId} /></div>
    </div>
  </header>
    {snapshot ? <Link className="calculation-inputs-link" to={`/applications/${applicationId}/calculation-inputs?snapshot=${snapshot.id}`}>{t('inventory.viewCalculationInputs')}</Link> : null}
    {application.isLoading || snapshots.isLoading || packages.isLoading ? <LoadingState /> : null}
    {application.isError || snapshots.isError || packages.isError ? <ErrorState error={application.error || snapshots.error || packages.error} /> : null}
    {calculate.isPending ? <LoadingState /> : null}
    {calculate.isError ? <ErrorState error={calculate.error} onRetry={() => calculate.mutate()} /> : null}
    {!snapshot || !method ? (!snapshots.isLoading && !packages.isLoading ? <EmptyState description={t('results.taskMissing')} /> : null) : recordId || calculate.isError ?
      <section className="section-panel"><OrganizationLifecyclePanel applicationId={applicationId} snapshot={snapshot} method={method}
        methodPackages={packages.data} recordId={recordId} onCreated={id => setParams({ snapshot: snapshot.id, record: id })} /></section> : null}
  </main></ResultActionsTarget.Provider>;
}
