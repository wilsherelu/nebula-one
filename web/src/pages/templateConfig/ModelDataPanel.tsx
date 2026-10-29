import { Button } from '@arco-design/web-react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { useI18n } from '../../i18n';
import { StatusBadge } from '../../components/ui/StatusBadge';
import type { TemplateAccountingMethod, TemplateAccountingMethods } from '../../api/templateMethods';

export function ModelDataPanel({ data, onEditModel, editing, onViewIndicator }: {
  data: TemplateAccountingMethods;
  onEditModel: () => void;
  editing: boolean;
  onViewIndicator: (scheme: TemplateAccountingMethod) => void;
}) {
  const { t } = useI18n();
  const template = data.template;
  const revisions = useQuery({
    queryKey: ['revisions', template.source_model_id],
    queryFn: () => api.revisions(template.source_model_id),
  });
  // The default LCIA is a calculation setting, not a rule: it lives here, and the project entry
  // runs it with no user rule. Prefer the task's declared default, else the first scheme that
  // actually carries a characterization.
  const completeTask = data.tasks?.find(task => task.role === 'complete_model');
  const byKey = new Map(data.methods.map(method => [method.method_key, method]));
  const declaredDefault = completeTask?.default_ref;
  const indicator = declaredDefault
    ? byKey.get(declaredDefault) ?? byKey.get(`official:${declaredDefault}`)
    : data.methods.find(method => typeof method.package_detail?.formula_graph.lcia_method === 'string');
  const formula = indicator?.package_detail?.formula_graph;
  const indicatorMethod = typeof formula?.lcia_method === 'string' ? formula.lcia_method : null;
  const indicatorUnit = typeof formula?.result_unit === 'string' ? formula.result_unit : null;
  return <div className="stack">
    {indicator ? <section className="section-panel template-indicator">
      <h2>{t('tm.model.indicatorTitle')}</h2>
      <p className="helper-text">{t('tm.model.indicatorHint')}</p>
      <dl className="template-facts">
        <dt>{t('tm.indicator.method')}</dt><dd>{indicatorMethod ?? t('tm.indicator.unavailable')}</dd>
        <dt>{t('tm.indicator.unit')}</dt><dd>{indicatorUnit ?? t('tm.indicator.unavailable')}</dd>
      </dl>
      <div className="inline-actions">
        <Button size="small" onClick={() => onViewIndicator(indicator)}>{t('tm.model.viewSource')}</Button>
      </div>
    </section> : null}
    <section className="section-panel">
      <h2>{t('tm.modelFacts')}</h2>
      <dl className="template-facts">
        <dt>{t('tm.modelScale')}</dt>
        <dd>{t('templates.summary', { processes: template.model.process_count, fields: template.model.port_count })}</dd>
        <dt>{t('tm.templateVersion')}</dt>
        <dd>{template.version}</dd>
        <dt>{t('tm.templateKind')}</dt>
        <dd>{t(template.official ? 'tm.officialTemplate' : 'tm.userTemplate')}</dd>
      </dl>
      <div className="inline-actions">
        <Button type="primary" loading={editing} disabled={!template.source_model_id} onClick={onEditModel}>
          {t('tm.editInModeling')}
        </Button>
      </div>
      <p className="helper-text">{t('tm.editInModelingHint')}</p>
    </section>
    <details className="section-panel">
      <summary>{t('tm.sourceDetail')}</summary>
      <dl className="template-facts">
        <dt>{t('tm.templateHash')}</dt>
        <dd><code>{template.template_sha256}</code></dd>
        <dt>{t('tm.modelGraphHash')}</dt>
        <dd><code>{template.model.graph_sha256}</code> ({template.model.graph_basis})</dd>
        <dt>{t('tm.sourceIds')}</dt>
        <dd><code>{template.source_application_id}</code> / <code>{template.source_model_id}</code> / <code>{template.source_revision_id}</code></dd>
        {template.template_profile ? <>
          <dt>{t('tm.templateProfile')}</dt>
          <dd>{template.template_profile.id}@{template.template_profile.version} <code>{template.template_profile.content_sha256}</code></dd>
        </> : null}
        <dt>{t('tm.capabilities')}</dt>
        <dd>{template.capabilities.join(', ') || t('state.notRecorded')}</dd>
        {template.method_package_refs.length ? <>
          <dt>{t('tm.boundPackages')}</dt>
          <dd><ul>{template.method_package_refs.map(ref => <li key={ref}><code>{ref}</code>
            {template.method_pins?.[ref] ? <span className="helper-text">{template.method_pins[ref]}</span> : null}</li>)}</ul></dd>
        </> : null}
      </dl>
      <h3>{t('tm.versionHistory')}</h3>
      {revisions.data?.length ? <ul className="template-version-list">
        {revisions.data.map(revision => <li key={revision.id}>
          {revision.label ?? `#${revision.revision_number}`}
          {revision.id === template.source_revision_id ? <strong>{t('tm.currentContext')}</strong> : null}
          <StatusBadge status={revision.status} />
        </li>)}
      </ul> : <p className="helper-text">{t('state.notRecorded')}</p>}
    </details>
  </div>;
}
