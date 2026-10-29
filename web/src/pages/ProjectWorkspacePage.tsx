import { Alert, Button, Modal } from '@arco-design/web-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import type { CalculationMethodDetail, CalculationMethodRef, CalculationMethodValidation, SolvedSystemSnapshot } from '../api/types';
import { clearProjectDraft } from '../components/projectDraft';
import { useI18n } from '../i18n';
import { PageHeader } from '../components/ui/PageHeader';
import { ErrorState, LoadingState } from '../components/ui/States';
import { ProjectDataForm, type ProjectDataFormHandle } from '../components/ProjectDataForm';
import { CalculationMethodDialog, type CalculationTask } from '../components/CalculationMethodDialog';
import { buildSolvePayload, retryStorageKey, solveIdempotencyKey } from '../calculation/solveContract';
import { ScenariosPage } from './ScenariosPage';
import { ProfessionalProjectPage } from './ProfessionalProjectPage';
import { ReadOnlyProjectInventory } from '../components/ReadOnlyProjectInventory';
import { ReturnToProject } from '../components/ReturnToProject';

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
  const { t, lang } = useI18n();
  const models = useQuery({ queryKey: ['models', applicationId], queryFn: () => api.models(applicationId) });
  const model = params.get('model') ?? models.data?.[0]?.id ?? '';
  const revisions = useQuery({ queryKey: ['revisions', model], queryFn: () => api.revisions(model), enabled: !!model && !!models.data?.some(m => m.id === model) });
  // An absent selection opens the last saved data version; an explicit invalid one is refused.
  const revisionId = params.get('revision') ?? revisions.data?.at(-1)?.id ?? '';
  const revision = revisions.data?.find(r => r.id === revisionId);
  const historical = !!revision && revision.id !== revisions.data?.at(-1)?.id;
  // A draft lives only while its own version is on screen; on leaving, keep or discard it by choice.
  const [draftDirty, setDraftDirty] = useState(false);
  const [pendingLeave, setPendingLeave] = useState<string | null>(null);
  const [calculationOpen, setCalculationOpen] = useState(false);
  const [selectedTask, setSelectedTask] = useState<CalculationTask>('pcf');
  const [selectedMethodId, setSelectedMethodId] = useState<string | null>(null);
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const [checkedRef, setCheckedRef] = useState<CalculationMethodRef | null>(null);
  const [validation, setValidation] = useState<CalculationMethodValidation | null>(null);
  const [saving, setSaving] = useState(false);
  const formRef = useRef<ProjectDataFormHandle>(null);
  useEffect(() => {
    if (!draftDirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [draftDirty]);
  // Tracked so a save resolving after the operator switched versions cannot drag them back.
  const resolvedRevisionRef = useRef(revisionId);
  resolvedRevisionRef.current = revisionId;
  const activeSolveKey = useRef<string | null>(null);
  const workspace = useQuery({ queryKey: ['workspace', applicationId, revisionId, lang], queryFn: () => api.workspace(applicationId, revisionId, lang), enabled: !!revision });
  const packages = useQuery({ queryKey: ['method-packages', applicationId], queryFn: api.methodPackages });
  // The exact revision's user methods, so a calculation can cite a ready method version instead of
  // falling back to the official package. Only loaded while the calculation dialog is open.
  const userMethods = useQuery({ queryKey: ['calculation-methods', applicationId, revisionId], queryFn: () => api.calculationMethods(applicationId, revisionId), enabled: calculationOpen && !!revisionId });
  const methodOptions = useMemo(
    () => selectedTask === 'mfa' ? [] : (userMethods.data ?? []).filter(method => method.purpose === selectedTask),
    [userMethods.data, selectedTask],
  );
  const methodDetailQuery = useQuery({
    queryKey: ['calculation-method-detail', selectedMethodId],
    queryFn: () => api.calculationMethod(selectedMethodId as string),
    enabled: calculationOpen && !!selectedMethodId,
  });
  const methodDetail = selectedMethodId ? methodDetailQuery.data ?? null : null;
  const methodVersions = methodDetail?.versions ?? [];
  // Choosing a different method (or reopening the dialog) drops any prior check, so a stale ref can
  // never be carried into a solve; the exact version must be re-checked each time.
  useEffect(() => { setCheckedRef(null); setValidation(null); setSelectedVersion(null); }, [selectedMethodId, calculationOpen]);
  useEffect(() => {
    if (selectedVersion != null || !methodVersions.length) return;
    const ordered = methodVersions.slice().sort((a, b) => b.version - a.version);
    setSelectedVersion(ordered[0]?.version ?? null);
  }, [methodVersions, selectedVersion]);
  // The explicit "check and use" step: validate the chosen exact version, and only on success freeze
  // it as the effective ref. A draft becomes ready through this same validation, so the detail is
  // refetched afterwards to refresh the version label.
  const checkAndUse = useMutation({
    mutationFn: () => api.validateCalculationMethodVersion(selectedMethodId as string, selectedVersion as number),
    onSuccess: result => {
      setValidation(result);
      if (result.valid && result.content_sha256) {
        setCheckedRef({ method_id: result.method_id, version: result.version, content_sha256: result.content_sha256 });
        client.invalidateQueries({ queryKey: ['calculation-method-detail', selectedMethodId] });
        client.invalidateQueries({ queryKey: ['calculation-methods', applicationId, revisionId] });
      } else setCheckedRef(null);
    },
  });
  const step = params.get('step') ?? 'data';
  const supportsPcf = workspace.data?.capabilities.includes('pcf.product.v1');
  const supportsCbam = workspace.data?.capabilities.includes('cbam.trial.v2');
  const cbamBlocked = workspace.data?.blocked_capabilities.some(item => item.capability === 'cbam.trial.v2');
  const calculationReady = packages.isSuccess;
  const inventoryReady = !!workspace.data?.native_inventory?.available;
  const supportsOrganizationLifecycle = workspace.data?.capabilities.includes('organization.lifecycle-carbon.v1');
  const organizationMethod = methodRefs.slice().reverse().map(ref => packages.data?.find(item => `${item.package_id}@${item.version}` === ref)).find(item => item?.package_kind === 'organization_lifecycle_carbon');
  const pcfMethod = methodRefs.slice().reverse().map(ref => packages.data?.find(item => `${item.package_id}@${item.version}` === ref))
    .find(item => item?.package_kind === 'product_carbon_footprint');
  const pcfClimateMethod = (pcfMethod?.manifest.formula_graph as { lcia_method?: string } | undefined)?.lcia_method;
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
    mutationFn: async (view: CalculationTask) => {
      let source = workspace.data;
      if (!source || !revision) throw new Error(t('workspace.saveBeforeCompute'));
      if (draftDirty || !source.saved) source = await formRef.current!.save();
      if (view === 'pcf' && !supportsPcf) throw new Error(t('workspace.needPcfMethod'));
      if (view === 'cbam' && (!supportsCbam || cbamBlocked)) throw new Error(t('workspace.cbamBoundaryUnreviewed'));
      // The product method projects the frozen native climate answer. Its source solve uses the
      // reviewed full-model LCA derivation; this template declares no separate PCF derivation.
      const purpose = purposeBound && (view === 'cbam' || view === 'organization' || (view === 'pcf' && returnedBound))
        ? (view === 'cbam' ? view : 'lca') : undefined;
      const nativeMfa = view === 'mfa' && Boolean(source.mapped_background_process_pins?.length) && inventoryReady;
      // A chosen user method is frozen against the exact version the operator checked-and-used, so a
      // concurrent save cannot silently move the basis under this run. The dialog only enables
      // calculation after a successful check; refuse rather than resolve some other version.
      let calculationMethodRef: CalculationMethodRef | undefined;
      if (selectedMethodId) {
        if (!checkedRef || checkedRef.method_id !== selectedMethodId || (selectedVersion != null && checkedRef.version !== selectedVersion))
          throw new Error(t('workspace.calcCheckHint'));
        calculationMethodRef = checkedRef;
      }
      const baseKey = await solveIdempotencyKey(view, source.revision_id, source.content_sha256, calculationMethodRef);
      activeSolveKey.current = baseKey;
      const retry = Number(localStorage.getItem(retryStorageKey(baseKey)) ?? 0);
      // One data version can be computed as several different tasks, and the climate total is a
      // different calculation basis from a projection, so each task keys its own run: sharing a
      // key would refuse the second task as a conflicting replay of the first. buildSolvePayload
      // is the single assembly point shared with the professional and scenario entry points.
      return api.solveAndFreeze(applicationId, source.revision_id, buildSolvePayload({
        demand: source.demand,
        backgroundProcessPins: source.background_process_pins ?? [],
        mappedBackgroundProcessPins: source.mapped_background_process_pins ?? [],
        projectBackgroundPins: source.project_background_pins,
        idempotencyKey: baseKey,
        retries: retry,
        task: view,
        calculationMethodRef,
        calculationPurpose: purpose,
        nativeBackgroundInventory: nativeMfa,
      }));
    },
    onSuccess: (snapshot, view) => { if (activeSolveKey.current) localStorage.removeItem(retryStorageKey(activeSolveKey.current)); activeSolveKey.current = null; client.setQueryData<SolvedSystemSnapshot[]>(['solved-snapshots', applicationId], previous => previous?.some(item => item.id === snapshot.id) ? previous : [...(previous ?? []), snapshot]); client.invalidateQueries({ queryKey: ['solved-snapshots', applicationId] }); client.invalidateQueries({ queryKey: ['application', applicationId] }); client.invalidateQueries({ queryKey: ['method-packages', applicationId] }); setCalculationOpen(false); navigate(view === 'organization' ? `/applications/${applicationId}/organization?snapshot=${snapshot.id}` : `/applications/${applicationId}/results?snapshot=${snapshot.id}&view=${view}`); },
    onError: () => { if (activeSolveKey.current) { const key = retryStorageKey(activeSolveKey.current); const previous = Number(localStorage.getItem(key) ?? 0); localStorage.setItem(key, String(Number.isSafeInteger(previous) && previous >= 0 ? previous + 1 : 1)); activeSolveKey.current = null; } },
  });
  const error = models.error || revisions.error || workspace.error;
  const retry = () => { models.refetch(); if (model) revisions.refetch(); if (revision) workspace.refetch(); };
  const badSelection = (models.isSuccess && !models.data.some(m => m.id === model)) || (revisions.isSuccess && !revision) || !['overview', 'data', 'background', 'reports'].includes(step);
  const choices = [
    { task: 'pcf', available: Boolean(supportsPcf && calculationReady), method: pcfClimateMethod },
    { task: 'cbam', available: Boolean(supportsCbam && calculationReady && !cbamBlocked), reason: cbamBlocked ? t('workspace.cbamBoundaryUnreviewed') : undefined },
    { task: 'organization', available: Boolean(supportsOrganizationLifecycle && organizationMethod && calculationReady), method: (organizationMethod?.manifest.formula_graph as { lcia_method?: string } | undefined)?.lcia_method },
    { task: 'mfa', available: Boolean(workspace.data?.capabilities.includes('mfa.solved.v1')) },
  ] as const;
  const beginCalculation = () => {
    const first = choices.find(choice => choice.available);
    setSelectedTask(first?.task ?? 'pcf');
    setSelectedMethodId(null);
    solve.reset();
    setCalculationOpen(true);
  };
  return <main className="app-page project-workspace-page">
    <div className="project-workspace-header">
    <PageHeader title={name} description="" />
    {historical ? <ReturnToProject applicationId={applicationId} /> : workspace.data && !badSelection ? <div className="project-header-actions">
      <Link className="arco-btn arco-btn-text project-history-button" to={`/applications/${applicationId}/history`}
        onClick={event => { if (saving || solve.isPending) event.preventDefault(); else if (draftDirty) { event.preventDefault(); setPendingLeave(event.currentTarget.getAttribute('href')); } }}>{t('workspace.history')}</Link>
      <Link className="arco-btn arco-btn-text project-methods-button" to={`/applications/${applicationId}/calculation-methods?model=${model}&revision=${revisionId}`}
        onClick={event => { if (saving || solve.isPending) event.preventDefault(); else if (draftDirty) { event.preventDefault(); setPendingLeave(event.currentTarget.getAttribute('href')); } }}>{t('cm.title')}</Link>
      <span className="project-save-status" role="status">{saving ? t('workspace.saving') : draftDirty ? t('workspace.unsaved') : workspace.data.saved ? t('workspace.saved') : ''}</span>
      <Button type="outline" disabled={saving || solve.isPending || (!draftDirty && workspace.data.saved)} loading={saving} onClick={() => { void formRef.current?.save().catch(() => undefined); }}>{t('workspace.saveProject')}</Button>
      <Button type="primary" loading={solve.isPending} disabled={saving || solve.isPending} onClick={beginCalculation}>{t('workspace.calculate')}</Button>
    </div> : null}
    </div>
    {error ? <ErrorState error={error} onRetry={retry} /> : badSelection ? <Alert type="error" content={t('workspace.badSelection')} action={<Button onClick={() => setParams({ step: 'data' })}>{t('workspace.clearSelection')}</Button>} /> : !workspace.data ? <LoadingState /> : historical ? <ReadOnlyProjectInventory workspace={workspace.data} /> : <>
      <ProjectDataForm key={revisionId} ref={formRef} workspace={workspace.data} hideFooterSave onReload={() => workspace.refetch()} onDirtyChange={setDraftDirty} onSaveStateChange={setSaving} onSaved={async (next, base) => { client.setQueryData(['workspace', applicationId, next.revision_id, lang], next); await Promise.all([client.invalidateQueries({ queryKey: ['revisions', model] }), client.invalidateQueries({ queryKey: ['application', applicationId] })]); if (resolvedRevisionRef.current !== base) return; setParams(prev => { const p = new URLSearchParams(prev); p.set('revision', next.revision_id); p.delete('step'); return p; }); }} />
      {returnedBound && cbamBlocked ? <Alert type="warning" content={t('workspace.cbamBoundaryUnreviewed')} action={<Button disabled={!workspace.data.saved || reviewCbam.isPending} loading={reviewCbam.isPending} onClick={() => reviewCbam.mutate()}>{t('workspace.applyCbamRules')}</Button>} /> : null}
      {reviewCbam.isError ? <ErrorState error={reviewCbam.error} /> : null}
    </>}
    <CalculationMethodDialog visible={calculationOpen} choices={[...choices]} selected={selectedTask}
      onSelect={task => { setSelectedTask(task); setSelectedMethodId(null); }}
      methodOptions={methodOptions} methodId={selectedMethodId} onMethodId={setSelectedMethodId}
      methodDetail={methodDetail} methodVersion={selectedVersion}
      onMethodVersion={version => { setSelectedVersion(version); setCheckedRef(null); setValidation(null); }}
      checkedRef={checkedRef} validation={validation} checking={checkAndUse.isPending}
      onCheckAndUse={() => checkAndUse.mutate()}
      workspace={workspace.data}
      dirty={draftDirty || !workspace.data?.saved} pending={solve.isPending || saving} error={solve.error}
      onCancel={() => { if (!solve.isPending && !saving) setCalculationOpen(false); }} onStart={() => solve.mutate(selectedTask)} />
    <Modal
      className="draft-switch-modal"
      title={t('workspace.draftTitle')}
      visible={!!pendingLeave}
      onCancel={() => setPendingLeave(null)}
      footer={<div className="form-actions">
        <Button onClick={() => setPendingLeave(null)}>{t('workspace.draftCancel')}</Button>
        <Button onClick={() => { clearProjectDraft(applicationId, revisionId); if (pendingLeave) navigate(pendingLeave); }}>{t('workspace.draftDiscard')}</Button>
        <Button type="primary" onClick={() => { if (pendingLeave) navigate(pendingLeave); }}>{t('workspace.draftKeep')}</Button>
      </div>}
    >{t('workspace.draftBody')}</Modal>
  </main>;
}
