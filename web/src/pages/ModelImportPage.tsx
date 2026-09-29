import { Alert, Button, Card, Checkbox, Input, InputNumber, Select, Space, Tabs } from '@arco-design/web-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, shortId } from '../api/client';
import type { ModelSource, ModelSourcePreview } from '../api/types';
import { PageHeader } from '../components/ui/PageHeader';
import { EmptyState, ErrorState, LoadingState } from '../components/ui/States';
import { StatusBadge } from '../components/ui/StatusBadge';
import { ModelSourceAuditDrawer } from '../components/ModelSourceAuditDrawer';

const TabPane = Tabs.TabPane;

function PendingSource({ source }: { source: ModelSource }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [candidateIndex, setCandidateIndex] = useState(0);
  const [auditVisible, setAuditVisible] = useState(false);
  const candidate = source.candidate_versions[candidateIndex];
  const attach = useMutation({
    mutationFn: () => api.attachModelSource(source.id, candidate.project_id, candidate.version),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['model-sources', source.application_id] });
      queryClient.invalidateQueries({ queryKey: ['models', source.application_id] });
      navigate(`/applications/${source.application_id}/workbench?model=${result.system_model.id}`);
    },
  });
  return (
    <Card className="model-source-record" bordered>
      <div className="model-source-record__head">
        <div><strong>{source.name}</strong><small>{source.source_type === 'tidas_bundle' ? 'TIDAS 交换包' : 'Nebula 原生备份'}</small></div>
        <StatusBadge status={source.status} />
      </div>
      {source.external_dependencies.length ? <Alert type="warning" content={`检测到 ${source.external_dependencies.length} 项外部依赖；可以浏览，依赖补齐前不能求解。`} /> : null}
      <label className="model-source-field">
        <span>选择精确版本</span>
        <Select value={candidateIndex} onChange={setCandidateIndex} disabled={attach.isPending}>
          {source.candidate_versions.map((item, index) => (
            <Select.Option key={`${item.project_id}:${item.version}`} value={index}>
              {item.project_id} · v{item.version} · {shortId(item.graph_hash)}
            </Select.Option>
          ))}
        </Select>
      </label>
      {attach.isError ? <ErrorState error={attach.error} onRetry={() => attach.mutate()} /> : null}
      <div className="form-actions"><Button onClick={() => setAuditVisible(true)}>查看审计</Button><Button type="primary" loading={attach.isPending} disabled={!candidate} onClick={() => attach.mutate()}>挂载所选版本</Button></div>
      <ModelSourceAuditDrawer value={source} visible={auditVisible} onClose={() => setAuditVisible(false)} />
    </Card>
  );
}

interface PackagePanelProps {
  kind: 'tidas' | 'native';
  applicationId: string;
  providerReady: boolean;
}

