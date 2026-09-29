import { Alert, Button, InputNumber } from '@arco-design/web-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { api, formatDate } from '../api/client';
import type { Application } from '../api/types';
import { PageHeader } from '../components/ui/PageHeader';
import { EmptyState, ErrorState, LoadingState } from '../components/ui/States';

export function ProfessionalProjectPage({application}: {application: Application}) {
  const [params] = useSearchParams();
  const navigate = useNavigate(), client = useQueryClient();
  const models = useQuery({queryKey: ['models', application.id], queryFn: () => api.models(application.id)});
  const modelId = params.get('model') ?? models.data?.[0]?.id;
  const model = models.data?.find(m => m.id === modelId);
  const source = application.context.modeling_source as Record<string, unknown> | undefined;
  const matchesSource = !!model && !!source && model.upstream_project_id === source.project_id && model.upstream_version === source.version;
  const revisions = useQuery({queryKey: ['revisions', modelId], queryFn: () => api.revisions(modelId!), enabled: !!model});
  const revision = revisions.data?.find(r => r.id === (params.get('revision') ?? model?.upstream_receipt.base_revision_id));
  const snapshots = useQuery({queryKey: ['solved-snapshots', application.id], queryFn: () => api.solvedSnapshots(application.id)});
  const raw = application.context.modeling_functional_unit;
  const unit = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {};
  const demandValid = typeof unit.flow_uuid === 'string' && !!unit.flow_uuid && typeof unit.unit === 'string' && !!unit.unit && typeof unit.amount === 'number' && Number.isFinite(unit.amount) && unit.amount > 0;
  const [amount, setAmount] = useState(demandValid ? unit.amount as number : undefined);
  const solve = useMutation({mutationFn: () => api.solveAndFreeze(application.id, revision!.id, {demand: [{reference_flow_uuid: unit.flow_uuid as string, unit: unit.unit as string, amount: amount!}], idempotency_key: `modeling-${revision!.id}-${amount}`}), onSuccess: result => {client.invalidateQueries({queryKey: ['solved-snapshots', application.id]}); navigate(`/applications/${application.id}/results?snapshot=${result.id}&view=mfa`);}});
  const error = models.error || revisions.error;
  return <main className="app-page modeling-page"><PageHeader title={application.name} description="使用已保存的工艺模型进行分析。" action={<Link to="/applications">我的项目</Link>} />
    {models.isLoading || revisions.isLoading ? <LoadingState /> : error ? <ErrorState error={error} /> : !model || !revision || !matchesSource ? <Alert type="error" content="所选模型或数据版本不属于本项目，请返回项目列表重新进入。" /> : <section className="section-panel modeling-start">
      <div className="section-heading"><h2>模型与核算规模</h2><Link to={`/modeling?application=${application.id}&model=${model.id}&revision=${revision.id}&launch=1`} target="_blank" rel="noopener noreferrer">另建工艺模型</Link></div>
      <p>{model.name} · Nebula LCA 版本 {model.upstream_version}</p>
      {demandValid ? <label className="project-field"><span>核算规模 · {unit.unit as string}</span><InputNumber aria-label="核算规模" value={amount} min={Number.EPSILON} onChange={setAmount} /></label> : <Alert type="warning" content="模型尚未声明完整的参考产品、数量和单位，请在专业建模中补齐后另存版本。" />}
      <p className="helper-text">参考产品信息完整后可计算物质流。产品碳足迹、CBAM 和企业碳清单还需绑定对应方法与核算边界。</p>
      <div className="form-actions"><Button type="primary" disabled={!demandValid || !amount || !Number.isFinite(amount) || amount <= 0} loading={solve.isPending} onClick={() => solve.mutate()}>计算物质流</Button></div>
      {solve.isError ? <ErrorState error={solve.error} /> : null}
    </section>}
    <section className="section-panel"><h2>历史结果</h2>{snapshots.isLoading ? <LoadingState /> : snapshots.isError ? <ErrorState error={snapshots.error} /> : !snapshots.data?.length ? <EmptyState description="还没有计算结果" /> : snapshots.data.map(s => <Link className="home-project-row" key={s.id} to={`/applications/${application.id}/results?snapshot=${s.id}&view=mfa`}><strong>物质流分析</strong><span>{formatDate(s.created_at)} →</span></Link>)}</section>
  </main>;
}
