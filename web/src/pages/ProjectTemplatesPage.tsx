import { Alert, Button, Input, Modal, Radio } from '@arco-design/web-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { seedProjectsApi, templateName, type SeedProjectTemplate } from '../api/seedProjects';
import { openModelingHandoff } from '../api/modeling';
import { languageParam, useI18n } from '../i18n';
import { PageHeader } from '../components/ui/PageHeader';
import { EmptyState, ErrorState, LoadingState } from '../components/ui/States';
import { TemplateFinalizePanel } from '../components/TemplateFinalizePanel';

export function ProjectTemplatesPage() {
  const navigate = useNavigate();
  const { t, lang } = useI18n();
  const seeds = useQuery({queryKey: ['seed-project-templates'], queryFn: seedProjectsApi.catalog});
  const catalog = useQuery({ queryKey: ['casepacks'], queryFn: api.casepacks });
  const [selected, setSelected] = useState<string | null>(null);
  const edit = useMutation({mutationFn: (item: SeedProjectTemplate) => openModelingHandoff(templateName(item, lang), item.source_model_id, item.source_revision_id ?? undefined, lang)});
  const editTemplate = (item: SeedProjectTemplate) => {
    if (window.__NEBULA_ONE_DESKTOP__) { edit.mutate(item); return; }
    const params = new URLSearchParams({ application: item.source_application_id, model: item.source_model_id, launch: '1', template: '1' });
    if (item.source_revision_id) params.set('revision', item.source_revision_id);
    // The modelling app runs on another port, so language is carried in the URL rather than storage.
    params.set('lang', lang);
    window.open(`/modeling?${params}`, '_blank', 'noopener,noreferrer');
  };
  return <main className="app-page">
    <PageHeader title={t('templates.title')} description={t('templates.subtitle')} action={<Button onClick={() => navigate('/model-import')}>{t('templates.import')}</Button>} />
    {seeds.isError ? <ErrorState error={seeds.error} onRetry={() => seeds.refetch()} /> : null}
    {edit.isError ? <ErrorState error={edit.error} /> : null}
    <div className="template-library-grid">{seeds.data?.items.map(item => <section className="section-panel template-library-card" key={item.id}><h2>{templateName(item, lang)}</h2><p className="template-library-card__summary">{t('templates.summary', { processes: item.process_count, fields: item.field_count })}</p><p className="helper-text">{t('templates.cardHint')}</p><small>{t('templates.version', { version: item.version })}</small><div className="template-library-card__actions"><Button type="primary" onClick={() => setSelected(`seed:${item.id}`)}>{t('templates.newProject')}</Button><Button onClick={() => editTemplate(item)}>{t('templates.editTemplate')}</Button></div></section>)}</div>
    {catalog.isLoading ? <LoadingState /> : catalog.isError ? <ErrorState error={catalog.error} onRetry={() => catalog.refetch()} /> : <div className="template-library-grid">{catalog.data?.items.flatMap(pack => pack.applications.filter(item => item.lifecycle_status === 'executable').map(item => {
      const key = `${pack.id}@${pack.version}/${item.id}@${item.version}`;
      return <section className="section-panel template-library-card" key={key}><h2>{item.title}</h2><p className="helper-text">{item.study_frame_title}</p><p>{item.editable_parameter_count ? t('dialog.editableParams', { count: item.editable_parameter_count }) : t('dialog.scaleOnly')}</p><div><small>{t('templates.version', { version: item.version })}</small><Button type="primary" onClick={() => setSelected(key)}>{t('templates.useNew')}</Button></div></section>;
    }))}</div>}
    <TemplateFinalizePanel />
    {selected !== null ? <ProjectCreateDialog key={selected} initialSelection={selected} onClose={() => setSelected(null)} /> : null}
  </main>;
}

