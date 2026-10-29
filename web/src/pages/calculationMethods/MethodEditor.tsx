import { Alert, Button, Dropdown, Input, Menu, Message, Modal, Select } from '@arco-design/web-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api, isCalculationMethodConflict } from '../../api/client';
import { useI18n } from '../../i18n';
import { ErrorState, LoadingState } from '../../components/ui/States';
import { IdentityPanel, ProcessingPackagesPanel, StaleDraftBanner, ValidationPanel, VersionHistoryPanel } from './MethodPanels';
import { useMethodDraft } from './useMethodDraft';
import { ScopePanel } from './ScopePanel';
import { TagSchemeEditor } from './TagSchemeEditor';
import { LegacyConversionDialog } from './LegacyConversionDialog';
import { ClassificationSuggestionPanel } from './ClassificationSuggestionPanel';
import { buildScopeRows, exchangeIdOf, modelPorts, overrideFor, type ScopeRow } from './flowRows';
import { MethodRun } from './MethodRun';
import { PURPOSES, purposeText, scopeText, statusText } from './labels';
import type { CalculationMethodRule, CalculationMethodValidation, CalculationMethodVersion, ClassificationSuggestion, MethodPurpose } from '../../api/types';

const EMPTY_VERSION = { id: '', method_id: '', version: 0, cbam_boundary_ref: null, content_sha256: null, status: 'draft', created_at: '', validated_at: null, rules: [] } satisfies CalculationMethodVersion;

