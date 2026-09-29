import { Alert, Button, Input } from '@arco-design/web-react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import { modelingApi, openModelingHandoff, withLanguage } from '../api/modeling';
import { useI18n } from '../i18n';
import { PageHeader } from '../components/ui/PageHeader';
import { ErrorState, LoadingState } from '../components/ui/States';

export function ModelingPage() {
  const [params] = useSearchParams();
  return params.has('model') ? <ModelingHandoffPage /> : <ModelingHome />;
}

function ModelingHome() {
  const { t, lang } = useI18n();
  const config = useQuery({queryKey: ['modeling-configuration'], queryFn: modelingApi.configuration});
  const editorHome = config.data?.editor_url ? new URL(withLanguage(config.data.editor_url, lang)) : null;
  editorHome?.searchParams.set('from_nebula_one', '1');
  useEffect(() => {
    if (config.data?.available && editorHome) window.location.assign(editorHome.toString());
  }, [config.data?.available, config.data?.editor_url, lang]);
  return <main className="app-page modeling-page">
    <PageHeader title={t('nav.modeling')} description={t('modeling.opening')} action={<Link to="/">{t('modeling.backHome')}</Link>} />
    {config.isLoading ? <LoadingState /> : config.isError ? <ErrorState error={config.error} onRetry={() => config.refetch()} /> : !config.data?.available || !editorHome ? <Alert type="warning" content={config.data?.message} /> : <a href={editorHome.toString()}>{t('modeling.continue')}</a>}
  </main>;
}

function ModelingHandoffPage() {
  const { t, lang } = useI18n();
  const [params] = useSearchParams();
  const base = params.get('model') ?? undefined;
  const baseRevision = params.get('revision') ?? undefined;
  const applicationId = params.get('application') ?? '';
  // Only the template-author entry launches immediately. Old project edit links remain a
  // reviewable way to create a separate model; they never mutate a locked project in place.
  const autoLaunch = params.get('launch') === '1' && params.get('template') === '1';
  const started = useRef(false);
  const [name, setName] = useState('');
  const config = useQuery({queryKey: ['modeling-configuration'], queryFn: modelingApi.configuration});
  const models = useQuery({queryKey: ['models', applicationId], queryFn: () => api.models(applicationId), enabled: !!applicationId});
  const selected = models.data?.find(model => model.id === base);
  useEffect(() => {
    if (selected) setName(selected.name);
  }, [selected?.id]);
  const validBase = !params.has('model') || !!selected;
  const start = useMutation({mutationFn: async () => {
    await openModelingHandoff(name.trim(), base!, baseRevision, lang);
  }});
  useEffect(() => {
    if (autoLaunch && !started.current && selected && name.trim() && config.data?.available) {
      started.current = true;
      start.mutate();
    }
  }, [autoLaunch, selected, name, config.data?.available]);
  return <main className="app-page modeling-page">
    <PageHeader title={t('nav.modeling')} description={t('modeling.hint')} action={<Link to="/">{t('modeling.backHome')}</Link>} />
    <section className="section-panel modeling-start">
      <h2>{base ? t('modeling.saveAs') : t('modeling.newModel')}</h2>
      <p>{t('modeling.editScope')}</p>
      {selected ? <p>{t('modeling.baseModel', { name: selected.name, version: selected.upstream_version })}</p> : null}
      {params.has('model') && !validBase && !models.isLoading ? <Alert type="error" content={t('modeling.baseMissing')} /> : null}
      <label className="project-field"><span>{t('modeling.projectName')}</span><Input aria-label={t('modeling.projectName')} value={name} onChange={setName} maxLength={255} placeholder={t('modeling.projectNamePlaceholder')} /></label>
      {base ? <p className="helper-text">{t('modeling.autoOpen')}</p> : null}
      <Alert type="info" content={t('modeling.keepNote')} />
      {config.isLoading ? <LoadingState /> : config.isError ? <ErrorState error={config.error} onRetry={() => config.refetch()} /> : !config.data?.available ? <Alert type="warning" content={config.data?.message} /> : null}
      {models.isError ? <ErrorState error={models.error} /> : null}
      {start.isError ? <ErrorState error={start.error} /> : null}
      <div className="form-actions"><Link to="/model-import">{t('templates.import')}</Link><Button type="primary" disabled={!name.trim() || !validBase || !config.data?.available || start.isPending} loading={start.isPending} onClick={() => start.mutate()}>{t('modeling.enter')}</Button></div>
      {!name.trim() && config.data?.available ? <p role="status" className="helper-text">{t('modeling.needName')}</p> : null}
    </section>
  </main>;
}
