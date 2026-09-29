import { Alert, Button, InputNumber } from '@arco-design/web-react';
import { useMutation } from '@tanstack/react-query';
import { forwardRef, useEffect, useImperativeHandle, useState } from 'react';
import { api, isStaleDataVersion } from '../api/client';
import type { ProjectWorkspace } from '../api/types';
import { useI18n } from '../i18n';
import { carryProjectDraft, draftDiffers, projectDraftKey } from './projectDraft';
import { ErrorState } from './ui/States';
import { ProcessInventoryTable } from './ProcessInventoryTable';
import { BackgroundEditDialog } from './BackgroundEditDialog';
import { ProcessGraph } from './ProcessGraph';

export interface ProjectDataFormHandle {
  save: () => Promise<ProjectWorkspace>;
}

export const ProjectDataForm = forwardRef<ProjectDataFormHandle, { workspace: ProjectWorkspace; onSaved: (workspace: ProjectWorkspace, baseRevisionId: string) => void; onReload: () => void; onDirtyChange?: (dirty: boolean) => void; onSaveStateChange?: (saving: boolean) => void; hideFooterSave?: boolean }>(function ProjectDataForm({ workspace, onSaved, onReload, onDirtyChange, onSaveStateChange, hideFooterSave = false }, ref) {
  const { t, formatNumber, lang } = useI18n();
  const draftKey = projectDraftKey(workspace.application_id, workspace.revision_id);
  const initial = { amounts: workspace.demand.map(d => d.amount), values: Object.fromEntries(workspace.fields.map(f => [f.key, f.value])), source: workspace.source };
  const [draft, setDraft] = useState<typeof initial>(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(draftKey) ?? 'null');
      return saved && Array.isArray(saved.amounts) && saved.values && typeof saved.source === 'string' ? saved : initial;
    } catch { return initial; }
  });
  const update = (next: typeof draft) => { setDraft(next); localStorage.setItem(draftKey, JSON.stringify(next)); };
  const [bgTarget, setBgTarget] = useState<string>();
  const dirty = draftDiffers(draft, initial);
  useEffect(() => { onDirtyChange?.(dirty); }, [dirty]);
  const referenceFields = workspace.demand.map(d => {
    const matches = workspace.fields.filter(f => f.group === 'outputs' && f.reference_product && f.flow_uuid === d.reference_flow_uuid && f.unit === d.unit);
    return matches.length === 1 ? matches[0] : undefined;
  });
  const linkedDemand = workspace.inventory_editing && referenceFields.every(Boolean);
  // The solve demand follows the entered product output. A version saved while the demand was set
  // by hand keeps showing its own numbers, so opening an older project cannot restate its batch.
  const keepExplicitDemand = !linkedDemand || (workspace.saved && workspace.demand_mode === 'explicit');
  const effectiveAmounts = keepExplicitDemand ? draft.amounts : referenceFields.map(f => draft.values[f!.key]);
  const save = useMutation({
    mutationFn: () => api.saveProjectInputs(workspace.application_id, { revision_id: workspace.revision_id, expected_content_sha256: workspace.content_sha256, ...draft,
      amounts: effectiveAmounts,
      ...(linkedDemand ? { demand_mode: keepExplicitDemand ? 'explicit' as const : 'reference_output' as const } : {}) }, lang),
    onSuccess: next => { localStorage.removeItem(draftKey); onSaved(next, workspace.revision_id); },
  });
  const isInvalid = (key: string, referenceProduct?: boolean) => {
    const value = draft.values[key];
    return !Number.isFinite(value) || (referenceProduct ? value <= 0 : value < 0);
  };
  const blockers = [
    effectiveAmounts.length !== workspace.demand.length || effectiveAmounts.some(v => !Number.isFinite(v) || v <= 0) ? t('form.blockerOutput') : null,
    workspace.fields.some(f => isInvalid(f.key, f.reference_product)) ? t('form.blockerFields') : null,
  ].filter((reason): reason is string => !!reason);
  const ready = !blockers.length;
  useImperativeHandle(ref, () => ({ save: () => {
    if (!ready) return Promise.reject(new Error(t('form.blockers', { reasons: blockers.join(' · ') })));
    if (save.isPending) return Promise.reject(new Error(t('workspace.saving')));
    return save.mutateAsync();
  } }));
  useEffect(() => { onSaveStateChange?.(save.isPending); }, [save.isPending, onSaveStateChange]);
  const productOutput = (amounts: (number | undefined)[]) => workspace.demand.map((d, i) =>
    t('form.productOutput', { amount: formatNumber(amounts[i]), unit: d.unit })).join('、');
  return <section className="section-panel project-data-form">
    <div className="project-data-intro">
    <div className="project-form-heading">{keepExplicitDemand ? null : <p className="helper-text">{productOutput(effectiveAmounts)}</p>}</div>
    {keepExplicitDemand ? <div className="project-scale-fields">{workspace.demand.map((d, index) => <label className="project-field" key={d.reference_flow_uuid}><span>{t('form.demandLabel', { index: workspace.demand.length > 1 ? ` ${index + 1}` : '' })}</span><InputNumber suffix={d.unit} aria-label={t('form.demandAria', { index: index + 1 })} value={draft.amounts[index]} min={Number.EPSILON} disabled={save.isPending} onChange={value => update({ ...draft, amounts: draft.amounts.map((old, i) => i === index ? value : old) })} /></label>)}</div> : null}
    </div>
    {!workspace.saved ? <Alert type="info" content={t('form.exampleData')} /> : null}
    {workspace.inventory_editing ? <>
      {workspace.process_graph?.nodes.length ? <ProcessGraph graph={workspace.process_graph} /> : null}
      <ProcessInventoryTable fields={workspace.fields} values={draft.values} disabled={save.isPending} onChange={(key, value) => update({...draft, values: {...draft.values, [key]: value}})} workspace={workspace} onEditBackground={setBgTarget} hasGraph={Boolean(workspace.process_graph?.nodes.length)} />
      {bgTarget ? <BackgroundEditDialog workspace={workspace} exchangeId={bgTarget} onClose={() => setBgTarget(undefined)} onSaved={next => { carryProjectDraft(workspace.application_id, workspace.revision_id, next.revision_id); onSaved(next, workspace.revision_id); }} onReload={onReload} /> : null}
    </> : workspace.fields.length ? <div className="project-process-section"><h3>{t('form.processSection')}</h3><p className="helper-text">{t('form.processSectionHint')}</p><div className="project-process-grid">{Array.from(new Set(workspace.fields.map(f => f.process))).map(process => <fieldset className="project-process-group" key={process}><legend>{process}</legend>{workspace.fields.filter(f => f.process === process).map(field => <label className="project-field" key={field.key}><span>{field.label}</span><InputNumber suffix={field.unit} aria-label={field.label} value={draft.values[field.key]} min={0} disabled={save.isPending} onChange={value => update({ ...draft, values: { ...draft.values, [field.key]: value } })} /></label>)}</fieldset>)}</div></div> : <p className="helper-text">{t('form.noParams')}</p>}
    {save.isError ? <ErrorState error={save.error} onRetry={isStaleDataVersion(save.error) ? onReload : undefined} /> : null}
    <div className="form-actions"><Button disabled={save.isPending} onClick={() => update(initial)}>{t('form.restore')}</Button>{!hideFooterSave ? <Button type="primary" disabled={!ready || save.isPending} loading={save.isPending} onClick={() => save.mutate()}>{t('form.save')}</Button> : null}</div>
    {!ready && !save.isPending ? <p className="helper-text" role="status">{t('form.blockers', { reasons: blockers.join(' · ') })}</p> : null}
    {dirty ? <p className="helper-text">{t('form.draftSaved')}</p> : null}
  </section>;
});
