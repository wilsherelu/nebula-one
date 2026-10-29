import { Link, useParams, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';
import { Select } from '@arco-design/web-react';
import { api } from '../api/client';
import { useI18n } from '../i18n';
import { PageHeader } from '../components/ui/PageHeader';
import { ErrorState, LoadingState } from '../components/ui/States';
import { ReturnToProject } from '../components/ReturnToProject';
import { useUrlSelection } from '../hooks/useUrlSelection';
import { MethodList } from './calculationMethods/MethodList';
import { MethodEditor } from './calculationMethods/MethodEditor';
import { MethodMigration } from './calculationMethods/MethodMigration';
import { TemplateContextRedirect } from './templateConfig/TemplateContextRedirect';
export function CalculationMethodsPage() {
  const { applicationId = '' } = useParams();
  const { t } = useI18n();
  const [params, setParams] = useSearchParams();

  const models = useQuery({ queryKey: ['models', applicationId], queryFn: () => api.models(applicationId) });
  const modelIds = useMemo(() => models.data?.map(model => model.id) ?? [], [models.data]);
  const model = useUrlSelection('model', modelIds, {
    ready: models.isSuccess,
    fallbackId: models.data?.[0]?.id,
    clearKeys: ['revision', 'method', 'version'],
  });
  const revisions = useQuery({
    queryKey: ['revisions', model.value],
    queryFn: () => api.revisions(model.value),
    enabled: !!model.value && !!models.data?.some(item => item.id === model.value),
  });
  const revisionIds = useMemo(() => revisions.data?.map(revision => revision.id) ?? [], [revisions.data]);
  const revision = useUrlSelection('revision', revisionIds, {
    ready: revisions.isSuccess,
    fallbackId: revisions.data?.at(-1)?.id,
    clearKeys: ['method', 'version'],
  });
  const selectedRevision = revisions.data?.find(item => item.id === revision.value);

  const methods = useQuery({
    queryKey: ['calculation-methods', applicationId, revision.value],
    queryFn: () => api.calculationMethods(applicationId, revision.value),
    enabled: !!revision.value && !revision.invalid && !model.invalid,
  });
  const packages = useQuery({ queryKey: ['method-packages', applicationId], queryFn: api.methodPackages });

  const methodIds = useMemo(() => methods.data?.map(item => item.id) ?? [], [methods.data]);
  const methodSelection = useUrlSelection('method', methodIds, { ready: methods.isSuccess });

  const write = (mutate: (next: URLSearchParams) => void) => setParams(previous => { const next = new URLSearchParams(previous); mutate(next); return next; });
  const revisionLabel = selectedRevision ? (selectedRevision.label ?? `#${selectedRevision.revision_number}`) : '';

  // A template=1 link is template configuration, not a project method list: it enters the
  // configuration workspace, which resolves the exact template version instead of guessing one.
  if (params.get('template') === '1') {
    return <main className="app-page calculation-methods-page">
      <TemplateContextRedirect source={applicationId} model={model.value} revision={revision.value} tab="methods" />
    </main>;
  }

  const header = <div className="project-workspace-header"><PageHeader title={t('cm.title')} description=""
    action={<div className="project-header-actions">
      <ReturnToProject applicationId={applicationId} />
    </div>} /></div>;
  if (models.error || revisions.error || methods.error) {
    return <main className="app-page calculation-methods-page">{header}
      <ErrorState error={models.error || revisions.error || methods.error}
        onRetry={() => { void models.refetch(); void revisions.refetch(); void methods.refetch(); }} /></main>;
  }
  if (models.isLoading || model.pending || revisions.isLoading || revision.pending) {
    return <main className="app-page calculation-methods-page">{header}<LoadingState /></main>;
  }
  if (model.invalid || revision.invalid || !model.value || !revision.value) {
    return <main className="app-page calculation-methods-page">{header}
      <ErrorState error={Object.assign(new Error(t('workspace.badSelection')), { name: 'BadSelection' })} onRetry={() => write(next => { next.delete('model'); next.delete('revision'); next.delete('method'); })} /></main>;
  }

  const selectors = <div className="calculation-methods__selectors">
    <label htmlFor="cm-model">{t('cm.modelLabel')}</label>
    <Select id="cm-model" value={model.value || undefined}
      onChange={value => model.select(String(value))}
      options={(models.data ?? []).map(item => ({ value: item.id, label: item.name }))} />
    <label htmlFor="cm-revision">{t('cm.methodLabel')}</label>
    <Select id="cm-revision" value={revision.value || undefined} loading={revisions.isLoading}
      onChange={value => revision.select(String(value))}
      options={(revisions.data ?? []).map(item => ({ value: item.id, label: item.label ?? `#${item.revision_number}` }))} />
  </div>;

  if (methodSelection.invalid) {
    return <main className="app-page calculation-methods-page">{header}{selectors}
      <ErrorState error={Object.assign(new Error(t('cm.notFound')), { name: 'MethodNotFound' })} onRetry={() => write(next => { next.delete('method'); next.delete('version'); })} /></main>;
  }

  if (methodSelection.requested && methodSelection.value && !methodSelection.pending) {
    return <main className="app-page calculation-methods-page">
      <MethodEditor key={`${applicationId}:${revision.value}:${methodSelection.value}`} applicationId={applicationId} revisionId={revision.value} revisionLabel={revisionLabel}
        graph={selectedRevision?.graph_snapshot}
        methodId={methodSelection.value} onBack={() => write(next => { next.delete('method'); next.delete('version'); })} /></main>;
  }

  if (methods.isLoading) {
    return <main className="app-page calculation-methods-page">{header}{selectors}<LoadingState /></main>;
  }

  return <main className="app-page calculation-methods-page">{header}{selectors}
    <MethodList methods={methods.data ?? []} packages={packages.data ?? []} packagesLoading={packages.isLoading}
      revisionLabel={revisionLabel} applicationId={applicationId} revisionId={revision.value}
      onOpen={id => write(next => { next.set('method', id); })} />
    <MethodMigration key={revision.value} applicationId={applicationId} revisionId={revision.value} modelRevisionIds={revisionIds}
      onCreated={id => write(next => { next.set('method', id); next.delete('version'); })} /></main>;
}
