import { Button, Input, Table, Tooltip } from '@arco-design/web-react';
import { IconArrowRight, IconDown, IconRight, IconSearch } from '@arco-design/web-react/icon';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import type { Application, SystemModel } from '../api/types';
import { useI18n } from '../i18n';
import { PageHeader } from '../components/ui/PageHeader';
import { StatusBadge } from '../components/ui/StatusBadge';
import { EmptyState, ErrorState, LoadingState } from '../components/ui/States';

function ApplicationModels({ application }: { application: Application }) {
  const navigate = useNavigate();
  const { t, formatDate } = useI18n();
  const models = useQuery({ queryKey: ['models', application.id], queryFn: () => api.models(application.id) });
  const open = (model: SystemModel) => navigate(`/applications/${application.id}/workbench?model=${model.id}`);
  return (
      <div className="model-list catalog-models" aria-label={t('projects.modelsAria', { name: application.name })}>
        {models.isLoading ? <LoadingState rows={2} /> : null}
        {models.isError ? <ErrorState error={models.error} onRetry={() => models.refetch()} /> : null}
        {models.data?.length === 0 ? <EmptyState description={t('projects.noModel')} /> : null}
        {models.data?.map((model) => (
          <button className="model-row" key={model.id} onClick={() => open(model)}>
            <span className="model-row__identity"><strong>{model.name}</strong><small>{t('projects.modelVersion', { version: model.upstream_version })}</small></span>
            <IconArrowRight aria-hidden="true" />
          </button>
        ))}
      </div>
  );
}

export function ApplicationsPage() {
  const navigate = useNavigate();
  const { t, lang, formatDate } = useI18n();
  const [query, setQuery] = useState('');
  const applications = useQuery({ queryKey: ['applications', lang], queryFn: () => api.applications(lang) });
  const filtered = applications.data?.filter((item) => item.name.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())) ?? [];
  return (
    <main className="app-page catalog-page">
      <PageHeader title={t('nav.projects')} description={t('projects.subtitle')} action={<Button type="primary" size="small" onClick={() => navigate('/applications?create=project')}>{t('home.newProject')}</Button>} />
      {applications.isLoading ? <section className="section-panel"><LoadingState rows={5} /></section> : null}
      {applications.isError ? <ErrorState error={applications.error} onRetry={() => applications.refetch()} /> : null}
      {applications.data?.length === 0 ? <section className="section-panel"><EmptyState description={t('projects.none')} /></section> : null}
      {applications.data?.length ? <section className="catalog-surface" aria-label={t('projects.surfaceAria')}>
        <div className="catalog-toolbar"><span className="catalog-toolbar__count">{t('projects.all')} <span className="helper-text">{t('projects.count', { count: filtered.length })}</span></span><Input aria-label={t('projects.searchAria')} placeholder={t('projects.searchPlaceholder')} prefix={<IconSearch />} allowClear value={query} onChange={setQuery} /></div>
        <Table<Application> className="catalog-table" rowKey="id" data={filtered} border={false} pagination={false} scroll={{ x: 800 }} expandProps={{ width: 40, icon: ({ expanded, record }) => <Button type="text" size="small" aria-label={`${expanded ? t('projects.collapse') : t('projects.expand')} · ${t('projects.modelsAria', { name: record.name })}`} aria-expanded={expanded} icon={expanded ? <IconDown /> : <IconRight />} /> }} expandedRowRender={(application) => <ApplicationModels application={application} />} noDataElement={<EmptyState description={t('projects.emptyTable')} />} columns={[
          { title: t('projects.columnName'), dataIndex: 'name', width: 380, render: (name: string, item) => <Tooltip content={name} trigger={['hover', 'focus']}><button className="catalog-record-name" type="button" onClick={() => navigate(`/applications/${item.id}/workbench`)}>{name}</button></Tooltip> },
          { title: t('projects.columnStatus'), width: 90, render: (_, item) => <StatusBadge status={item.status} /> },
          { title: t('projects.columnUpdated'), width: 180, render: (_, item) => <span className="helper-text tabular">{formatDate(item.updated_at)}</span> },
          { title: t('projects.columnActions'), width: 110, fixed: 'right', align: 'right', render: (_, item) => <Button type="text" size="small" onClick={() => navigate(`/applications/${item.id}/workbench`)}>{t('projects.open')}</Button> },
        ]} />
      </section> : null}
    </main>
  );
}
