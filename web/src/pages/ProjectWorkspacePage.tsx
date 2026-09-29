import { Alert, Button, Modal, Select, Tabs } from '@arco-design/web-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import type { SolvedSystemSnapshot } from '../api/types';
import { clearProjectDraft } from '../components/projectDraft';
import { useI18n, type MessageKey } from '../i18n';
import { PageHeader } from '../components/ui/PageHeader';
import { EmptyState, ErrorState, LoadingState } from '../components/ui/States';
import { ProjectDataForm } from '../components/ProjectDataForm';
import { ScenariosPage } from './ScenariosPage';
import { ProfessionalProjectPage } from './ProfessionalProjectPage';

// Fixed product task identifiers shown on the analysis tab. These are UI feature names, not domain
// data; an unknown capability keeps its raw key rather than inventing a translation.
const TASK_KEYS: Record<string, MessageKey> = {
  'mfa.solved.v1': 'task.mfa',
  'solve.nebula.v1': 'task.coveredLca',
  'pcf.product.v1': 'task.pcf',
  'cbam.trial.v2': 'task.cbam',
  'climate.native.v1': 'task.climate',
};

function historyTask(snapshot: SolvedSystemSnapshot, organizationBound: boolean, returnedBound: boolean): { view: string; label: MessageKey } {
  const basis = snapshot.provider_receipt.calculation_basis as {
    purpose?: string; model_derivation?: { purpose?: string };
    calculation_method?: { reference?: string; content_sha256?: string };
  } | undefined;
  const purpose = basis?.model_derivation?.purpose ?? basis?.purpose;
  if (purpose === 'cbam') return { view: 'cbam', label: 'task.cbam' };
  if (purpose === 'lca' && organizationBound && !returnedBound) return { view: 'organization-lifecycle', label: 'task.organization' };
  const method = basis?.calculation_method;
  if (method?.reference && method.content_sha256) return { view: 'pcf', label: 'task.pcf' };
  if (snapshot.native_background_climate) return { view: 'climate', label: 'workspace.historyPartialClimate' };
  return { view: 'mfa', label: 'task.mfa' };
}

export function ProjectWorkspacePage() {
  const { applicationId = '' } = useParams();
  const { lang } = useI18n();
  const application = useQuery({ queryKey: ['application', applicationId, lang], queryFn: () => api.application(applicationId, lang) });
  if (application.isLoading) return <main className="app-page"><LoadingState /></main>;
  if (application.isError) return <main className="app-page"><ErrorState error={application.error} /></main>;
  if (application.data?.context.modeling_handoff_id && !application.data?.context.template_locked) return <ProfessionalProjectPage key={application.data.id} application={application.data} />;
  if (!application.data?.context.template_locked) return <ScenariosPage />;
  return <ProjectWorkspace applicationId={applicationId} name={application.data.name} purposeBound={Boolean(application.data.context.seed_template || application.data.context.modeling_template_binding)} returnedBound={Boolean(application.data.context.modeling_template_binding)} methodRefs={Array.isArray(application.data.context.method_package_refs) ? application.data.context.method_package_refs.filter((ref): ref is string => typeof ref === 'string') : []} />;
}