export function MethodEditor({ applicationId, revisionId, revisionLabel, methodId, onBack, graph, templateMode = false }: {
  applicationId: string; revisionId: string; revisionLabel: string; methodId: string; onBack: () => void; graph?: Record<string, unknown>; templateMode?: boolean;
}) {
  const { t, lang } = useI18n();
  const [params, setParams] = useSearchParams();
  const queryClient = useQueryClient();
  const [modal, setModal] = useState<'identity' | 'clone' | 'history' | 'source' | 'check' | 'archive' | 'convert' | null>(null);
  const [trialOpen, setTrialOpen] = useState(false);
  const [comparingStale, setComparingStale] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const [validation, setValidation] = useState<CalculationMethodValidation | null>(null);
  const [cloneName, setCloneName] = useState('');
  const [clonePurpose, setClonePurpose] = useState<MethodPurpose>();
  const [suggestOpen, setSuggestOpen] = useState(false);
  const detail = useQuery({ queryKey: ['calculation-method', methodId], queryFn: () => api.calculationMethod(methodId) });
  const workspace = useQuery({ queryKey: ['workspace', applicationId, revisionId, lang], queryFn: () => api.workspace(applicationId, revisionId, lang), enabled: !graph });
  // The server owns the answer to "does this method have a processing package to choose at all";
  // the packages query is only issued once that answer is yes and the reader opens the diagnostic.
  const capabilities = useQuery({ queryKey: ['calculation-method-capabilities', methodId], queryFn: () => api.calculationMethodCapabilities(methodId) });
  const packages = useQuery({ queryKey: ['selectable-processing-packages', methodId], queryFn: () => api.selectableProcessingPackages(methodId),
    enabled: modal === 'source' && capabilities.data?.processing_package_selection === true && capabilities.data.tag_scheme !== true });
  const boundaries = useQuery({ queryKey: ['boundaries', applicationId], queryFn: () => api.boundaries(applicationId), enabled: modal === 'source' && detail.data?.method.purpose === 'cbam' });

  const versions = detail.data?.versions ?? [];
  const latestVersion = versions.find(item => item.version === detail.data?.latest_version);
  const requestedVersion = params.get('version');
  const resolvedVersion = requestedVersion === null ? detail.data?.latest_version : Number(requestedVersion);
  const invalidVersion = requestedVersion !== null && !versions.some(item => item.version === Number(requestedVersion));
  const version = versions.find(item => item.version === resolvedVersion);

  const isLatest = !!version && version.version === detail.data?.latest_version;
  const archived = detail.data?.method.status === 'retired';
  const semantics = (version ?? latestVersion)?.semantics;
  const isLegacyTag = semantics === 'flow_tag.v1';
  // A pre-caliber custom method (no semantics) is legacy as well: its Scope/boundary rules are
  // history, so it is read-only and convertible instead of opening the inclusion editor again.
  const isLegacyOrdinary = semantics == null && detail.data?.method.purpose === 'custom';
  const isLegacy = isLegacyTag || isLegacyOrdinary;
  const isResultCategory = semantics === 'result_category.v1';
  const isCaliber = isLegacyTag || isResultCategory;
  // A legacy scheme stays readable forever but is never edited in place; conversion is the only
  // forward path, and it creates an independent method.
  const canEdit = isLatest && !archived && !isLegacy;
  const archivable = isLatest && !archived;
  const draft = useMethodDraft(applicationId, revisionId, methodId, versions, latestVersion ?? EMPTY_VERSION, detail.data?.method.name ?? '', detail.data?.method.description ?? null);
  // Readable identities for the conversion draft, so a mapping is chosen per flow rather than by id.
  const flowLabels = useMemo(
    () => new Map(modelPorts(graph, workspace.data).map(port => [
      `${port.processId}::${port.portId}`,
      `${port.processName} / ${port.name}`,
    ])),
    [graph, workspace.data],
  );

  const save = useMutation({
    mutationFn: () => api.saveCalculationMethodVersion(methodId, draft.baseVersion, {
      name: draft.meta.name,
      description: draft.meta.description,
      cbam_boundary_ref: draft.meta.cbam_boundary_ref,
      rules: draft.rules,
      reporting_dimensions: draft.dimensions,
      model_processing_rules_ref: draft.processingRef,
      semantics: latestVersion?.semantics ?? undefined,
      expected_content_sha256: draft.baseContentSha256,
    }),
    onSuccess: () => {
      setConflict(false);
      draft.reloadFromServer();
      queryClient.invalidateQueries({ queryKey: ['calculation-method', methodId] });
      queryClient.invalidateQueries({ queryKey: ['calculation-methods'] });
      queryClient.invalidateQueries({ queryKey: ['template-accounting-methods'] });
      Message.success(t('cm.saved'));
    },
    onError: error => setConflict(isCalculationMethodConflict(error)),
  });

  const clone = useMutation({
    mutationFn: () => api.cloneCalculationMethod(methodId, version?.version ?? draft.baseVersion, {
      name: cloneName.trim() || `${detail.data?.method.name ?? ''} · ${t('cm.cloneSuffix')}`,
      purpose: isCaliber ? 'custom' : (clonePurpose ?? detail.data!.method.purpose as MethodPurpose),
      model_revision_id: revisionId,
    }),
    onSuccess: created => {
      setModal(null);
      queryClient.invalidateQueries({ queryKey: ['calculation-method', methodId] });
      queryClient.invalidateQueries({ queryKey: ['calculation-methods'] });
      queryClient.invalidateQueries({ queryKey: ['template-accounting-methods'] });
      setParams(previous => { const next = new URLSearchParams(previous); next.set('method', created.method.id); next.delete('version'); return next; });
    },
  });

  const archive = useMutation({
    mutationFn: () => api.archiveCalculationMethod(methodId),
    onSuccess: () => {
      setModal(null);
      queryClient.invalidateQueries({ queryKey: ['calculation-method', methodId] });
      queryClient.invalidateQueries({ queryKey: ['calculation-method-capabilities', methodId] });
      queryClient.invalidateQueries({ queryKey: ['calculation-methods'] });
      Message.success(t('cm.archiveDone'));
    },
  });

  const validate = useMutation({
    mutationFn: () => api.validateCalculationMethodVersion(methodId, version?.version ?? detail.data?.latest_version ?? 0),
    onSuccess: result => {
      setValidation(result);
      queryClient.invalidateQueries({ queryKey: ['calculation-method', methodId] });
      queryClient.invalidateQueries({ queryKey: ['calculation-methods'] });
      queryClient.invalidateQueries({ queryKey: ['template-accounting-methods'] });
    },
  });

  // A new head version or an unsaved draft invalidates any prior validation result: the check
  // only ever describes the persisted version it was run against.
  useEffect(() => { setValidation(null); }, [methodId, resolvedVersion, detail.data?.latest_version, draft.dirty]);

  // Leaving with unsaved rule edits is the reader's choice, not a silent navigation. The overlay
  // survives in storage either way; discarding it here is the only path that actually throws it away.
  const unsaved = isLatest && draft.dirty;
  useEffect(() => {
    if (!unsaved) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [unsaved]);

  if (detail.error) return <ErrorState error={detail.error} onRetry={() => detail.refetch()} />;
  if (detail.isLoading) return <LoadingState />;
  if (!detail.data || !latestVersion || invalidVersion || !version) {
    return <ErrorState error={Object.assign(new Error(t('cm.notFound')), { name: 'VersionNotFound' })}
      onRetry={() => setParams(previous => { const next = new URLSearchParams(previous); next.delete('version'); return next; })} />;
  }

  /** Editing a row that has no rule of its own creates exactly one per-flow override, starting from
   * the process default it inherited; an existing rule is patched in place. */
  const editRow = (row: ScopeRow, patch: Partial<CalculationMethodRule>) => {
    if (row.rule) { draft.updateRule(row.identity, patch); return; }
    draft.addRule({ ...overrideFor(row, draft.rules), ...patch });
  };
  /** Fold confirmed suggestions into the draft. Each suggestion is located against the same ports the
   * scope editor draws, so applying one writes exactly the per-flow override an equivalent manual edit
   * would; a suggestion with no proposed rule (pending, not applicable, already decided) is skipped, so
   * a rule the reader set by hand is never overwritten. */
  const applySuggestions = (selected: ClassificationSuggestion[]) => {
    const actionable = selected.filter(item => item.suggested);
    if (!actionable.length) return 0;
    const ports = modelPorts(graph, workspace.data);
    const rowsByExchange = new Map<string, ScopeRow>();
    for (const processId of new Set(actionable.map(item => item.exchange_id.split('::')[0]))) {
      for (const row of buildScopeRows(processId, draft.rules, ports)) {
        if (row.portId) rowsByExchange.set(exchangeIdOf({ processId: row.processId, portId: row.portId }), row);
      }
    }
    let applied = 0;
    for (const item of actionable) {
      const row = rowsByExchange.get(item.exchange_id);
      const suggested = item.suggested;
      if (!row || !suggested) continue;
      editRow(row, {
        boundary_status: suggested.boundary_status,
        location_role: suggested.location_role,
        scope: suggested.scope,
      });
      applied += 1;
    }
    return applied;
  };
  const visibleRules = canEdit ? draft.rules : version.rules;
  const visibleDimensions = canEdit ? draft.dimensions : version.reporting_dimensions ?? [];
  const scopePanel = () => <ScopePanel graph={graph} workspace={workspace.data}
    loading={!graph && workspace.isLoading} error={graph ? null : workspace.error} editable={canEdit}
    rules={visibleRules} dimensions={visibleDimensions} onDimensions={draft.setDimensions}
    onEdit={editRow} onRemove={row => draft.removeRule(row.identity)} />;
  const tagPanel = () => <TagSchemeEditor graph={graph} workspace={workspace.data}
    loading={!graph && workspace.isLoading} error={graph ? null : workspace.error} editable={canEdit} legacy={isLegacy}
    rules={visibleRules} dimensions={visibleDimensions} onDimensions={draft.setDimensions}
    addRule={draft.addRule} updateRule={draft.updateRule} removeRule={draft.removeRule} />;
  const openModal = (kind: 'identity' | 'clone' | 'history' | 'source' | 'check' | 'archive') => {
    if (kind === 'clone') setCloneName(`${detail.data.method.name} · ${t('cm.cloneSuffix')}`);
    if (kind === 'archive') archive.reset();
    setModal(kind);
  };
  const capabilityReason = capabilities.data?.processing_package_reason ?? null;

  return <div className="calculation-method-editor">
    <div className="calculation-method-editor__bar">
      <Button className="calculation-method-editor__back" type="text" size="small"
        onClick={() => (unsaved ? setLeaving(true) : onBack())}><span aria-hidden="true">‹ </span>{t('cm.backToCategories')}</Button>
      <div className="calculation-method-editor__identity">
        <strong>{detail.data.method.name}{isLegacy
          ? <span className="calculation-method-editor__badge">{isLegacyTag ? t('cm.typeLegacyTag') : t('cm.typeLegacyMethod')}</span>
          : null}</strong>
        <span>{revisionLabel} · {purposeText(t, detail.data.method.purpose)} · v{version.version} · {statusText(t, version.status)}</span>
      </div>
      <span className={`calculation-method-editor__state${draft.dirty ? ' is-dirty' : ''}`}>
        {canEdit ? (draft.dirty ? t('cm.dirtyTitle') : t('cm.savedState')) : t('cm.readOnly')}
      </span>
      <Button onClick={() => openModal('check')}>{t('cm.moreCheck')}</Button>
      <Dropdown trigger="click" position="br" droplist={<Menu onClickMenuItem={key => {
        if (key === 'suggest') { setSuggestOpen(true); return; }
        openModal(key as 'identity' | 'clone' | 'history' | 'source' | 'archive');
      }}>
        {!isLegacy ? <Menu.Item key="identity">{t('cm.moreIdentity')}</Menu.Item> : null}
        {!isLegacy ? <Menu.Item key="clone">{t('cm.moreClone')}</Menu.Item> : null}
        <Menu.Item key="history">{t('cm.moreHistory')}</Menu.Item>
        <Menu.Item key="source">{t('cm.moreSource')}</Menu.Item>
        {!isCaliber && canEdit ? <Menu.Item key="suggest">{t('cm.moreSuggest')}</Menu.Item> : null}
        <Menu.Item key="archive" disabled={!archivable}>{t('cm.moreArchive')}</Menu.Item>
      </Menu>}>
        <Button>{t('cm.more')}</Button>
      </Dropdown>
      {canEdit ? <Button type="primary" onClick={() => save.mutate()} loading={save.isPending} disabled={!draft.dirty}>{t('cm.save')}</Button> : null}
    </div>
    {archived ? <Alert type="info" showIcon content={t('cm.archivedNote')} /> : null}
    {isLegacy && !archived ? <div className="calculation-method-editor__legacy">
      <Alert type="info" showIcon content={<div className="calculation-method-editor__legacy-body">
        <p>{isLegacyTag ? t('cm.legacyReadOnlyBody') : t('cm.legacyMethodReadOnlyBody')}</p>
        <Button size="small" type="primary" onClick={() => setModal('convert')}>{t('cm.convertAction')}</Button>
      </div>} />
    </div> : null}
    {canEdit && draft.dirty ? <div className="calculation-method-editor__actions">
      <Button type="text" onClick={draft.reloadFromServer}>{t('cm.discard')}</Button>
    </div> : null}
    {canEdit && draft.stale ? <StaleDraftBanner stale={draft.stale} comparing={comparingStale}
      onCompareToggle={() => setComparingStale(value => !value)}
      onMigrate={() => { draft.migrateStale(); setComparingStale(false); }}
      onDiscard={() => { draft.discardStale(); setComparingStale(false); }} /> : null}
    {conflict ? <Alert type="warning" showIcon content={<div>
      <strong>{t('cm.conflictTitle')}</strong>
      <p>{t('cm.conflictBody')}</p>
      <Button size="mini" type="primary" onClick={() => { setConflict(false); queryClient.invalidateQueries({ queryKey: ['calculation-method', methodId] }); }}>{t('cm.reloadLatest')}</Button>
    </div>} /> : null}
    {save.isError && !conflict ? <ErrorState error={save.error} onRetry={() => save.mutate()} /> : null}
    {isLegacyOrdinary ? <LegacyMethodPanel version={version} /> : isCaliber ? tagPanel() : scopePanel()}
    <Modal className="draft-switch-modal" title={t('cm.leaveTitle')} visible={leaving} style={{ maxWidth: 'calc(100vw - 32px)' }}
      onCancel={() => setLeaving(false)}
      footer={<div className="form-actions">
        <Button onClick={() => setLeaving(false)}>{t('workspace.draftCancel')}</Button>
        <Button onClick={() => { draft.reloadFromServer(); setLeaving(false); onBack(); }}>{t('workspace.draftDiscard')}</Button>
        <Button type="primary" onClick={() => { setLeaving(false); onBack(); }}>{t('workspace.draftKeep')}</Button>
      </div>}>{t('cm.leaveBody')}</Modal>
    <Modal title={t('cm.moreIdentity')} visible={modal === 'identity'} onCancel={() => setModal(null)} style={{ width: 560, maxWidth: 'calc(100vw - 32px)' }}
      footer={<div className="form-actions">
        <Button onClick={() => setModal(null)}>{t('cm.tagClose')}</Button>
        {canEdit ? <Button type="primary" onClick={() => { setModal(null); save.mutate(); }}>{t('cm.identityApply')}</Button> : null}
      </div>}>
      <IdentityPanel method={detail.data.method} version={version} editable={canEdit} meta={draft.meta} onMeta={draft.setMeta} />
    </Modal>
    <Modal title={t('cm.moreClone')} visible={modal === 'clone'} onCancel={() => setModal(null)} style={{ maxWidth: 'calc(100vw - 32px)' }}
      footer={<div className="form-actions">
        <Button onClick={() => setModal(null)}>{t('workspace.draftCancel')}</Button>
        <Button type="primary" loading={clone.isPending} disabled={!cloneName.trim() || unsaved} onClick={() => clone.mutate()}>{t('cm.cloneSubmit')}</Button>
      </div>}>
      <div className="calculation-method-form">
        {unsaved ? <p className="helper-text">{t('cm.dirtyTitle')} · {t('cm.save')}</p> : null}
        <label className="project-field"><span>{t('cm.cloneName')}</span>
          <Input value={cloneName} onChange={setCloneName} maxLength={255} /></label>
        <label className="project-field"><span>{t('cm.clonePurpose')}</span>
          <Select aria-label={t('cm.clonePurpose')} value={isCaliber ? 'custom' : clonePurpose ?? detail.data.method.purpose}
            disabled={isCaliber} style={{ width: 200 }} options={PURPOSES.map(value => ({ value, label: purposeText(t, value) }))}
            onChange={value => setClonePurpose(value as MethodPurpose)} /></label>
        {clone.isError ? <Alert type="error" showIcon content={t('cm.cloneFailed')} /> : null}
      </div>
    </Modal>
    <Modal title={t('cm.historyTitle')} visible={modal === 'history'} onCancel={() => setModal(null)} style={{ width: 760, maxWidth: 'calc(100vw - 32px)' }}
      footer={<Button onClick={() => setModal(null)}>{t('cm.tagClose')}</Button>}>
      <VersionHistoryPanel versions={versions} currentVersion={version.version} onView={next => {
        setModal(null);
        setParams(previous => {
          const params = new URLSearchParams(previous);
          if (next === detail.data.latest_version) params.delete('version'); else params.set('version', String(next));
          return params;
        }, { replace: true });
      }} />
    </Modal>
    <Modal title={t('cm.sourceTitle')} visible={modal === 'source'} onCancel={() => setModal(null)} style={{ width: 720, maxWidth: 'calc(100vw - 32px)' }}
      footer={<Button onClick={() => setModal(null)}>{t('cm.tagClose')}</Button>}>
      <div className="calculation-method-source">
        <dl className="calculation-method-source__facts">
          <div><dt>{t('cm.sourceModelRevision')}</dt><dd>{revisionLabel}</dd></div>
          <div><dt>{t('cm.identityPurpose')}</dt><dd>{purposeText(t, detail.data.method.purpose)}</dd></div>
          <div><dt>{t('cm.sourceSemantics')}</dt><dd>{isLegacyTag ? t('cm.typeLegacyTag') : isLegacyOrdinary ? t('cm.typeLegacyMethod') : isResultCategory ? t('cm.typeResultCategory') : t('cm.typeMethod')}</dd></div>
          <div><dt>{t('cm.sourceHeadStatus')}</dt><dd>v{detail.data.method.latest_version ?? '—'} · {detail.data.method.latest_status ? statusText(t, detail.data.method.latest_status) : '—'}</dd></div>
          <div><dt>{t('cm.sourceCapability')}</dt><dd>{capabilities.data?.processing_package_selection ? t('cm.sourceCapabilityYes') : t('cm.sourceCapabilityNo')}</dd></div>
        </dl>
        {isCaliber ? <p className="helper-text">{t('cm.sourceTagNoPackage')}</p> : null}
        {!isCaliber && capabilities.error ? <ErrorState error={capabilities.error} onRetry={() => capabilities.refetch()} /> : null}
        {!isCaliber && capabilities.isLoading ? <LoadingState /> : null}
        {!isCaliber && capabilities.data ? (capabilities.data.processing_package_selection
          ? <ProcessingPackagesPanel options={packages.data ?? []} loading={packages.isLoading} error={packages.error}
              currentRef={isLatest ? draft.processingRef : version.model_processing_rules_ref ?? null} editable={canEdit} onChange={draft.setProcessingRef} />
          : <Alert type="info" showIcon content={<div>
              <p>{t('cm.sourcePackageUnavailable')}</p>
              {capabilityReason ? <p className="helper-text">{t('cm.sourcePackageDiagnostic')}：<code>{capabilityReason.code}</code> · {capabilityReason.message}</p> : null}
            </div>} />) : null}
        {detail.data.method.purpose === 'cbam' ? <div className="project-field"><span>{t('cm.boundarySelect')}</span>
          <Select aria-label={t('cm.boundarySelect')} disabled={!canEdit} value={(isLatest ? draft.meta.cbam_boundary_ref : version.cbam_boundary_ref) ?? undefined}
            options={boundaries.data?.filter(item => item.status === 'frozen' && item.boundary_type === 'cbam_trial').map(item => ({ value: item.id, label: t('tm.frozenBoundaryOption', { processes: item.included_process_ids.length, rules: item.included_flow_rules.length }) }))}
            onChange={value => draft.setMeta({ cbam_boundary_ref: value })} />
          {boundaries.error ? <ErrorState error={boundaries.error} /> : null}
        </div> : null}
        <details className="frozen-input-identity"><summary>{t('cm.reviewContent')}</summary>
          <pre className="audit-json">{JSON.stringify({
            origin_method_id: detail.data.method.origin_method_id,
            origin_method_version: detail.data.method.origin_method_version ?? null,
            origin_content_sha256: detail.data.method.origin_content_sha256 ?? null,
            model_revision_id: detail.data.method.model_revision_id,
            version: version.version,
            content_sha256: version.content_sha256,
            semantics: version.semantics ?? null,
            latest_content_sha256: detail.data.method.latest_content_sha256 ?? null,
          }, null, 2)}</pre>
        </details>
      </div>
    </Modal>
    <Modal title={t('cm.checkTitle')} visible={modal === 'check'} onCancel={() => setModal(null)} style={{ width: 640, maxWidth: 'calc(100vw - 32px)' }}
      footer={<div className="form-actions">
        {version.status === 'ready' && !isCaliber ? <Button onClick={() => { setModal(null); setTrialOpen(true); }}>{t('cm.moreTrial')}</Button> : null}
        {version.status === 'ready' && isCaliber && !templateMode ? <Link className="arco-btn arco-btn-primary" to={`/applications/${applicationId}/results?revision=${revisionId}&view=pcf`}>{t('cm.tagViewResults')}</Link> : null}
        <Button onClick={() => setModal(null)}>{t('cm.tagClose')}</Button>
      </div>}>
      <ValidationPanel validation={validation} validating={validate.isPending} canValidate={canEdit}
        draftDirty={draft.dirty} onValidate={() => validate.mutate()} />
      {validate.error ? <ErrorState error={validate.error} onRetry={() => validate.mutate()} /> : null}
      {isCaliber && templateMode && version.status === 'ready' ? <p>{t('cm.tagTemplateNext')}</p> : null}
    </Modal>
    <Modal title={t('cm.trialTitle')} visible={trialOpen} onCancel={() => setTrialOpen(false)} style={{ width: 640, maxWidth: 'calc(100vw - 32px)' }}
      footer={<Button onClick={() => setTrialOpen(false)}>{t('cm.tagClose')}</Button>}>
      <MethodRun applicationId={applicationId} revisionId={revisionId} graph={graph}
        purpose={detail.data.method.purpose} version={version} dirty={draft.dirty} />
    </Modal>
    <Modal title={t('cm.archiveTitle')} visible={modal === 'archive'} onCancel={() => setModal(null)} style={{ maxWidth: 'calc(100vw - 32px)' }}
      footer={<div className="form-actions">
        <Button onClick={() => setModal(null)}>{t('workspace.draftCancel')}</Button>
        <Button status="danger" loading={archive.isPending} onClick={() => archive.mutate()}>{t('cm.archiveConfirm')}</Button>
      </div>}>
      <p>{t('cm.archiveBody')}</p>
      {archive.isError ? <Alert type="error" showIcon content={t('cm.archiveFailed')} /> : null}
    </Modal>
    {modal === 'convert' ? <LegacyConversionDialog methodId={methodId} version={version.version}
      methodName={detail.data.method.name}
      flowLabel={(rule, index) => flowLabels.get(rule.exchange_id ?? '') ?? t('cm.convertRuleFallback', { index: index + 1 })}
      onClose={() => setModal(null)}
      onConverted={id => {
        setModal(null);
        queryClient.invalidateQueries({ queryKey: ['calculation-method', methodId] });
        queryClient.invalidateQueries({ queryKey: ['calculation-methods'] });
        setParams(previous => { const next = new URLSearchParams(previous); next.set('method', id); next.delete('version'); return next; });
      }} /> : null}
    <ClassificationSuggestionPanel methodId={methodId} version={detail.data.latest_version}
      visible={suggestOpen && isLatest} onClose={() => setSuggestOpen(false)}
      onApply={selected => {
        const applied = applySuggestions(selected);
        setSuggestOpen(false);
        if (applied) Message.success(t('cm.suggest.applied', { count: applied }));
      }} />
  </div>;
}

/** What a legacy ordinary method still says, as history. No toggle, no Scope editor: its only
 * forward path is conversion, so the reader is never offered a second meaning for the same flow. */
function LegacyMethodPanel({ version }: { version: CalculationMethodVersion }) {
  const { t } = useI18n();
  const counts = { selected: 0, excluded: 0, pending: 0 };
  const scopes = new Map<string, number>();
  for (const rule of version.rules) {
    if (rule.boundary_status === 'excluded') counts.excluded += 1;
    else if (rule.boundary_status === 'pending') counts.pending += 1;
    else counts.selected += 1;
    if (rule.scope) scopes.set(rule.scope, (scopes.get(rule.scope) ?? 0) + 1);
  }
  return <section className="section-panel legacy-method-panel">
    <h2>{t('cm.legacyMethodTitle')}</h2>
    <p className="helper-text">{t('cm.legacyMethodBody')}</p>
    <dl className="legacy-conversion__counts">
      <div><dt>{t('cm.boundary.selected')}</dt><dd>{counts.selected}</dd></div>
      <div><dt>{t('cm.boundary.excluded')}</dt><dd>{counts.excluded}</dd></div>
      <div><dt>{t('cm.boundary.pending')}</dt><dd>{counts.pending}</dd></div>
    </dl>
    {scopes.size ? <div className="legacy-conversion__categories">
      <span className="legacy-conversion__label">{t('cm.legacyMethodScopes')}</span>
      {[...scopes.entries()].map(([scope, count]) =>
        <span className="tag-scheme__chip" key={scope}>{scopeText(t, scope)} · {count}</span>)}
    </div> : null}
  </section>;
}
