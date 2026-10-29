import { Link, useParams, useSearchParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { Alert, Button, Modal, Tag } from '@arco-design/web-react';
import { templateMethodsApi, type TemplateMethodCopyResult, type TemplateMethodGap, type TemplateSaveResult } from '../api/templateMethods';
import { openModelingHandoff } from '../api/modeling';
import { useI18n } from '../i18n';
import { PageHeader } from '../components/ui/PageHeader';
import { ErrorState, LoadingState } from '../components/ui/States';
import { ProjectCreateDialog } from './ProjectTemplatesPage';
import { MethodEditor } from './calculationMethods/MethodEditor';
import { NewMethodForm } from './calculationMethods/MethodList';
import { MethodSchemePanel } from './templateConfig/MethodSchemePanel';
import { MethodTaskPanel } from './templateConfig/MethodTaskPanel';
import { SaveTemplateDialog } from './templateConfig/SaveTemplateDialog';
import { ModelDataPanel } from './templateConfig/ModelDataPanel';
import { IndicatorDialog } from './templateConfig/IndicatorDialog';
import type { TemplateAccountingMethod } from '../api/templateMethods';

/** One focused workspace for a single exact template version: no second back link, no source pickers. */
export function TemplateConfigPage() {
  const { templateId = '' } = useParams();
  const [params, setParams] = useSearchParams();
  const { t, lang } = useI18n();
  const aggregation = useQuery({
    queryKey: ['template-accounting-methods', templateId, lang],
    queryFn: () => templateMethodsApi.forTemplate(templateId, lang),
  });
  const editModel = useMutation({
    mutationFn: () => {
      const template = aggregation.data?.template;
      if (!template) throw new Error(t('tm.contextUnresolved'));
      return openModelingHandoff(templateTitle(template.title, template.display_name, lang), template.source_model_id, template.source_revision_id ?? undefined, lang);
    },
  });
  const [createOpen, setCreateOpen] = useState(false);
  const [schemeOpen, setSchemeOpen] = useState(false);
  const [indicator, setIndicator] = useState<TemplateAccountingMethod | null>(null);
  const [saveOpen, setSaveOpen] = useState(false);
  const [saved, setSaved] = useState<TemplateSaveResult | null>(null);
  const [copyNotes, setCopyNotes] = useState<TemplateMethodGap[]>([]);
  const queryClient = useQueryClient();
  const tab = params.get('tab') === 'model' ? 'model' : 'methods';
  const editingRule = tab === 'methods' && !!params.get('method');
  const setTab = (next: 'model' | 'methods') => setParams(previous => {
    const updated = new URLSearchParams(previous);
    updated.set('tab', next);
    updated.delete('method');
    return updated;
  }, { replace: true });

  const shell = (body: ReactNode) => <main className={`app-page template-config-page${editingRule ? ' template-config-page--editing' : ''}`}>
    {!editingRule ? <div className="project-workspace-header">
      <PageHeader title={aggregation.data ? templateTitle(aggregation.data.template.title, aggregation.data.template.display_name, lang) : t('tm.configTitle')}
        description=""
        action={!editingRule ? <div className="project-header-actions">
          <Button type="primary" onClick={() => setCreateOpen(true)}>{t('templates.newProject')}</Button>
          {aggregation.data ? <Button onClick={() => { setSaved(null); setSaveOpen(true); }}>
            {t('tm.saveAction')}</Button> : null}
          <Link className="arco-btn arco-btn-text" to="/templates">{t('tm.backToTemplates')}</Link>
        </div> : undefined} />
    </div> : null}
    {aggregation.data && !editingRule ? <div className="template-config-status">
      <Tag size="small" color={aggregation.data.template.official ? 'arcoblue' : 'green'}>
        {t(aggregation.data.template.official ? 'tm.officialTemplate' : 'tm.userTemplate')}
      </Tag>
      <span>{t('templates.version', { version: aggregation.data.template.version })}</span>
    </div> : null}
    {!editingRule ? <nav className="result-tabs__navigation" aria-label={t('tm.configTitle')}>
      <div className="result-tabs__list">
        <button type="button" className={tab === 'model' ? 'is-active' : ''} onClick={() => setTab('model')}>{t('tm.tabModel')}</button>
        <button type="button" className={tab === 'methods' ? 'is-active' : ''} onClick={() => setTab('methods')}>{t('tm.tabMethods')}</button>
      </div>
    </nav> : null}
    {copyNotes.length ? <Alert className="template-copy-notes" type="info" showIcon closable
      onClose={() => setCopyNotes([])} content={<div>
        <strong>{t('tm.copyNotes', { count: copyNotes.length })}</strong>
        <ul>{copyNotes.map((note, index) => <li key={`${note.code}-${index}`}>
          <span>{note.message}</span>
          {note.exchange_id ? <code>{note.exchange_id}</code> : null}
          {note.clause ? <span className="helper-text">{note.clause}</span> : null}
        </li>)}</ul>
      </div>} /> : null}
    {saved ? <Alert className="template-copy-notes" type="success" showIcon closable
      onClose={() => setSaved(null)} content={<div>
        <strong>{t('tm.savedTitle', { title: saved.template.title, version: saved.template.version })}</strong>
        <p className="helper-text">{t('tm.savedHint')}</p>
      </div>} /> : null}
    <div className="result-tabs__panel">{body}</div>
    {schemeOpen && aggregation.data?.template.source_revision_id ? <Modal visible title={t('tm.newScheme')}
      footer={null} onCancel={() => setSchemeOpen(false)}>
      <NewMethodForm applicationId={aggregation.data.template.source_application_id}
        revisionId={aggregation.data.template.source_revision_id} onCancel={() => setSchemeOpen(false)}
        onCreated={id => {
          setSchemeOpen(false);
          void queryClient.invalidateQueries({ queryKey: ['template-accounting-methods', templateId] });
          setParams(previous => { const next = new URLSearchParams(previous); next.set('method', id); next.delete('version'); return next; });
        }} />
    </Modal> : null}
    {indicator ? <IndicatorDialog scheme={indicator} onClose={() => setIndicator(null)}
      onCreate={() => { setIndicator(null); setCreateOpen(true); }} /> : null}
    {saveOpen ? <SaveTemplateDialog key={`${templateId}:${saved?.template.id ?? ''}`} templateId={templateId}
      onClose={() => setSaveOpen(false)} onSaved={result => { setSaveOpen(false); setSaved(result); }} /> : null}
    {createOpen && aggregation.data ? <ProjectCreateDialog initialSelection={`seed:${aggregation.data.template.id}`}
      onClose={() => setCreateOpen(false)} /> : null}
  </main>;

  if (aggregation.isLoading) return shell(<LoadingState />);
  if (aggregation.isError || !aggregation.data) {
    return shell(<ErrorState error={aggregation.error ?? new Error(t('tm.contextUnresolved'))} onRetry={() => aggregation.refetch()} />);
  }
  if (editModel.isError) return shell(<ErrorState error={editModel.error} />);
  const data = aggregation.data;
  // Inspect the bound characterization in this workspace; no custom rule is required.
  const configureIndicator = (scheme: TemplateAccountingMethod) => setIndicator(scheme);
  if (tab === 'model') {
    return shell(<ModelDataPanel data={data} editing={editModel.isPending} onEditModel={() => editModel.mutate()}
      onViewIndicator={configureIndicator} />);
  }
  const opened = params.get('method');
  const openedScheme = data.methods.find(item => item.user_method?.method_id === opened);
  if (opened && openedScheme?.user_method && data.template.source_revision_id) {
    if (!data.template.model.graph_snapshot) return shell(<ErrorState error={new Error(t('tm.contextUnresolved'))}
      onRetry={() => aggregation.refetch()} />);
    return shell(<MethodEditor templateMode key={openedScheme.user_method.method_id} applicationId={data.template.source_application_id}
      revisionId={data.template.source_revision_id} revisionLabel={templateTitle(data.template.title, data.template.display_name, lang)}
      methodId={openedScheme.user_method.method_id}
      graph={data.template.model.graph_snapshot}
      onBack={() => setParams(previous => { const next = new URLSearchParams(previous); next.delete('method'); next.delete('version'); return next; })} />);
  }
  const openScheme = (scheme: TemplateAccountingMethod) => {
    if (scheme.user_method?.method_id) {
      setParams(previous => { const next = new URLSearchParams(previous); next.set('method', scheme.user_method!.method_id); return next; });
    }
  };
  const onCopied = (result: TemplateMethodCopyResult) => {
    setCopyNotes(result.transcription.notes);
    void queryClient.invalidateQueries({ queryKey: ['template-accounting-methods', templateId] });
    setParams(previous => { const next = new URLSearchParams(previous); next.set('method', result.method.method.id); next.delete('version'); return next; });
  };
  const createScheme = () => setSchemeOpen(true);
  if (data.tasks?.length) {
    return shell(<MethodTaskPanel templateId={templateId} data={data} onOpen={openScheme} onCopied={onCopied}
      onCreateScheme={createScheme} />);
  }
  return shell(<MethodSchemePanel templateId={templateId} data={data} onOpen={openScheme} onCopied={onCopied} />);
}

function templateTitle(title: string, displayName: Record<string, string> | null, lang: string): string {
  return displayName?.[lang]?.trim() || title;
}