function PackageImportPanel({ kind, applicationId, providerReady }: PackagePanelProps) {
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [preview, setPreview] = useState<ModelSourcePreview | null>(null);
  const [auditVisible, setAuditVisible] = useState(false);
  const previewMutation = useMutation({
    mutationFn: () => kind === 'tidas' ? api.previewTidasBundle(file!) : api.inspectNativeBundle(file!),
    onSuccess: setPreview,
  });
  const importMutation = useMutation({
    mutationFn: () => kind === 'tidas'
      ? api.importTidasBundle(applicationId, file!, name, preview!.preview_sha256)
      : api.restoreNativeBundle(applicationId, file!, name, preview!.preview_sha256, 'rename'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['model-sources', applicationId] });
      setConfirmed(false);
    },
  });
  const accept = kind === 'tidas' ? '.zip' : '.nebula.zip';
  const title = kind === 'tidas' ? '导入 TIDAS 包' : '恢复 Nebula 项目备份';
  const explanation = kind === 'tidas'
    ? '先由 Nebula LCA 执行 dry-run，确认 Flow、Process、模型拓扑和过滤项后再正式导入。'
    : '先在本地核验 manifest、文件哈希、路径和解压上限，再由 Nebula LCA 事务性恢复。';
  const ready = Boolean(file && preview?.status === 'ready' && name.trim() && confirmed && providerReady);
  return (
    <section className="model-source-panel">
      <p>{explanation}</p>
      {!providerReady ? <Alert type="warning" content={`当前 Nebula LCA API 未提供${kind === 'tidas' ? ' TIDAS bundle import' : ' native bundle restore'} 合同。`} /> : null}
      <label className="model-source-field"><span>模型名称</span><Input value={name} maxLength={255} onChange={setName} placeholder="导入后在 Nebula One 中显示的名称" /></label>
      <label className="model-source-field">
        <span>模型包</span>
        <input type="file" accept={accept} disabled={!providerReady || previewMutation.isPending || importMutation.isPending} onChange={(event) => {
          setFile(event.target.files?.[0] ?? null); setPreview(null); setConfirmed(false);
        }} />
      </label>
      <Space wrap>
        <Button disabled={!file || !providerReady} loading={previewMutation.isPending} onClick={() => previewMutation.mutate()}>检查兼容性</Button>
        {preview ? <StatusBadge status={preview.status} /> : null}
        {preview ? <Button type="text" onClick={() => setAuditVisible(true)}>查看检查回执</Button> : null}
      </Space>
      {preview?.issues.length ? <Alert type={preview.status === 'blocked' ? 'error' : 'warning'} content={`检查发现 ${preview.issues.length} 项问题，请在审计回执中确认。`} /> : null}
      {preview?.external_dependencies.length ? <Alert type="warning" content={`包内记录 ${preview.external_dependencies.length} 项未再分发的外部依赖。`} /> : null}
      {previewMutation.isError ? <ErrorState error={previewMutation.error} onRetry={() => previewMutation.mutate()} /> : null}
      {importMutation.isError ? <ErrorState error={importMutation.error} onRetry={() => importMutation.mutate()} /> : null}
      <Checkbox checked={confirmed} disabled={!preview || preview.status !== 'ready'} onChange={setConfirmed}>
        我确认正式操作会写入当前连接的 Nebula LCA 数据库
      </Checkbox>
      <div className="form-actions"><Button type="primary" status={kind === 'native' ? 'warning' : undefined} disabled={!ready} loading={importMutation.isPending} onClick={() => importMutation.mutate()}>{title}</Button></div>
      {preview ? <ModelSourceAuditDrawer value={preview} visible={auditVisible} onClose={() => setAuditVisible(false)} /> : null}
    </section>
  );
}

