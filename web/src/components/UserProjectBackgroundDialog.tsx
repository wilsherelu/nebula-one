import { Alert, Button, Modal, Select } from '@arco-design/web-react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { api, isStaleDataVersion } from '../api/client';
import { seedProjectsApi } from '../api/seedProjects';
import type { ProjectWorkspace } from '../api/types';
import { useI18n } from '../i18n';
import { ErrorState } from './ui/States';

export function UserProjectBackgroundDialog({ workspace, consumerId, onClose, onSaved, onReload }: {
  workspace: ProjectWorkspace; consumerId: string; onClose: () => void;
  onSaved: (next: ProjectWorkspace) => void; onReload: () => void;
}) {
  const { lang } = useI18n();
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
  const port = workspace.background_ports?.find(item => item.exchange_id === consumerId);
  return <Modal visible title="关联自建供应过程" footer={null} onCancel={() => { if (!save.isPending) onClose(); }}
    closable={!save.isPending} maskClosable={!save.isPending} escToExit={!save.isPending} style={{ width: 620, maxWidth: 'calc(100vw - 32px)' }}>
    <p>{port?.process} · {port?.label}</p>
    <p className="helper-text">选择已在专业建模中保存的单过程供应项目和版本。系统会核对参考产品流、单位与模型内容。</p>
    <label className="project-field"><span>供应项目</span><Select aria-label="供应项目"
      value={projects.data?.items.some(item => item.project_id === projectId) ? projectId : undefined}
      placeholder="选择供应项目" loading={projects.isLoading} disabled={save.isPending}
      options={(projects.data?.items ?? []).filter(item => item.latest_version !== null)
        .map(item => ({value: item.project_id, label: `${item.name} · v${item.latest_version}`}))}
      onChange={value => { setProjectId(String(value)); setVersion(undefined); resolve.reset(); }} /></label>
    {projects.data?.items.every(item => item.latest_version === null)
      ? <Alert type="info" content="尚无已保存的供应过程。请先到“专业建模”创建单过程项目并保存版本，再返回此处关联。" /> : null}
    <label className="project-field"><span>模型版本</span><Select aria-label="供应项目版本" value={versions.data?.items.some(item => item.version === version) ? String(version) : undefined}
      placeholder="选择模型版本" loading={versions.isLoading} disabled={!projectId || save.isPending}
      options={(versions.data?.items ?? []).map(item => ({value: String(item.version), label: `版本 ${item.version}`}))}
      onChange={value => { setVersion(Number(value)); resolve.reset(); }} /></label>
    {projects.isError ? <ErrorState error={projects.error} /> : null}
    {versions.isError ? <ErrorState error={versions.error} /> : null}
    <Button disabled={!projectId || !version || resolve.isPending || save.isPending} loading={resolve.isPending} onClick={() => resolve.mutate()}>校验供应过程</Button>
    {resolve.isError ? <ErrorState error={resolve.error} /> : null}
    {checked ? <><Alert type="info" content={`已核对 ${checked.name}，1 ${checked.consumer_unit} 投入对应 ${checked.pin.provider_amount_per_consumer_unit} ${checked.reference_unit} 供应。该过程仅覆盖这一项供应，不自动形成完整生命周期或 CBAM 合规结论。`} />
      <details><summary>精确来源</summary><p>项目 {checked.pin.project_id} · 版本 {checked.pin.version} · 图哈希 {checked.pin.expected_graph_hash}</p></details>
      <Button type="primary" disabled={save.isPending} loading={save.isPending} onClick={() => save.mutate(false)}>关联并保存新版本</Button></> : null}
    {(workspace.project_background_pins ?? []).some(item => item.consumer_exchange_id === consumerId)
      ? <Button disabled={save.isPending} onClick={() => save.mutate(true)}>移除此供应关联</Button> : null}
    {save.isError ? <ErrorState error={save.error} onRetry={isStaleDataVersion(save.error) ? onReload : undefined} /> : null}
  </Modal>;
}