export function ProjectCreateDialog({ onClose, initialSelection = '' }: { onClose: () => void; initialSelection?: string }) {
  const { t, lang } = useI18n();
  const seeds = useQuery({queryKey: ['seed-project-templates'], queryFn: seedProjectsApi.catalog});
  const catalog = useQuery({ queryKey: ['casepacks'], queryFn: api.casepacks });
  const client = useQueryClient();
  const navigate = useNavigate();
  const [selected, setSelected] = useState(initialSelection);
  const [name, setName] = useState('');
  const [search, setSearch] = useState('');
  const [showExamples, setShowExamples] = useState(!!initialSelection && !initialSelection.startsWith('seed:'));
  const [key, setKey] = useState(() => crypto.randomUUID());
  const choices = (catalog.data?.items ?? []).flatMap(pack => pack.applications.filter(item => item.lifecycle_status === 'executable').map(item => ({ pack, item, key: `${pack.id}@${pack.version}/${item.id}@${item.version}` })));
  const choice = choices.find(item => item.key === selected);
  const seed = seeds.data?.items.find(item => `seed:${item.id}` === selected);
  const query = search.trim().toLocaleLowerCase();
  const visibleSeeds = seeds.data?.items.filter(item => `${item.title} ${Object.values(item.display_name ?? {}).join(' ')}`.toLocaleLowerCase().includes(query)) ?? [];
  const visibleExamples = choices.filter(({item}) => `${item.title} ${item.study_frame_title}`.toLocaleLowerCase().includes(query));
  const create = useMutation({
    mutationFn: async () => {
      if (seed && name.trim()) {
        const result = await seedProjectsApi.create(seed.id, {name: name.trim(), project_key: key, expected_template_sha256: seed.template_sha256});
        return {application: {id: result.application_id}, system_model: {id: result.system_model_id}, base_revision: {id: result.revision_id}};
      }
      if (!choice || !name.trim()) throw new Error(t('dialog.fillName'));
      return api.materializeCasePack(choice.pack.id, choice.pack.version, choice.item.id, choice.item.version, {
        expected_case_pack_sha256: choice.pack.case_pack_sha256, expected_resolved_case_sha256: choice.item.resolved_case_sha256,
        project_name: name.trim(), project_key: key,
      });
    },
    onSuccess: result => {
      client.invalidateQueries({ queryKey: ['applications'] });
      onClose();
      navigate(`/applications/${result.application.id}/workbench?step=data&model=${result.system_model.id}&revision=${result.base_revision.id}`);
    },
  });
  return <Modal visible title={t('dialog.newProject')} className="project-create-dialog" style={{ width: 820, maxWidth: 'calc(100vw - 32px)' }} footer={null} onCancel={onClose} maskClosable={!create.isPending} closable={!create.isPending} escToExit={!create.isPending}>
    <div className="project-create-grid">
      <section className="section-panel"><h2>{t('dialog.chooseTemplate')}</h2><p className="helper-text">{t('dialog.chooseTemplateHint')}</p>
        <Input.Search aria-label={t('dialog.searchAria')} placeholder={t('dialog.searchPlaceholder')} allowClear value={search} onChange={setSearch} />
        {seeds.isError ? <ErrorState error={seeds.error} onRetry={() => seeds.refetch()} /> : null}
        {seeds.isLoading ? <LoadingState /> : <Radio.Group aria-label={t('dialog.templateGroupAria')} value={selected} disabled={create.isPending} onChange={value => {setSelected(value); setKey(crypto.randomUUID()); create.reset();}} className="template-options">{visibleSeeds.map(item => <Radio key={item.id} value={`seed:${item.id}`}><strong>{templateName(item, lang)}</strong><p>{t('templates.summary', { processes: item.process_count, fields: item.field_count })}</p><small>{t('templates.version', { version: item.version })}</small></Radio>)}</Radio.Group>}
        <div className="project-example-options">
          <Button type="text" aria-expanded={showExamples || !!query} onClick={() => setShowExamples(!showExamples)}>{t('dialog.examples', { count: choices.length })}</Button>
          {showExamples || query ? <>
            <p className="helper-text">{t('dialog.examplesHint')}</p>
            {catalog.isLoading ? <LoadingState /> : catalog.isError ? <ErrorState error={catalog.error} onRetry={() => catalog.refetch()} /> : <Radio.Group aria-label={t('dialog.exampleGroupAria')} value={selected} disabled={create.isPending} onChange={value => { setSelected(value); setKey(crypto.randomUUID()); create.reset(); }} className="template-options">{visibleExamples.map(({ key: id, item }) => <Radio key={id} value={id}><strong>{item.title}</strong><p>{item.editable_parameter_count ? t('dialog.editableParams', { count: item.editable_parameter_count }) : t('dialog.scaleOnly')}</p><small>{t('dialog.exampleVersion', { version: item.version, demand: item.demand.map(d => `${d.amount} ${d.unit}`).join(' + ') })}</small></Radio>)}</Radio.Group>}
          </> : null}
        </div>
        {seeds.isSuccess && catalog.isSuccess && !visibleSeeds.length && !visibleExamples.length ? <EmptyState description={query ? t('dialog.noTemplate') : t('dialog.noTemplateConfigured')} /> : null}
      </section>
      <section className="section-panel project-create-form"><h2>{t('dialog.projectName')}</h2><label htmlFor="project-name">{t('dialog.projectNameLabel')}</label><Input id="project-name" value={name} disabled={create.isPending} maxLength={255} onChange={value => { setName(value); setKey(crypto.randomUUID()); create.reset(); }} placeholder={t('dialog.projectNamePlaceholder')} />
        {choice || seed ? <p>{t('dialog.selected', { title: seed ? templateName(seed, lang) : choice?.item.title ?? '' })}</p> : <p className="helper-text">{t('dialog.pickTemplate')}</p>}
        <Alert type="info" content={t('dialog.lockNote')} />
        {create.isError ? <ErrorState error={create.error} /> : null}
        <Button type="primary" size="large" disabled={(!choice && !seed) || !name.trim() || create.isPending} loading={create.isPending} onClick={() => create.mutate()}>{t('dialog.create')}</Button>
        <Link to="/model-import" onClick={onClose}>{t('dialog.importInstead')}</Link>
        <Link to={`/modeling?${languageParam(lang)}`} target="_blank" rel="noopener noreferrer" onClick={onClose}>{t('dialog.modelInstead')}</Link>
      </section>
    </div>
  </Modal>;
}
