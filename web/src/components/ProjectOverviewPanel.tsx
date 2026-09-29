import { Button } from '@arco-design/web-react';
import type { ProjectWorkspace } from '../api/types';
import { useI18n } from '../i18n';

export function ProjectOverviewPanel({ workspace, activeProcess, onStep }: {
  workspace: ProjectWorkspace; activeProcess?: string; onStep: (step: string, process?: string) => void;
}) {
  const { t, formatNumber } = useI18n();
  const processes = Array.from(new Set(workspace.fields.map(f => f.process)));
  // The data tab addresses a process by its template id, so the jump must carry the id, not the label.
  const processIds = new Map(workspace.fields.filter(f => f.process_id).map(f => [f.process, f.process_id!]));
  const ports = workspace.background_ports ?? [];
  const boundIds = new Set([...(workspace.background_process_pins ?? []), ...(workspace.mapped_background_process_pins ?? [])].map(p => p.consumer_exchange_id));
  const bound = ports.filter(p => boundIds.has(p.exchange_id));
  const actionable = ports.filter(p => !boundIds.has(p.exchange_id) && p.exact_binding_supported);
  const unmapped = ports.length - bound.length - actionable.length;
  const basis = workspace.fields.filter(f => f.reference_product);
  const process = (activeProcess ? workspace.fields.find(f => f.process_id === activeProcess)?.process : undefined) ?? processes[0];
  const next = !workspace.saved ? { step: 'data', label: t('overview.nextFill') }
    : actionable.length && workspace.inventory_editing ? { step: 'background', label: t('overview.nextBackground') }
      : { step: 'reports', label: t('overview.nextTask') };
  return <section className="section-panel">
    <p className="helper-text">{t('overview.intro')}</p>
    <dl className="project-status-list">
      <div className="project-status-row"><dt>{t('overview.dataStatus')}</dt><dd>{workspace.saved ? t('overview.saved') : t('overview.unsaved')}</dd></div>
      <div className="project-status-row"><dt>{t('overview.scope')}</dt><dd>{t('overview.scopeValue', { processes: processes.length, fields: workspace.fields.length })}</dd></div>
      {process ? <div className="project-status-row"><dt>{t('overview.currentProcess')}</dt><dd>{process}</dd></div> : null}
      <div className="project-status-row"><dt>{t('overview.basis')}</dt><dd>{basis.length
        ? <>{basis.map((f, index) => <span className="project-status-line" key={`${f.process}:${f.key}:${index}`}>{f.process} · {f.label} {formatNumber(f.value)} {f.unit}</span>)
          }<small className="inventory-linked">{t('overview.basisNote')}</small></>
        : t('overview.noReferenceProduct')}</dd></div>
      <div className="project-status-row"><dt>{t('overview.source')}</dt><dd>{workspace.source.trim() || t('overview.sourceEmpty')}</dd></div>
      {ports.length ? <div className="project-status-row"><dt>{t('overview.background')}</dt><dd>{t('overview.backgroundBound', { bound: bound.length, actionable: actionable.length })}{unmapped ? t('overview.backgroundUnmapped', { count: unmapped }) : ''}
        {actionable.length ? <small className="inventory-linked">{t('overview.backgroundPendingNote')}</small> : null}
        {unmapped ? <small className="inventory-linked">{t('overview.backgroundUnmappedNote')}</small> : null}
      </dd></div> : null}
    </dl>
    {processes.length ? <div className="project-process-rows">{processes.map(name => {
      const fields = workspace.fields.filter(f => f.process === name);
      const namePorts = ports.filter(p => p.process === name);
      const nameBound = namePorts.filter(p => boundIds.has(p.exchange_id)).length;
      const nameActionable = namePorts.filter(p => !boundIds.has(p.exchange_id) && p.exact_binding_supported).length;
      const nameUnmapped = namePorts.length - nameBound - nameActionable;
      return <div className="project-process-row" key={name}>
        <div className="project-process-row__text"><strong>{name}</strong>
          <small>{t('overview.processFields', { count: fields.length })}{namePorts.length
            ? `${t('overview.processInputs', { count: namePorts.length })}${nameActionable ? t('overview.processActionable', { count: nameActionable }) : ''}${nameUnmapped ? t('overview.processUnmapped', { count: nameUnmapped }) : ''}${nameBound === namePorts.length ? t('overview.processAllBound') : ''}`
            : ''}</small></div>
        <Button type="text" size="small" onClick={() => onStep('data', processIds.get(name))}>{t('overview.fillProcess')}</Button>
      </div>;
    })}</div> : null}
    <div className="form-actions"><Button type="primary" onClick={() => onStep(next.step)}>{next.label}</Button></div>
    <details className="project-version-details"><summary>{t('overview.technical')}</summary>
      <p>{workspace.template_title ?? t('overview.noTemplate')}</p>
      <p>{t('overview.revision', { id: workspace.revision_id })}</p>
      <p>{workspace.content_sha256}</p>
    </details>
  </section>;
}