export function ModelImportPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const applications = useQuery({ queryKey: ['applications'], queryFn: () => api.applications() });
  const engine = useQuery({ queryKey: ['engine'], queryFn: api.engine });
  const [applicationId, setApplicationId] = useState('');
  const activeApplicationId = applicationId || applications.data?.[0]?.id || '';
  const sources = useQuery({
    queryKey: ['model-sources', activeApplicationId],
    queryFn: () => api.modelSources(activeApplicationId),
    enabled: Boolean(activeApplicationId),
  });
  const [projectName, setProjectName] = useState('');
  const [projectId, setProjectId] = useState('');
  const [version, setVersion] = useState<number | undefined>();
  const connect = useMutation({
    mutationFn: () => api.connectNebulaProject(activeApplicationId, { name: projectName, upstream_project_id: projectId, upstream_version: version! }),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['model-sources', activeApplicationId] });
      queryClient.invalidateQueries({ queryKey: ['models', activeApplicationId] });
      navigate(`/applications/${activeApplicationId}/workbench?model=${result.system_model.id}`);
    },
  });
  const providerReady = engine.data?.status === 'ready';
  const directReady = Boolean(providerReady && engine.data?.contracts.provider_model_snapshot && engine.data?.contracts.exact_model_version);
  const tidasReady = Boolean(providerReady && engine.data?.contracts.tidas_bundle_import);
  const nativeReady = Boolean(providerReady && engine.data?.contracts.native_bundle_restore);
  const pendingSources = useMemo(() => sources.data?.filter((item) => item.status === 'ready_to_attach') ?? [], [sources.data]);
  return (
    <main className="app-page page-grid">
      <PageHeader title="导入模型" description="三种来源统一固定为 SystemModel；建模、导入恢复和求解均由 Nebula LCA API 提供。" />
      {engine.isLoading || applications.isLoading ? <section className="section-panel"><LoadingState rows={3} /></section> : null}
      {engine.isError ? <ErrorState error={engine.error} onRetry={() => engine.refetch()} /> : null}
      {applications.isError ? <ErrorState error={applications.error} onRetry={() => applications.refetch()} /> : null}
      {!providerReady && !engine.isLoading ? <Alert type="error" title="Nebula LCA API 未就绪" content="导入和挂载已禁用。请启动算法服务并检查 NEBULA_LCA_BASE_URL。" /> : null}
      <section className="section-panel model-source-context">
        <label className="model-source-field"><span>目标应用</span><Select value={activeApplicationId || undefined} placeholder="选择应用" onChange={setApplicationId}>{applications.data?.map((item) => <Select.Option key={item.id} value={item.id}>{item.name}</Select.Option>)}</Select></label>
      </section>
      {applications.data?.length === 0 ? <section className="section-panel"><EmptyState description="请先创建或实例化一个应用，再导入模型。" /></section> : null}
      {activeApplicationId ? <section className="section-panel">
        <Tabs defaultActiveTab="project">
          <TabPane key="project" title="连接现有 Nebula 项目">
            <div className="model-source-panel">
              <p>填写精确项目 ID 和版本。系统不会读取 latest，也不会猜测版本。</p>
              <label className="model-source-field"><span>模型名称</span><Input value={projectName} onChange={setProjectName} /></label>
              <div className="model-source-pin-grid">
                <label className="model-source-field"><span>项目 ID</span><Input value={projectId} onChange={setProjectId} /></label>
                <label className="model-source-field"><span>版本</span><InputNumber min={1} precision={0} value={version} onChange={(value) => setVersion(value ?? undefined)} /></label>
              </div>
              {connect.isError ? <ErrorState error={connect.error} onRetry={() => connect.mutate()} /> : null}
              {!directReady ? <Alert type="warning" content="当前 Nebula LCA API 未提供精确模型快照合同。" /> : null}
              <div className="form-actions"><Button type="primary" disabled={!directReady || !projectName.trim() || !projectId.trim() || !version} loading={connect.isPending} onClick={() => connect.mutate()}>连接并固定版本</Button></div>
            </div>
          </TabPane>
          <TabPane key="tidas" title="导入 TIDAS 包"><PackageImportPanel kind="tidas" applicationId={activeApplicationId} providerReady={tidasReady} /></TabPane>
          <TabPane key="native" title="恢复 Nebula 项目备份"><PackageImportPanel kind="native" applicationId={activeApplicationId} providerReady={nativeReady} /></TabPane>
        </Tabs>
      </section> : null}
      {activeApplicationId ? <section className="section-panel">
        <div className="section-heading"><h2>等待选择版本</h2><span className="helper-text">刷新页面后仍可继续</span></div>
        {sources.isLoading ? <LoadingState rows={2} /> : null}
        {sources.isError ? <ErrorState error={sources.error} onRetry={() => sources.refetch()} /> : null}
        {!sources.isLoading && pendingSources.length === 0 ? <EmptyState description="没有待挂载的导入或恢复记录" /> : null}
        <div className="model-source-list">{pendingSources.map((source) => <PendingSource key={source.id} source={source} />)}</div>
      </section> : null}
    </main>
  );
}
