import { Alert, Button } from '@arco-design/web-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { handoffStorageKey, modelingApi, type ModelingCandidate, type ModelingResult } from '../api/modeling';
import { PageHeader } from '../components/ui/PageHeader';
import { ErrorState, LoadingState } from '../components/ui/States';

export function parseModelingReturn(params: URLSearchParams, stored: string | null) {
  const id = params.get('handoff_id') ?? '';
  if (!/^[0-9a-f-]{36}$/.test(id)) throw new Error('缺少有效的建模会话，请从专业建模入口重新开始。');
  for (const key of ['handoff_id', 'state', 'project_id', 'saved_version', 'base_version', 'upstream_graph_hash', 'status']) {
    if (params.getAll(key).length > 1) throw new Error('建模返回参数重复，请重新发起。');
  }
  const saved = JSON.parse(stored ?? 'null');
  if (!saved || saved.state !== params.get('state') || typeof saved.confirmation_token !== 'string') throw new Error('请使用发起建模的原浏览器页签返回，当前页签没有匹配的会话。');
  const credentials = {state: saved.state as string, confirmation_token: saved.confirmation_token as string};
  if (params.get('status') === 'cancelled') return {id, credentials, cancelled: true as const};
  if (params.has('status') && params.get('status') !== 'saved') throw new Error('无法识别建模返回状态。');
  const version = params.get('saved_version') ?? '';
  const base = params.get('base_version');
  if (!/^[1-9]\d*$/.test(version) || !Number.isSafeInteger(Number(version)) || (base !== null && (!/^[1-9]\d*$/.test(base) || !Number.isSafeInteger(Number(base))))) throw new Error('保存版本无效，不能使用最新版本替代。');
  const project = params.get('project_id') ?? '', hash = params.get('upstream_graph_hash') ?? '';
  if (!/^[A-Za-z0-9_-]+$/.test(project) || !/^[0-9a-f]{64}$/.test(hash)) throw new Error('返回的模型身份不完整，请重新保存后返回。');
  const candidate: ModelingCandidate = {...credentials, project_id: project, saved_version: Number(version), upstream_graph_hash: hash, ...(base === null ? {} : {base_version: Number(base)})};
  return {id, credentials, candidate, cancelled: false as const};
}

export function ModelingReturnPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate(), client = useQueryClient();
  let value: ReturnType<typeof parseModelingReturn> | undefined, invalid: unknown;
  try { value = parseModelingReturn(params, sessionStorage.getItem(handoffStorageKey(params.get('handoff_id') ?? ''))); } catch (error) { invalid = error; }
  const candidate = value && !value.cancelled ? value.candidate : undefined;
  const preview = useQuery({queryKey: ['modeling-preview', params.toString()], queryFn: () => modelingApi.preview(value!.id, candidate!), enabled: !!candidate, retry: false});
  const open = (result: ModelingResult) => {
    client.invalidateQueries({queryKey: ['applications']});
    navigate(`/applications/${result.application_id}/workbench?model=${result.system_model_id}&revision=${result.revision_id}`);
  };
  const confirm = useMutation({mutationFn: () => modelingApi.confirm(value!.id, candidate!), onSuccess: open});
  const cancel = useMutation({mutationFn: () => modelingApi.cancel(value!.id, value!.credentials), onSuccess: () => {sessionStorage.removeItem(handoffStorageKey(value!.id)); navigate('/');}});
  return <main className="app-page modeling-page"><PageHeader title="确认建模结果" description="核对保存版本，再接入分析项目。" action={<Link to="/">返回首页</Link>} />
    <section className="section-panel">
      {invalid ? <ErrorState error={invalid} /> : value?.cancelled ? <Alert type="info" content="已从建模界面返回，尚未接入任何分析项目。" /> : preview.isLoading ? <LoadingState /> : preview.isError ? <ErrorState error={preview.error} onRetry={() => preview.refetch()} /> : preview.data ? <>
        <h2>{preview.data.name}</h2><p>保存版本 {preview.data.version} · {preview.data.node_count} 个过程节点</p>
        <p>已由算法服务读取并核验此版本。确认后保存独立分析快照，历史项目不变。</p>
        <Alert type="info" content="模型接入后可继续配置分析。产品碳足迹、CBAM 等任务仍需要匹配的方法和核算边界，不会因模型导入而自动具备。" />
        {preview.data.issues.length ? <><Alert type="warning" content={`模型返回 ${preview.data.issues.length} 项提示，请在核算前检查模型数据。`} /><details><summary>查看模型提示</summary><ul>{preview.data.issues.map((issue, index) => <li key={index}>{issue && typeof issue === 'object' && 'message' in issue && typeof issue.message === 'string' ? issue.message : JSON.stringify(issue)}</li>)}</ul></details></> : null}
        <details><summary>模型版本证据</summary><p>{preview.data.project_id}</p><p>上游内容标识：{preview.data.upstream_graph_hash}</p><p>分析快照内容标识：{preview.data.hydrated_graph_sha256}</p></details>
        <div className="form-actions"><Button disabled={confirm.isPending || cancel.isPending || preview.data.status === 'confirmed'} onClick={() => cancel.mutate()}>取消接入</Button><Button type="primary" loading={confirm.isPending} disabled={cancel.isPending} onClick={() => confirm.mutate()}>{preview.data.status === 'confirmed' ? '进入已创建项目' : '确认版本，创建分析项目'}</Button></div>
      </> : null}
      {value?.cancelled ? <Button loading={cancel.isPending} onClick={() => cancel.mutate()}>结束本次建模</Button> : null}
      {confirm.isError ? <ErrorState error={confirm.error} /> : null}{cancel.isError ? <ErrorState error={cancel.error} /> : null}
      {invalid || preview.isError ? <Link to="/modeling">返回专业建模</Link> : null}
    </section>
  </main>;
}
