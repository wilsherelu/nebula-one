import { Button, Modal, Select } from '@arco-design/web-react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { api, isStaleDataVersion } from '../api/client';
import { seedProjectsApi } from '../api/seedProjects';
import type { ProjectWorkspace } from '../api/types';
import { useI18n } from '../i18n';
import { ErrorState } from './ui/States';

export function UserProjectBackgroundDialog({ workspace, consumerId, onClose, onSaved, onReload, embedded = false, onBusyChange }: {
  workspace: ProjectWorkspace; consumerId: string; onClose: () => void;
  onSaved: (next: ProjectWorkspace) => void; onReload: () => void;
  embedded?: boolean;
  onBusyChange?: (busy: boolean) => void;
}) {
  const { lang, t } = useI18n();
  const existing = workspace.project_background_pins?.find(item => item.consumer_exchange_id === consumerId);
  const [projectId, setProjectId] = useState(existing?.project_id ?? '');
  const [version, setVersion] = useState<number | undefined>(existing?.version);
  const projects = useQuery({ queryKey: ['user-supply-projects', workspace.application_id, workspace.revision_id],
    queryFn: () => seedProjectsApi.userSupplyProjects(workspace.application_id, workspace.revision_id) });
  const versions = useQuery({ queryKey: ['user-supply-versions', workspace.application_id, workspace.revision_id, projectId],
    queryFn: () => seedProjectsApi.userSupplyVersions(workspace.application_id, workspace.revision_id, projectId),
    enabled: Boolean(projectId) });
  const resolve = useMutation({ mutationFn: () => seedProjectsApi.resolveUserProject(
    workspace.application_id, workspace.revision_id,
    { consumer_exchange_id: consumerId, project_id: projectId, version: version! },
  ) });
  const checked = resolve.data?.pin.project_id === projectId && resolve.data?.pin.version === version
    ? resolve.data : undefined;
  const save = useMutation({ mutationFn: (remove: boolean) => api.saveProjectInputs(workspace.application_id, {
    revision_id: workspace.revision_id, expected_content_sha256: workspace.content_sha256,
    amounts: workspace.demand.map(item => item.amount), demand_mode: workspace.demand_mode,
    values: Object.fromEntries(workspace.fields.map(field => [field.key, field.value])), source: workspace.source,
    background_process_pins: (workspace.background_process_pins ?? []).filter(item => remove || item.consumer_exchange_id !== consumerId),
    mapped_background_process_pins: (workspace.mapped_background_process_pins ?? []).filter(item => remove || item.consumer_exchange_id !== consumerId),
    project_background_pins: remove
      ? (workspace.project_background_pins ?? []).filter(item => item.consumer_exchange_id !== consumerId)
      : [...(workspace.project_background_pins ?? []).filter(item => item.consumer_exchange_id !== consumerId), checked!.pin],
    model_processing_rules_ref: remove ? workspace.model_processing_rules_ref : checked!.model_processing_rules_ref,
  }, lang), onSuccess: next => { onSaved(next); onClose(); } });
  useEffect(() => { onBusyChange?.(save.isPending); }, [onBusyChange, save.isPending]);
  const port = workspace.background_ports?.find(item => item.exchange_id === consumerId);
  const content = <><div className="background-picker-body">
    {!embedded ? <p>{port?.process} · {port?.label}</p> : null}
    <div className="project-field"><span>{t('background.supplyProject')}</span><Select aria-label={t('background.supplyProject')}
      value={projects.data?.items.some(item => item.project_id === projectId) ? projectId : undefined}
      placeholder={t('background.supplyProject')} loading={projects.isLoading} disabled={save.isPending}
      options={(projects.data?.items ?? []).filter(item => item.latest_version !== null)
        .map(item => ({value: item.project_id, label: `${item.name} · v${item.latest_version}`}))}
      onChange={value => { setProjectId(String(value)); setVersion(undefined); resolve.reset(); }} /></div>
    {projects.data?.items.every(item => item.latest_version === null)
      ? <p>{t('background.empty')}</p> : null}
    <div className="project-field"><span>{t('background.supplyVersion')}</span><Select aria-label={t('background.supplyVersion')} value={versions.data?.items.some(item => item.version === version) ? String(version) : undefined}
      placeholder={t('background.supplyVersion')} loading={versions.isLoading} disabled={!projectId || save.isPending}
      options={(versions.data?.items ?? []).map(item => ({value: String(item.version), label: `v${item.version}`}))}
      onChange={value => { setVersion(Number(value)); resolve.reset(); }} /></div>
    {projects.isError ? <ErrorState error={projects.error} /> : null}
    {versions.isError ? <ErrorState error={versions.error} /> : null}
    <Button disabled={!projectId || !version || resolve.isPending || save.isPending} loading={resolve.isPending} onClick={() => resolve.mutate()}>{t('background.validate')}</Button>
    {resolve.isError ? <ErrorState error={resolve.error} /> : null}
    {checked ? <><p className="helper-text">{t('background.validated', { name: checked.name })}</p>
      <details><summary>{t('results.details')}</summary><p>{checked.pin.project_id} · v{checked.pin.version}</p><p>{checked.pin.expected_graph_hash}</p></details>
      </> : null}
    {(workspace.project_background_pins ?? []).some(item => item.consumer_exchange_id === consumerId)
      ? <Button disabled={save.isPending} onClick={() => save.mutate(true)}>{t('background.remove')}</Button> : null}
    {save.isError ? <ErrorState error={save.error} onRetry={isStaleDataVersion(save.error) ? onReload : undefined} /> : null}
  </div><div className="background-picker-footer"><Button disabled={save.isPending} onClick={onClose}>{t('background.cancel')}</Button><Button type="primary" disabled={!checked || save.isPending} loading={save.isPending} onClick={() => save.mutate(false)}>{t('background.linkConfirm')}</Button></div></>;
  return embedded ? content : <Modal visible title={t('background.choose')} className="background-picker" footer={null} onCancel={() => { if (!save.isPending) onClose(); }} closable={!save.isPending} maskClosable={!save.isPending} escToExit={!save.isPending} style={{ width: 720, maxWidth: 'calc(100vw - 32px)' }}>{content}</Modal>;
}
