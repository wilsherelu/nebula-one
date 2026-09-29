import { Alert, Button, Checkbox, Input, Select } from '@arco-design/web-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { api } from '../api/client';
import { seedProjectsApi } from '../api/seedProjects';
import { useI18n } from '../i18n';
import { ErrorState, LoadingState } from './ui/States';

export function TemplateFinalizePanel() {
  const { t, lang } = useI18n();
  const client = useQueryClient();
  const applications = useQuery({ queryKey: ['applications', lang], queryFn: () => api.applications(lang) });
  const methods = useQuery({ queryKey: ['method-packages'], queryFn: api.methodPackages });
  const candidates = applications.data?.filter(item => item.context.modeling_handoff_id && item.context.modeling_template_binding && item.context.template_locked) ?? [];
  const [applicationId, setApplicationId] = useState('');
  const selectedApplication = candidates.find(item => item.id === applicationId);
  const models = useQuery({ queryKey: ['models', applicationId], queryFn: () => api.models(applicationId), enabled: !!selectedApplication });
  const [modelId, setModelId] = useState('');
  const selectedModel = models.data?.find(item => item.id === modelId);
  const revisions = useQuery({ queryKey: ['revisions', modelId], queryFn: () => api.revisions(modelId), enabled: !!selectedModel });
  const [revisionId, setRevisionId] = useState('');
  const selectedRevision = revisions.data?.find(item => item.id === revisionId && item.revision_kind === 'base');
  const [title, setTitle] = useState('');
  const [version, setVersion] = useState('1.0.0');
  const [refs, setRefs] = useState<string[]>([]);
  const availableRefs = (Array.isArray(selectedApplication?.context.method_package_refs) ? selectedApplication.context.method_package_refs : [])
    .filter((ref): ref is string => typeof ref === 'string');
  const availableMethods = (methods.data ?? []).filter(item => availableRefs.includes(`${item.package_id}@${item.version}`));
  const publish = useMutation({ mutationFn: () => seedProjectsApi.publish({
    title: title.trim(), version: version.trim(), source_application_id: applicationId,
    source_model_id: modelId, source_revision_id: revisionId,
    expected_revision_sha256: selectedRevision!.content_sha256,
    methods: availableMethods.filter(item => refs.includes(`${item.package_id}@${item.version}`))
      .map(item => ({ package_id: item.package_id, version: item.version, content_sha256: item.content_sha256 })),
  }), onSuccess: () => client.invalidateQueries({ queryKey: ['seed-project-templates'] }) });
  return <section className="section-panel template-finalize-panel">
    <h2>{t('templates.finalizeTitle')}</h2><p className="helper-text">{t('templates.finalizeHint')}</p>
    {applications.isLoading || methods.isLoading ? <LoadingState rows={2} /> : null}
    {applications.isError || methods.isError ? <ErrorState error={applications.error || methods.error} /> : null}
    {!candidates.length && applications.isSuccess ? <Alert type="info" content={t('templates.noModelToFinalize')} /> : null}
    <div className="template-finalize-fields">
      <label>{t('templates.sourceProject')}<Select value={applicationId || undefined} options={candidates.map(item => ({ label: item.name, value: item.id }))}
        onChange={value => { setApplicationId(value); setModelId(''); setRevisionId(''); setRefs([]); publish.reset(); }} /></label>
      {selectedApplication ? <label>{t('templates.sourceModel')}<Select value={modelId || undefined}
        options={models.data?.map(item => ({ label: `${item.name} · v${item.upstream_version}`, value: item.id }))}
        onChange={value => { setModelId(value); setRevisionId(''); publish.reset(); }} /></label> : null}
      {selectedModel ? <label>{t('templates.sourceRevision')}<Select value={revisionId || undefined}
        options={revisions.data?.filter(item => item.revision_kind === 'base').map(item => ({ label: `${t('workspace.dataVersion')} ${item.revision_number}`, value: item.id }))}
        onChange={value => { setRevisionId(value); publish.reset(); }} /></label> : null}
      {selectedRevision ? <><label>{t('templates.templateName')}<Input value={title} onChange={setTitle} maxLength={255} /></label>
        <label>{t('templates.templateVersion')}<Input value={version} onChange={setVersion} maxLength={32} /></label>
        <fieldset><legend>{t('templates.methods')}</legend>{availableMethods.map(item => {
          const ref = `${item.package_id}@${item.version}`;
          return <Checkbox key={ref} checked={refs.includes(ref)} onChange={checked => setRefs(previous => checked ? [...previous, ref] : previous.filter(value => value !== ref))}>
            {ref}</Checkbox>;
        })}</fieldset></> : null}
    </div>
    {publish.isError ? <ErrorState error={publish.error} /> : null}
    {publish.isSuccess ? <Alert type="success" content={t('templates.finalized')} /> : null}
    <Button type="primary" disabled={!selectedRevision || !title.trim() || !version.trim() || publish.isPending}
      loading={publish.isPending} onClick={() => publish.mutate()}>{t('templates.finalize')}</Button>
  </section>;
}
