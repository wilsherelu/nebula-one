import { Alert, Button, Input, Modal, Table } from '@arco-design/web-react';
import { useMutation } from '@tanstack/react-query';
import { useState } from 'react';
import { api, isStaleDataVersion } from '../api/client';
import { seedProjectsApi } from '../api/seedProjects';
import type { BackgroundProcessPin, ProjectWorkspace } from '../api/types';
import { useI18n } from '../i18n';
import { ErrorState } from './ui/States';
import { MappedBackgroundDialog } from './MappedBackgroundDialog';
import { UserProjectBackgroundDialog } from './UserProjectBackgroundDialog';

type BackgroundPort = NonNullable<ProjectWorkspace['background_ports']>[number];

export function ProjectBackgroundPanel({workspace, onSaved, onContinue, onReload, portFilter, exchangeId, initialAction}: {
  workspace: ProjectWorkspace; onSaved: (workspace: ProjectWorkspace) => void; onContinue?: () => void; onReload: () => void;
  portFilter?: (port: BackgroundPort) => boolean; exchangeId?: string; initialAction?: 'external' | 'local';
}) {
  const [target, setTarget] = useState<string | undefined>(initialAction === 'external' ? exchangeId : undefined);
  const [mappedTarget, setMappedTarget] = useState<string | undefined>(initialAction === 'local' ? exchangeId : undefined);
  const [userTarget, setUserTarget] = useState<string | undefined>();
  const [processId, setProcessId] = useState('');
  const [version, setVersion] = useState('');
  const { lang } = useI18n();
  const pins = workspace.background_process_pins ?? [];
  const save = useMutation({
    mutationFn: (next: BackgroundProcessPin[]) => api.saveProjectInputs(workspace.application_id, {
      revision_id: workspace.revision_id, expected_content_sha256: workspace.content_sha256,
      amounts: workspace.demand.map(d => d.amount), values: Object.fromEntries(workspace.fields.map(f => [f.key, f.value])),
      source: workspace.source, demand_mode: workspace.demand_mode, background_process_pins: next,
      ...(workspace.mapped_background_process_pins?.length ? {mapped_background_process_pins: workspace.mapped_background_process_pins.filter(p => p.consumer_exchange_id !== target)} : {}),
      project_background_pins: (workspace.project_background_pins ?? []).filter(p => p.consumer_exchange_id !== target),
    }, lang),
    onSuccess: result => { setTarget(undefined); onSaved(result); },
  });
  const resolve = useMutation({mutationFn: async (selection: {consumer_exchange_id: string; process_uuid: string; version: string}) => ({
    selection, result: await seedProjectsApi.resolveBackground(workspace.application_id, workspace.revision_id, selection),
  })});
  const checked = resolve.data?.selection;
  const verified = checked?.consumer_exchange_id === target && checked?.process_uuid === processId.trim()
    && checked?.version === version.trim() ? resolve.data?.result : undefined;
  const selectedPort = workspace.background_ports?.find(p => p.exchange_id === target);
  // The operator acts inside the dialog, so the refusal has to appear there rather than behind it.
  const saveError = save.isError ? <ErrorState error={save.error} onRetry={isStaleDataVersion(save.error) ? onReload : undefined} /> : null;
  const ports = (workspace.background_ports ?? []).filter(p => !portFilter || portFilter(p));
  const embedded = !!portFilter;
  return <section className="section-panel">
    {!embedded ? <><h2>电力、原料与上游供应</h2><p className="helper-text">选择各项外购投入的供应数据。替换背景数据会生成新版本，已有结果保留。</p></> : null}
    <Table rowKey="exchange_id" pagination={false} data={ports} scroll={{x: 700}} columns={[
      {title: '生产过程', dataIndex: 'process'}, {title: '外购投入', dataIndex: 'label'},
      {title: '背景数据', render: (_, row) => {const pin = pins.find(p => p.consumer_exchange_id === row.exchange_id); const mapped = workspace.mapped_background_process_pins?.find(p => p.consumer_exchange_id === row.exchange_id); const user = workspace.project_background_pins?.find(p => p.consumer_exchange_id === row.exchange_id); return <div className="background-cell">{user ? <>已关联自建供应过程<small className="inventory-linked">项目版本 {user.version} · 部分背景清单</small></> : mapped ? <>已关联本地背景库<small className="inventory-linked">数据库版本 {mapped.database_release} · 部分背景清单</small></> : pin ? <>已关联背景过程<small className="inventory-linked">版本 {pin.version} · 部分背景清单</small></> : row.exact_binding_supported ? '尚未关联' : '模板尚缺上游流映射'}<details className="identity-disclosure"><summary>查看来源</summary><p>投入流 {row.label} · {row.source_namespace} · {row.flow_uuid} · 版本 {row.version}</p>{pin ? <p>背景过程 {pin.process_uuid} · 数据库 {pin.source_namespace}</p> : null}{mapped ? <p>背景过程 {mapped.process_uuid} · 映射包 {mapped.mapping_package_id}@{mapped.mapping_package_version}</p> : null}{user ? <p>自建项目 {user.project_id} · 版本 {user.version} · 图哈希 {user.expected_graph_hash}</p> : null}</details></div>;}},
      {title: '操作', width: 220, render: (_, row) => <><Button type="text" size="small" disabled={save.isPending} onClick={() => setUserTarget(row.exchange_id)}>关联自建供应过程</Button><Button type="text" size="small" disabled={save.isPending} onClick={() => setMappedTarget(row.exchange_id)}>选择本地背景库</Button><Button size="small" disabled={save.isPending} onClick={() => {setTarget(row.exchange_id); setProcessId(''); setVersion(''); resolve.reset(); save.reset();}}>关联背景过程</Button>{pins.some(p => p.consumer_exchange_id === row.exchange_id) ? <Button type="text" disabled={save.isPending} onClick={() => save.mutate(pins.filter(p => p.consumer_exchange_id !== row.exchange_id))}>移除</Button> : null}</>},
    ]} />
    {!embedded ? <p className="helper-text">未关联的投入不包含上游排放。当前结果只能按已覆盖范围解读，不能据此宣称完整产品碳足迹或企业范围 1–3。</p> : null}
    {!target ? saveError : null}
    {!embedded ? <div className="form-actions"><Button type="primary" onClick={onContinue}>查看可计算的分析</Button></div> : null}
    <Modal visible={!!target} title="关联背景过程" onCancel={() => {if (!save.isPending) setTarget(undefined);}} footer={null} maskClosable={!save.isPending} closable={!save.isPending} escToExit={!save.isPending}>
      <p>{selectedPort?.process} · {selectedPort?.label}</p>
      {selectedPort && !selectedPort.exact_binding_supported ? <Alert type="warning" content="此投入使用模板自建流，尚无与上游产品流的正式映射。请在 Nebula LCA 中完成映射并发布新模板；不能仅按流名称关联。" /> : <>
        <p className="helper-text">填写已导入 Nebula LCA 的背景过程 UUID 和精确版本。系统会校验产品流、单位与依赖清单。</p>
        <label className="project-field"><span>背景过程 UUID</span><Input aria-label="背景过程 UUID" disabled={save.isPending} value={processId} onChange={value => {setProcessId(value); resolve.reset();}} /></label>
        <label className="project-field"><span>数据版本</span><Input aria-label="数据版本" disabled={save.isPending} value={version} placeholder="例如 01.00.000" onChange={value => {setVersion(value); resolve.reset();}} /></label>
        <Button disabled={!processId.trim() || !version.trim() || resolve.isPending || save.isPending} loading={resolve.isPending} onClick={() => resolve.mutate({consumer_exchange_id: target!, process_uuid: processId.trim(), version: version.trim()})}>校验背景数据</Button>
        {resolve.isError ? <ErrorState error={resolve.error} /> : null}
        {verified ? <><p>{verified.name} · {verified.pin.version}</p><Alert type="info" content="关联的是部分背景清单，其他未覆盖供应链仍需补齐。" /><Button type="primary" disabled={save.isPending} loading={save.isPending} onClick={() => save.mutate([...pins.filter(p => p.consumer_exchange_id !== target), verified.pin])}>确认关联并保存</Button></> : null}
      </>}
      {saveError}
    </Modal>
    {mappedTarget ? <MappedBackgroundDialog key={`${workspace.revision_id}:${mappedTarget}`} workspace={workspace} consumerId={mappedTarget} onSaved={onSaved} onReload={onReload} onClose={() => setMappedTarget(undefined)} /> : null}
    {userTarget ? <UserProjectBackgroundDialog key={`${workspace.revision_id}:${userTarget}`} workspace={workspace} consumerId={userTarget} onSaved={onSaved} onReload={onReload} onClose={() => setUserTarget(undefined)} /> : null}
  </section>;
}