function ProjectWorkspace({ applicationId, name, purposeBound, returnedBound, methodRefs }: { applicationId: string; name: string; purposeBound: boolean; returnedBound: boolean; methodRefs: string[] }) {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const client = useQueryClient();
  const { t, lang, formatDate } = useI18n();
  const models = useQuery({ queryKey: ['models', applicationId], queryFn: () => api.models(applicationId) });
  const model = params.get('model') ?? models.data?.[0]?.id ?? '';
  const revisions = useQuery({ queryKey: ['revisions', model], queryFn: () => api.revisions(model), enabled: !!model && !!models.data?.some(m => m.id === model) });
  // An absent selection opens the last saved data version; an explicit invalid one is refused.
  const revisionId = params.get('revision') ?? revisions.data?.at(-1)?.id ?? '';
  const revision = revisions.data?.find(r => r.id === revisionId);
  // A draft lives only while its own version is on screen; on leaving, keep or discard it by choice.
  const [draftDirty, setDraftDirty] = useState(false);
  const [pendingSwitch, setPendingSwitch] = useState<string | null>(null);
  // Tracked so a save resolving after the operator switched versions cannot drag them back.
  const resolvedRevisionRef = useRef(revisionId);
  resolvedRevisionRef.current = revisionId;
  const activeSolveKey = useRef<string | null>(null);
  const workspace = useQuery({ queryKey: ['workspace', applicationId, revisionId, lang], queryFn: () => api.workspace(applicationId, revisionId, lang), enabled: !!revision });
  const packages = useQuery({ queryKey: ['method-packages', applicationId], queryFn: api.methodPackages });
  const snapshots = useQuery({ queryKey: ['solved-snapshots', applicationId], queryFn: () => api.solvedSnapshots(applicationId) });
  const step = params.get('step') ?? 'data';
  const activeStep = step === 'overview' || step === 'background' ? 'data' : step;
  const goto = (next: string, process?: string) => setParams(prev => { const p = new URLSearchParams(prev); p.set('step', next); if (revision) p.set('revision', revision.id); if (process) p.set('process', process); return p; });
  const setStep = (next: string) => goto(next);
  const applyRevision = (id: string) => {
    solve.reset();
    setDraftDirty(false);
    setPendingSwitch(null);
    setParams(prev => { const p = new URLSearchParams(prev); p.set('revision', id); return p; });
  };
  const requestRevision = (id: string) => {
    if (id === revisionId) return;
    if (draftDirty) setPendingSwitch(id);
    else applyRevision(id);
  };
  const supportsPcf = workspace.data?.capabilities.includes('pcf.product.v1');
  const supportsCbam = workspace.data?.capabilities.includes('cbam.trial.v2');
  const cbamBlocked = workspace.data?.blocked_capabilities.some(item => item.capability === 'cbam.trial.v2');
  const calculationReady = packages.isSuccess;
  const climateReady = !!workspace.data?.native_climate?.available;
  const inventoryReady = !!workspace.data?.native_inventory?.available;
  const supportsOrganizationLifecycle = workspace.data?.capabilities.includes('organization.lifecycle-carbon.v1');
  const organizationMethod = methodRefs.slice().reverse().map(ref => packages.data?.find(item => `${item.package_id}@${item.version}` === ref)).find(item => item?.package_kind === 'organization_lifecycle_carbon');
  const projectSupplyMethod = (organizationMethod?.manifest.classification_rules as Record<string, unknown> | undefined)?.energy_path_source === 'project_background_process_receipts';
  const missingSupply = projectSupplyMethod && !workspace.data?.project_background_pins?.length;
  const organizationFormula = organizationMethod?.manifest.formula_graph as Record<string, unknown> | undefined;
  const organizationSnapshot = (snapshots.data ?? []).filter(item => item.system_revision_id === revisionId && (projectSupplyMethod
    ? Array.isArray(item.provider_receipt.project_background_process_receipts) && item.provider_receipt.project_background_process_receipts.length > 0
      && item.lcia_results.method === organizationFormula?.lcia_method
      && Array.isArray(item.lcia_results.indicator_contribution_receipts)
      && item.lcia_results.indicator_contribution_receipts.some(receipt => typeof receipt === 'object' && receipt !== null
        && (receipt as Record<string, unknown>).canonical_indicator_key === organizationFormula?.total_indicator_key)
    : !!item.native_background_climate)).at(-1);
  const reviewCbam = useMutation({
    mutationFn: () => api.applyReviewedCbam(applicationId, revisionId, lang),
    onSuccess: async next => {
      client.setQueryData(['workspace', applicationId, revisionId, lang], next);
      await Promise.all([
        client.invalidateQueries({ queryKey: ['method-packages', applicationId] }),
        client.invalidateQueries({ queryKey: ['application', applicationId] }),
      ]);
    },
  });
  const solve = useMutation({
    mutationFn: (view: 'mfa' | 'lca' | 'pcf' | 'cbam' | 'climate' | 'organization') => {
      if (!workspace.data?.saved || !revision) throw new Error(t('workspace.saveBeforeCompute'));
      if (view === 'pcf' && !supportsPcf) throw new Error(t('workspace.needPcfMethod'));
      if (view === 'cbam' && (!supportsCbam || cbamBlocked)) throw new Error(t('workspace.cbamBoundaryUnreviewed'));
      if (view === 'climate' && !climateReady) throw new Error(t('workspace.climateScopeMismatch'));
      // The product method projects the frozen native climate answer. Its source solve uses the
      // reviewed full-model LCA derivation; this template declares no separate PCF derivation.
      const purpose = purposeBound && (view === 'lca' || view === 'climate' || view === 'cbam' || view === 'organization' || (view === 'pcf' && returnedBound))
        ? (view === 'climate' || view === 'pcf' || view === 'organization' ? 'lca' : view) : undefined;
      const nativeMfa = view === 'mfa' && Boolean(workspace.data.mapped_background_process_pins?.length) && inventoryReady;
      const baseKey = `${view === 'pcf' ? 'project-climate-v1' : nativeMfa ? 'project-inventory-v1' : purpose ? 'project-v2' : 'project'}-${view}:${revision.id}:${revision.content_sha256}`;
      activeSolveKey.current = baseKey;
      const retry = Number(localStorage.getItem(retryStorageKey(baseKey)) ?? 0);
      const payload = {
        demand: workspace.data.demand,
        background_process_pins: workspace.data.background_process_pins ?? [],
        mapped_background_process_pins: workspace.data.mapped_background_process_pins ?? [],
        ...(workspace.data.project_background_pins?.length ? { project_background_pins: workspace.data.project_background_pins } : {}),
        // One data version can be computed as several different tasks, and the climate total is a
        // different calculation basis from a projection, so each task keys its own run: sharing a
        // key would refuse the second task as a conflicting replay of the first.
        idempotency_key: Number.isSafeInteger(retry) && retry > 0 ? `${baseKey}:retry-${retry}` : baseKey,
        ...(purpose ? { calculation_purpose: purpose } : {}),
        // New product climate calculations resolve the pinned method on the server.
        ...(view === 'climate' ? { native_background_climate: true } : nativeMfa ? { native_background_inventory: true } : view === 'pcf' || view === 'organization' ? { climate_default: true } : {}),
      };
      return api.solveAndFreeze(applicationId, revision.id, payload);
    },
    onSuccess: (snapshot, view) => { if (activeSolveKey.current) localStorage.removeItem(retryStorageKey(activeSolveKey.current)); activeSolveKey.current = null; client.setQueryData<SolvedSystemSnapshot[]>(['solved-snapshots', applicationId], previous => previous?.some(item => item.id === snapshot.id) ? previous : [...(previous ?? []), snapshot]); client.invalidateQueries({ queryKey: ['solved-snapshots', applicationId] }); navigate(`/applications/${applicationId}/results?snapshot=${snapshot.id}&view=${view === 'lca' ? 'mfa' : view === 'organization' ? 'organization-lifecycle' : view}`); },
    onError: () => { if (activeSolveKey.current) { const key = retryStorageKey(activeSolveKey.current); const previous = Number(localStorage.getItem(key) ?? 0); localStorage.setItem(key, String(Number.isSafeInteger(previous) && previous >= 0 ? previous + 1 : 1)); activeSolveKey.current = null; } },
  });
  const error = models.error || revisions.error || workspace.error;
  const retry = () => { models.refetch(); if (model) revisions.refetch(); if (revision) workspace.refetch(); };
  const badSelection = (models.isSuccess && !models.data.some(m => m.id === model)) || (revisions.isSuccess && !revision) || !['overview', 'data', 'background', 'reports'].includes(step);
  const revisionLabel = (number: number) => number === 1 ? t('workspace.revisionBase') : t('workspace.revisionNth', { number });
  return <main className="app-page project-workspace-page">
    <div className="project-workspace-header">
    <PageHeader title={name} description="" action={<div className="project-header-links">{revision ? <Link to={`/modeling?application=${applicationId}&model=${model}&revision=${revision.id}&launch=1`} target="_blank" rel="noopener noreferrer">{t('workspace.editProcess')}</Link> : null}<Link className="project-back-link" to="/applications">{t('workspace.backToProjects')}</Link></div>} />
    {workspace.data && !badSelection ? <div className="project-version-bar"><span>{t('workspace.dataVersion')}</span><Select aria-label={t('workspace.dataVersionAria')} value={revisionId} onChange={requestRevision} options={revisions.data?.map(r => ({ label: `${revisionLabel(r.revision_number)} · ${formatDate(r.created_at)}`, value: r.id }))} /></div> : null}
    </div>
    {error ? <ErrorState error={error} onRetry={retry} /> : badSelection ? <Alert type="error" content={t('workspace.badSelection')} action={<Button onClick={() => setParams({ step: 'data' })}>{t('workspace.clearSelection')}</Button>} /> : !workspace.data ? <LoadingState /> : <>
      <Tabs className="project-workspace-tabs" activeTab={activeStep} onChange={setStep}>
        <Tabs.TabPane key="data" title={t('workspace.tabData')}><ProjectDataForm key={revisionId} workspace={workspace.data} onReload={() => workspace.refetch()} onDirtyChange={setDraftDirty} onSaved={async (next, base) => { client.setQueryData(['workspace', applicationId, next.revision_id, lang], next); await Promise.all([client.invalidateQueries({ queryKey: ['revisions', model] }), client.invalidateQueries({ queryKey: ['application', applicationId] })]); if (resolvedRevisionRef.current !== base) return; setParams(prev => { const p = new URLSearchParams(prev); p.set('revision', next.revision_id); p.set('step', 'data'); return p; }); }} /></Tabs.TabPane>
        <Tabs.TabPane key="reports" title={t('workspace.tabReports')}><section className="section-panel">
          <h2>{t('workspace.chooseTask')}</h2>
          {!workspace.data.saved ? <Alert type="warning" content={t('workspace.saveFirst')} action={<Button onClick={() => setStep('data')}>{t('workspace.goFill')}</Button>} /> : null}
          <div className="home-actions">
            {workspace.data.capabilities.includes('mfa.solved.v1') ? <Button disabled={!workspace.data.saved || solve.isPending} loading={solve.isPending && solve.variables === 'mfa'} onClick={() => solve.mutate('mfa')}>{t('workspace.computeMfa')}</Button> : null}
            {workspace.data.capabilities.includes('pcf.product.v1') ? <Button type="primary" disabled={!workspace.data.saved || !calculationReady || solve.isPending || missingSupply} loading={solve.isPending && solve.variables === 'pcf'} onClick={() => solve.mutate('pcf')}>{t('workspace.computePcf')}</Button> : null}
            {supportsCbam ? <Button type="primary" disabled={!workspace.data.saved || !calculationReady || cbamBlocked || solve.isPending} loading={solve.isPending && solve.variables === 'cbam'} onClick={() => solve.mutate('cbam')}>{t('workspace.computeCbam')}</Button> : null}
            {returnedBound && cbamBlocked ? <Button
              disabled={!workspace.data.saved || reviewCbam.isPending}
              loading={reviewCbam.isPending} onClick={() => reviewCbam.mutate()}>{t('workspace.applyCbamRules')}</Button> : null}
            {supportsOrganizationLifecycle && organizationMethod ? <Button disabled={!workspace.data.saved || !calculationReady || solve.isPending || missingSupply} loading={solve.isPending && solve.variables === 'organization'} onClick={() => solve.mutate('organization')}>{t('workspace.fillOrganization')}</Button> : null}
          </div>
          {missingSupply ? <Alert type="warning" content="产品碳足迹和组织碳核算需要先关联电力供应。请在“工艺与数据”的电力投入行选择“关联自建供应过程”，校验已安装的开放电力项目并保存新版本。" action={<Button onClick={() => setStep('data')}>去关联电力</Button>} /> : null}
          {packages.isError ? <ErrorState error={packages.error} onRetry={() => packages.refetch()} /> : workspace.data.capabilities.includes('pcf.product.v1') && !supportsPcf ? <p className="helper-text">{t('workspace.pcfNeedsMethod')}</p> : null}
          {workspace.data.blocked_capabilities.map(item => <Alert key={item.capability} type="warning" content={t('workspace.blockedFormat', { task: TASK_KEYS[item.capability] ? t(TASK_KEYS[item.capability]) : item.capability, reason: item.reason ?? t('workspace.taskUnavailable') })} />)}
          <p className="helper-text">{t('workspace.onlySupported')}</p>
          {solve.isError ? <ErrorState error={solve.error} /> : null}
          {reviewCbam.isError ? <ErrorState error={reviewCbam.error} /> : null}
        </section>
          <section className="section-panel"><h2>{t('workspace.history')}</h2>{snapshots.isLoading ? <LoadingState /> : snapshots.isError ? <ErrorState error={snapshots.error} /> : !snapshots.data?.length ? <EmptyState description={t('workspace.historyEmpty')} /> : snapshots.data.map(s => { const task = historyTask(s, Boolean(supportsOrganizationLifecycle), returnedBound); return <Link key={s.id} className="home-project-row" to={`/applications/${applicationId}/results?snapshot=${s.id}&view=${task.view}`}><strong>{t('workspace.historyEntry', { number: revisions.data?.find(r => r.id === s.system_revision_id)?.revision_number ?? '', kind: t(task.label) })}</strong><span>{formatDate(s.created_at)} →</span></Link>; })}</section>
        </Tabs.TabPane>
      </Tabs>
    </>}
    <Modal
      className="draft-switch-modal"
      title={t('workspace.draftTitle')}
      visible={!!pendingSwitch}
      onCancel={() => setPendingSwitch(null)}
      footer={<div className="form-actions">
        <Button onClick={() => setPendingSwitch(null)}>{t('workspace.draftCancel')}</Button>
        <Button onClick={() => { clearProjectDraft(applicationId, revisionId); applyRevision(pendingSwitch ?? revisionId); }}>{t('workspace.draftDiscard')}</Button>
        <Button type="primary" onClick={() => applyRevision(pendingSwitch ?? revisionId)}>{t('workspace.draftKeep')}</Button>
      </div>}
    >{t('workspace.draftBody')}</Modal>
  </main>;
}

const retryStorageKey = (base: string) => `nebula-one:solve-retry:${base}`;
