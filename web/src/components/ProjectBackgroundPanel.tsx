import { Alert, Button, Input, Modal, Table } from '@arco-design/web-react';
import { useMutation } from '@tanstack/react-query';
import { useEffect, useState, type ReactNode } from 'react';
import { api, isStaleDataVersion } from '../api/client';
import { seedProjectsApi } from '../api/seedProjects';
import type { BackgroundProcessPin, ProjectWorkspace } from '../api/types';
import { useI18n } from '../i18n';
import { ErrorState } from './ui/States';
import { MappedBackgroundDialog } from './MappedBackgroundDialog';
import { UserProjectBackgroundDialog } from './UserProjectBackgroundDialog';

type BackgroundPort = NonNullable<ProjectWorkspace['background_ports']>[number];
function InlinePicker({ children }: { children?: ReactNode }) { return <div className="background-picker-body">{children}</div>; }

export function ProjectBackgroundPanel({workspace, onSaved, onContinue, onReload, portFilter, exchangeId, initialAction, onClose, onBusyChange}: {
  workspace: ProjectWorkspace; onSaved: (workspace: ProjectWorkspace) => void; onContinue?: () => void; onReload: () => void;
  portFilter?: (port: BackgroundPort) => boolean; exchangeId?: string; initialAction?: 'external' | 'local';
  onClose?: () => void; onBusyChange?: (busy: boolean) => void;
}) {
  const [target, setTarget] = useState<string | undefined>(initialAction === 'external' ? exchangeId : undefined);
  const [mappedTarget, setMappedTarget] = useState<string | undefined>(initialAction === 'local' ? exchangeId : undefined);
  const [userTarget, setUserTarget] = useState<string | undefined>();
  const [processId, setProcessId] = useState('');
  const [version, setVersion] = useState('');
  const { lang, t } = useI18n();
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
  useEffect(() => { onBusyChange?.(save.isPending); }, [onBusyChange, save.isPending]);
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
  const Picker = embedded ? InlinePicker : Modal;
  return <section className={embedded ? 'background-exact-picker' : 'section-panel'}>
    {!embedded ? <><h2>电力、原料与上游供应</h2><p className="helper-text">选择各项外购投入的供应数据。替换背景数据会生成新版本，已有结果保留。</p></> : null}
    {!embedded ? <Table rowKey="exchange_id" pagination={false} data={ports} scroll={{x: 700}} columns={[
      {title: '生产过程', dataIndex: 'process'}, {title: '外购投入', dataIndex: 'label'},
      {title: '背景数据', render: (_, row) => {const pin = pins.find(p => p.consumer_exchange_id === row.exchange_id); const mapped = workspace.mapped_background_process_pins?.find(p => p.consumer_exchange_id === row.exchange_id); const user = workspace.project_background_pins?.find(p => p.consumer_exchange_id === row.exchange_id); return <div className="background-cell">{user ? <>已关联自建供应过程<small className="inventory-linked">项目版本 {user.version} · 部分背景清单</small></> : mapped ? <>已关联本地背景库<small className="inventory-linked">数据库版本 {mapped.database_release} · 部分背景清单</small></> : pin ? <>已关联背景过程<small className="inventory-linked">版本 {pin.version} · 部分背景清单</small></> : row.exact_binding_supported ? '尚未关联' : '模板尚缺上游流映射'}<details className="identity-disclosure"><summary>查看来源</summary><p>投入流 {row.label} · {row.source_namespace} · {row.flow_uuid} · 版本 {row.version}</p>{pin ? <p>背景过程 {pin.process_uuid} · 数据库 {pin.source_namespace}</p> : null}{mapped ? <p>背景过程 {mapped.process_uuid} · 映射包 {mapped.mapping_package_id}@{mapped.mapping_package_version}</p> : null}{user ? <p>自建项目 {user.project_id} · 版本 {user.version} · 图哈希 {user.expected_graph_hash}</p> : null}</details></div>;}},
      {title: '操作', width: 220, fixed: 'right' as const, render: (_, row) => <><Button type="text" size="small" disabled={save.isPending} onClick={() => setUserTarget(row.exchange_id)}>关联自建供应过程</Button><Button type="text" size="small" disabled={save.isPending} onClick={() => setMappedTarget(row.exchange_id)}>选择本地背景库</Button><Button size="small" disabled={save.isPending} onClick={() => {setTarget(row.exchange_id); setProcessId(''); setVersion(''); resolve.reset(); save.reset();}}>关联背景过程</Button>{pins.some(p => p.consumer_exchange_id === row.exchange_id) ? <Button type="text" disabled={save.isPending} onClick={() => save.mutate(pins.filter(p => p.consumer_exchange_id !== row.exchange_id))}>移除</Button> : null}</>},
    ]} /> : null}
    {!embedded ? <p className="helper-text">未关联的投入不包含上游排放。当前结果只能按已覆盖范围解读，不能据此宣称完整产品碳足迹或企业范围 1–3。</p> : null}
    {!target ? saveError : null}
    {!embedded ? <div className="form-actions"><Button type="primary" onClick={onContinue}>查看可计算的分析</Button></div> : null}
    <Picker visible={!!target} title="关联背景过程" onCancel={() => {if (!save.isPending) setTarget(undefined);}} footer={null} maskClosable={!save.isPending} closable={!save.isPending} escToExit={!save.isPending}>
      {!embedded ? <p>{selectedPort?.process} · {selectedPort?.label}</p> : null}
      {selectedPort && !selectedPort.exact_binding_supported ? <p>{t('background.mappingMissing')}</p> : <>
        <p className="helper-text">{t('background.exactNote')}</p>
        <label className="project-field"><span>{t('background.processUuid')}</span><Input aria-label={t('background.processUuid')} disabled={save.isPending} value={processId} onChange={value => {setProcessId(value); resolve.reset();}} /></label>
        <label className="project-field"><span>{t('background.dataVersion')}</span><Input aria-label={t('background.dataVersion')} disabled={save.isPending} value={version} placeholder="01.00.000" onChange={value => {setVersion(value); resolve.reset();}} /></label>
        <Button disabled={!processId.trim() || !version.trim() || resolve.isPending || save.isPending} loading={resolve.isPending} onClick={() => resolve.mutate({consumer_exchange_id: target!, process_uuid: processId.trim(), version: version.trim()})}>{t('background.validateData')}</Button>
        {resolve.isError ? <ErrorState error={resolve.error} /> : null}
        {verified ? <><p>{verified.name} · {verified.pin.version}</p>{!embedded ? <Button type="primary" disabled={save.isPending} loading={save.isPending} onClick={() => save.mutate([...pins.filter(p => p.consumer_exchange_id !== target), verified.pin])}>{t('background.linkConfirm')}</Button> : null}</> : null}
      </>}
      {saveError}
      {embedded && pins.some(pin => pin.consumer_exchange_id === target) ? <Button disabled={save.isPending} onClick={() => save.mutate(pins.filter(pin => pin.consumer_exchange_id !== target))}>{t('background.remove')}</Button> : null}
    </Picker>
    {embedded ? <div className="background-picker-footer"><Button disabled={save.isPending} onClick={onClose}>{t('background.cancel')}</Button><Button type="primary" disabled={!verified || save.isPending} loading={save.isPending} onClick={() => save.mutate([...pins.filter(p => p.consumer_exchange_id !== target), verified!.pin])}>{t('background.linkConfirm')}</Button></div> : null}
    {mappedTarget ? <MappedBackgroundDialog key={`${workspace.revision_id}:${mappedTarget}`} workspace={workspace} consumerId={mappedTarget} onSaved={onSaved} onReload={onReload} onClose={() => setMappedTarget(undefined)} /> : null}
    {userTarget ? <UserProjectBackgroundDialog key={`${workspace.revision_id}:${userTarget}`} workspace={workspace} consumerId={userTarget} onSaved={onSaved} onReload={onReload} onClose={() => setUserTarget(undefined)} /> : null}
  </section>;
}
