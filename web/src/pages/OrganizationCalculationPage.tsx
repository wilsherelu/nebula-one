import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import { OrganizationLifecyclePanel } from '../components/OrganizationLifecyclePanel';
import { EmptyState, ErrorState, LoadingState } from '../components/ui/States';
import { useI18n } from '../i18n';
import { ResultMenuProvider, ResultMoreMenu } from '../components/ResultHeaderActions';
import { CalculationInputsDialog } from '../components/CalculationInputsDialog';
import { ReturnToProject } from '../components/ReturnToProject';
import { Select } from '@arco-design/web-react';

export function OrganizationCalculationPage() {
  const { applicationId = '' } = useParams();
  const [params, setParams] = useSearchParams();
  const { t, lang, formatDate } = useI18n();
  const client = useQueryClient();
  const moreTrigger = useRef<HTMLButtonElement>(null);
  const [inputsSnapshotId, setInputsSnapshotId] = useState<string>();
  const attempted = useRef('');
  const snapshotId = params.get('snapshot') ?? '';
  const activeSnapshot = useRef(snapshotId);
  activeSnapshot.current = snapshotId;
  const recordId = params.get('record') ?? undefined;
  const application = useQuery({ queryKey: ['application', applicationId, lang], queryFn: () => api.application(applicationId, lang) });
  const snapshots = useQuery({ queryKey: ['solved-snapshots', applicationId], queryFn: () => api.solvedSnapshots(applicationId) });
  const packages = useQuery({ queryKey: ['method-packages', applicationId], queryFn: api.methodPackages });
  const records = useQuery({ queryKey: ['organization-lifecycle', applicationId], queryFn: () => api.organizationLifecycleInventories(applicationId) });
  const selectedRecord = records.data?.find(record => record.id === recordId && record.solved_snapshot_id === snapshotId);
  const snapshot = snapshots.data?.find(item => item.id === snapshotId);
  useEffect(() => { setInputsSnapshotId(undefined); }, [snapshotId, recordId]);
  const refs = application.data?.context.method_package_refs ?? [];
  const method = recordId ? packages.data?.find(item => `${item.package_id}@${item.version}` === selectedRecord?.result.method_package.reference
    && item.content_sha256 === selectedRecord.result.method_package.content_sha256) : Array.isArray(refs) ? refs.slice().reverse().map(ref => packages.data?.find(item => `${item.package_id}@${item.version}` === ref))
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
  return <ResultMenuProvider scope={`${snapshotId}:${recordId}`}><main className="app-page compact-result-page"><header className="result-page-header">
    <div className="result-page-header__top">
      <h1>{application.data?.name ?? ''} <span>· {t('task.organization')}</span></h1>
      <div className="result-header-actions"><ResultMoreMenu triggerRef={moreTrigger} actions={snapshot ? [
        { key: 'inputs', label: t('inventory.viewCalculationInputs'), run: () => setInputsSnapshotId(snapshot.id) },
      ] : []} /><ReturnToProject applicationId={applicationId} /></div>
    </div>
    {recordId && records.data?.length ? <div className="result-page-header__records"><label htmlFor="organization-record">{t('analysis.recordSelectorAria')}</label>
      <Select id="organization-record" value={selectedRecord?.id} onChange={value => {
        const next = records.data.find(record => record.id === value);
        if (next) setParams({snapshot:next.solved_snapshot_id,record:next.id});
      }} options={records.data.map((record,index)=>({value:record.id,label:t('results.record',{number:records.data.length-index,date:formatDate(record.created_at)})}))} />
    </div> : null}
  </header>
    {application.isLoading || snapshots.isLoading || packages.isLoading || records.isLoading ? <LoadingState /> : null}
    {application.isError || snapshots.isError || packages.isError || records.isError ? <ErrorState error={application.error || snapshots.error || packages.error || records.error} /> : null}
    {calculate.isPending ? <LoadingState /> : null}
    {calculate.isError ? <ErrorState error={calculate.error} onRetry={() => calculate.mutate()} /> : null}
    {!snapshot || !method ? (!snapshots.isLoading && !packages.isLoading ? <EmptyState description={t('results.taskMissing')} /> : null) : recordId || calculate.isError ?
      <section className="section-panel"><OrganizationLifecyclePanel applicationId={applicationId} snapshot={snapshot} method={method}
        methodPackages={packages.data} recordId={recordId} onCreated={id => setParams({ snapshot: snapshot.id, record: id })} /></section> : null}
    {snapshot ? <CalculationInputsDialog applicationId={applicationId} snapshot={snapshot}
      visible={inputsSnapshotId === snapshot.id} onClose={() => setInputsSnapshotId(undefined)}
      afterClose={() => moreTrigger.current?.focus({ preventScroll: true })} /> : null}
  </main></ResultMenuProvider>;
}
