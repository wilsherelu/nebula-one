import { Alert, Button, Checkbox, Form, Input, InputNumber, Select, Table, Tabs, Message } from '@arco-design/web-react';
import { IconArrowLeft, IconFile, IconPlayArrow } from '@arco-design/web-react/icon';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { api, formatDate, shortId } from '../api/client';
import type { ComparisonExecuteRequest, MethodPackage } from '../api/types';
import { RevisionLineage } from '../components/RevisionLineage';
import { PageHeader } from '../components/ui/PageHeader';
import { StatusBadge } from '../components/ui/StatusBadge';
import { EmptyState, ErrorState, LoadingState, NotFoundState } from '../components/ui/States';

interface FormValues {
  comparison_id: string;
  baseline_scenario_id: string;
  reference_flow_uuid: string;
  amount: number;
  unit: string;
  unit_group_uuid?: string;
  unit_group_version?: string;
  lcia_methods?: string;
}

function methodPackageRefs(context: Record<string, unknown> | undefined): string[] {
  const values = context?.method_package_refs;
  return Array.isArray(values)
    ? values.filter((value): value is string => typeof value === 'string' && value.trim().length > 0)
    : [];
}

function methodPackageReference(item: MethodPackage): string {
  return `${item.package_id}@${item.version}`;
}

function packageLciaMethod(item: MethodPackage): string | undefined {
  const formulaGraph = item.manifest.formula_graph;
  if (!formulaGraph || typeof formulaGraph !== 'object') return undefined;
  const method = (formulaGraph as Record<string, unknown>).lcia_method;
  return typeof method === 'string' && method.trim() ? method.trim() : undefined;
}

export function ScenariosPage() {
  const { applicationId } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [form] = Form.useForm<FormValues>();
  const draftKey = `nebula-one:comparison-draft:${applicationId ?? 'unknown'}`;
  const savedDraft = useMemo<Partial<FormValues>>(() => {
    try {
      return JSON.parse(localStorage.getItem(draftKey) ?? '{}') as Partial<FormValues>;
    } catch {
      return {};
    }
  }, [draftKey]);
  const watched = Form.useWatch(['comparison_id', 'baseline_scenario_id', 'reference_flow_uuid', 'amount', 'unit'], form) as Partial<FormValues>;
  const [selectedComparison, setSelectedComparison] = useState(searchParams.get('comparison') ?? savedDraft.comparison_id ?? '');
  const [lciaMethods, setLciaMethods] = useState('');
  const [selectedCapabilities, setSelectedCapabilities] = useState<string[]>([]);
  const application = useQuery({ queryKey: ['application', applicationId], queryFn: () => api.application(applicationId!), enabled: Boolean(applicationId) });
  const boundMethodPackageRefs = useMemo(() => methodPackageRefs(application.data?.context), [application.data?.context]);
  const methodPackages = useQuery({
    queryKey: ['method-packages', applicationId],
    queryFn: () => api.methodPackages(),
    enabled: boundMethodPackageRefs.length > 0,
  });
  const capabilities = useQuery({ queryKey: ['capabilities'], queryFn: api.capabilities });
  const casepacks = useQuery({ queryKey: ['casepacks'], queryFn: api.casepacks });
  const models = useQuery({ queryKey: ['models', applicationId], queryFn: () => api.models(applicationId!), enabled: Boolean(applicationId) });
  const scenarios = useQuery({ queryKey: ['scenarios', applicationId], queryFn: () => api.scenarios(applicationId!), enabled: Boolean(applicationId) });
  const comparisons = useQuery({ queryKey: ['comparisons', applicationId], queryFn: () => api.comparisons(applicationId!), enabled: Boolean(applicationId) });
  const runs = useQuery({ queryKey: ['comparison-runs', applicationId], queryFn: () => api.comparisonRuns(applicationId!), enabled: Boolean(applicationId) });
  const modelId = searchParams.get('model') ?? models.data?.[0]?.id ?? '';
  const revisions = useQuery({ queryKey: ['revisions', modelId], queryFn: () => api.revisions(modelId), enabled: Boolean(modelId) });
  const solvedSnapshots = useQuery({ queryKey: ['solved-snapshots', applicationId], queryFn: () => api.solvedSnapshots(applicationId!), enabled: Boolean(applicationId) });
  const casePackId = typeof application.data?.context.case_pack_id === 'string' ? application.data.context.case_pack_id : '';
  const resolvedCaseHash = typeof application.data?.context.resolved_case_sha256 === 'string' ? application.data.context.resolved_case_sha256 : '';
  const selectedCasePack = casepacks.data?.items.find((item) => item.id === casePackId);
  const selectedCase = selectedCasePack?.applications.find((item) => item.resolved_case_sha256 === resolvedCaseHash);
  const selectedModule = selectedCasePack?.showcase?.modules.find((item) => (
    item.key === searchParams.get('module') && item.application_case_id === selectedCase?.id
  ));
  const resultPath = (snapshotId: string) => {
    const params = new URLSearchParams({ snapshot: snapshotId });
    if (selectedModule) params.set('view', selectedModule.key);
    return `/applications/${applicationId}/results?${params}`;
  };
  const latestRevision = useMemo(() => [...(revisions.data ?? [])].sort((left, right) => right.revision_number - left.revision_number)[0], [revisions.data]);
  const comparison = comparisons.data?.find((item) => item.id === selectedComparison);
  const comparisonScenarios = useMemo(() => scenarios.data?.filter((scenario) => comparison?.scenario_ids.includes(scenario.id)) ?? [], [comparison, scenarios.data]);
  const boundPcfPackages = useMemo(() => (methodPackages.data ?? []).filter((item) => (
    item.package_kind === 'product_carbon_footprint' && boundMethodPackageRefs.includes(methodPackageReference(item))
  )), [boundMethodPackageRefs, methodPackages.data]);
  const boundPcfLciaMethods = useMemo(() => [...new Set(boundPcfPackages.flatMap((item) => {
    const method = packageLciaMethod(item);
    return method ? [method] : [];
  }))], [boundPcfPackages]);
  const pcfPackagesComplete = boundPcfPackages.length > 0 && boundPcfPackages.every((item) => Boolean(packageLciaMethod(item)));
  const formReady = Boolean(watched.comparison_id && watched.baseline_scenario_id && watched.reference_flow_uuid?.trim() && watched.amount && watched.amount > 0 && watched.unit?.trim());

  useEffect(() => {
    if (!selectedComparison && comparisons.data?.length) {
      const first = comparisons.data[0].id;
      setSelectedComparison(first);
      form.setFieldValue('comparison_id', first);
    }
  }, [comparisons.data, form, selectedComparison]);

  useEffect(() => {
    if (!selectedCase) return;
    setSelectedCapabilities(selectedCase.capabilities.filter((item) => item === 'mfa.solved.v1' || item === 'lcia.nebula.v1' || item === 'pcf.product.v1'));
  }, [selectedCase]);

  useEffect(() => {
    if (!searchParams.get('model') && models.data?.[0]) {
      const next = new URLSearchParams(searchParams);
      next.set('model', models.data[0].id);
      setSearchParams(next, { replace: true });
    }
  }, [models.data, searchParams, setSearchParams]);

  const execute = useMutation({
    mutationFn: ({ comparisonId, payload }: { comparisonId: string; payload: ComparisonExecuteRequest }) => api.executeComparison(comparisonId, payload),
    onSuccess: async (run) => {
      await queryClient.invalidateQueries({ queryKey: ['comparison-runs', applicationId] });
      Message.success('情景比较已完成');
      navigate(`/comparison-runs/${run.id}`);
    },
  });
  const solve = useMutation({
    mutationFn: async () => {
      if (!applicationId || !latestRevision || !selectedCase) throw new Error('案例、模型 revision 或结构化需求尚未就绪。');
      const manualMethods = selectedCapabilities.includes('lcia.nebula.v1') ? lciaMethods.split(',').map((item) => item.trim()).filter(Boolean) : [];
      if (selectedCapabilities.includes('pcf.product.v1') && !pcfPackagesComplete) {
        throw new Error('产品碳足迹方法包未完整绑定核算方法，不能启动求解。');
      }
      const methods = [...new Set([...manualMethods, ...boundPcfLciaMethods])];
      return api.solveAndFreeze(applicationId, latestRevision.id, {
        demand: selectedCase.demand.map((item) => ({
          reference_flow_uuid: String(item.reference_flow_uuid ?? ''),
          amount: Number(item.amount),
          unit: String(item.unit ?? ''),
          ...(typeof item.unit_group_uuid === 'string' ? { unit_group_uuid: item.unit_group_uuid } : {}),
          ...(typeof item.unit_group_version === 'string' ? { unit_group_version: item.unit_group_version } : {}),
        })),
        idempotency_key: `case-${selectedCase.resolved_case_sha256.slice(0, 20)}-${latestRevision.content_sha256.slice(0, 20)}`,
        ...(methods.length ? { lcia_methods: methods } : {}),
      });
    },
    onSuccess: async (snapshot) => {
      await queryClient.invalidateQueries({ queryKey: ['solved-snapshots', applicationId] });
      Message.success('分析完成，结果快照已冻结');
      navigate(resultPath(snapshot.id));
    },
  });

  if (!applicationId) return <NotFoundState />;
  const loading = application.isLoading || models.isLoading || scenarios.isLoading || comparisons.isLoading || casepacks.isLoading;
  const error = application.error || models.error || scenarios.error || comparisons.error || casepacks.error;
  const requiresLciaMethod = selectedCapabilities.includes('lcia.nebula.v1');
  const requiresManualLciaMethod = requiresLciaMethod && boundPcfLciaMethods.length === 0;
  const requiresPcfMethod = selectedCapabilities.includes('pcf.product.v1');
  const pcfMethodIncomplete = requiresPcfMethod && (!boundMethodPackageRefs.length || !pcfPackagesComplete);
  const pcfMethodUnavailable = requiresPcfMethod && (methodPackages.isLoading || methodPackages.isError || pcfMethodIncomplete);
  const solveReady = Boolean(selectedCase && latestRevision && selectedCase.demand.length && selectedCapabilities.length && (!requiresManualLciaMethod || lciaMethods.trim()) && !pcfMethodUnavailable);
  const onSubmit = (values: FormValues) => {
    const payload: ComparisonExecuteRequest = {
      baseline_scenario_id: values.baseline_scenario_id,
      demand: [{
        reference_flow_uuid: values.reference_flow_uuid.trim(),
        amount: values.amount,
        unit: values.unit.trim(),
        ...(values.unit_group_uuid?.trim() ? { unit_group_uuid: values.unit_group_uuid.trim() } : {}),
        ...(values.unit_group_version?.trim() ? { unit_group_version: values.unit_group_version.trim() } : {}),
      }],
      ...(values.lcia_methods?.trim() ? { lcia_methods: values.lcia_methods.split(',').map((item) => item.trim()).filter(Boolean) } : {}),
    };
    execute.mutate({ comparisonId: values.comparison_id, payload });
  };

  return (
    <main className="app-page">
      <PageHeader
        title={application.data?.name ?? '情景工作台'}
        description="配置本次核算，或查看已完成的分析结果。"
        action={<Button icon={<IconArrowLeft />} onClick={() => navigate('/applications')}>返回应用</Button>}
      />
      {loading ? <section className="section-panel"><LoadingState rows={7} /></section> : null}
      {error ? <ErrorState error={error} onRetry={() => { application.refetch(); models.refetch(); scenarios.refetch(); comparisons.refetch(); casepacks.refetch(); }} /> : null}
      {!loading && !error ? (
        <Tabs activeTab={searchParams.get('step') ?? 'analysis'} onChange={(step) => { const next = new URLSearchParams(searchParams); next.set('step', step); setSearchParams(next); }} className="workbench-tabs">
          <Tabs.TabPane key="analysis" title="分析运行">
            <div className="workbench-grid">
              <section className="section-panel analysis-launcher">
                <div className="section-heading"><h2>{selectedCase?.title ?? '案例分析'}</h2>{selectedCase ? <StatusBadge status={selectedCase.study_frame_status} /> : null}</div>
                {!selectedCase ? <Alert type="warning" content="该应用没有匹配到精确 resolved-case hash，不能从案例声明推断需求或分析能力。" /> : (
                  <>
                    <div className="analysis-launcher__capabilities"><span>本次模块</span><Checkbox.Group value={selectedCapabilities} onChange={(values) => setSelectedCapabilities(values.map(String))} options={selectedCase.capabilities.filter((item) => item === 'mfa.solved.v1' || item === 'lcia.nebula.v1' || item === 'pcf.product.v1').map((item) => ({ label: capabilities.data?.items.find((entry) => entry.key === item)?.name ?? '分析名称暂不可用', value: item }))} /></div>
                    <dl className="casepack-facts">
                      <div><dt>核算边界</dt><dd>{selectedCase.study_frame_title}</dd></div>
                      <div><dt>冻结 revision</dt><dd>{latestRevision ? `r${latestRevision.revision_number}` : '尚未绑定'}</dd></div>
                      <div><dt>需求</dt><dd>{selectedCase.demand.map((item) => `${item.amount ?? '—'} ${item.unit ?? ''}`).join(' + ')}</dd></div>
                    </dl>
                    {requiresLciaMethod ? <label className="analysis-launcher__method"><span>{boundPcfLciaMethods.length ? '额外 LCIA 方法（可选）' : 'LCIA 方法'}</span><Input value={lciaMethods} onChange={setLciaMethods} placeholder={boundPcfLciaMethods.length ? '如需增加其他方法，可用英文逗号分隔' : '输入算法层支持的方法；多个方法用英文逗号分隔'} /></label> : null}
                    {requiresPcfMethod && methodPackages.isLoading ? <Alert type="info" content="正在校验产品碳足迹方法包…" /> : null}
                    {requiresPcfMethod && methodPackages.isError ? <ErrorState error={methodPackages.error} onRetry={() => methodPackages.refetch()} /> : null}
                    {requiresPcfMethod && !methodPackages.isLoading && !methodPackages.isError && pcfMethodIncomplete ? <Alert type="error" title="产品碳足迹暂不可运行" content="当前应用没有精确绑定可执行的产品碳足迹方法包，或方法包未声明核算方法。" /> : null}
                    {requiresPcfMethod && !pcfMethodUnavailable ? <p className="helper-text">核算方法：{boundPcfLciaMethods.join('、')}</p> : null}
                    {solve.isError ? <ErrorState error={solve.error} /> : null}
                    <p className="helper-text">运行后保存当前版本的结果，可用于对比、追溯和报告导出。</p>
                    <div className="form-actions"><Button type="primary" icon={<IconPlayArrow />} loading={solve.isPending} disabled={!solveReady || solve.isPending} onClick={() => solve.mutate()}>运行并冻结结果</Button></div>
                  </>
                )}
              </section>
              <section className="section-panel analysis-output-summary">
                <div className="section-heading"><h2>已有结果</h2><span className="helper-text">{solvedSnapshots.data?.length ?? 0} 个快照</span></div>
                {solvedSnapshots.isLoading ? <LoadingState /> : solvedSnapshots.isError ? <ErrorState error={solvedSnapshots.error} onRetry={() => solvedSnapshots.refetch()} /> : solvedSnapshots.data?.length ? solvedSnapshots.data.slice(0, 4).map((snapshot) => (
                  <button type="button" className="analysis-result-row" key={snapshot.id} onClick={() => navigate(resultPath(snapshot.id))}>
                    <IconFile aria-hidden="true" /><span><strong>{formatDate(snapshot.created_at)}</strong><small>{revisions.data?.find((item) => item.id === snapshot.system_revision_id)?.label ?? '已保存结果'}</small></span>
                  </button>
                )) : <EmptyState description="尚无冻结求解结果" />}
              </section>
            </div>
          </Tabs.TabPane>
          <Tabs.TabPane key="execute" title="情景比较">
            <div className="workbench-grid">
              <section className="section-panel">
                <div className="section-heading"><h2>比较运行</h2>{comparison ? <StatusBadge status={comparison.comparability.compatible ? 'compatible' : 'incompatible'} /> : null}</div>
                {comparisons.data?.length === 0 ? <EmptyState description="尚未建立情景比较" /> : (
                  <Form<FormValues>
                    form={form}
                    layout="vertical"
                    onSubmit={onSubmit}
                    initialValues={{ amount: 1, ...savedDraft }}
                    onValuesChange={(_, values) => localStorage.setItem(draftKey, JSON.stringify(values))}
                    scrollToFirstError
                  >
                    <Form.Item label="比较方案" field="comparison_id" rules={[{ required: true, message: '请选择比较方案' }]}>
                      <Select
                        placeholder="选择 2–5 个冻结情景组成的比较"
                        onChange={(value) => { setSelectedComparison(value); form.setFieldValue('baseline_scenario_id', undefined); }}
                        options={comparisons.data?.map((item) => ({ label: item.name, value: item.id }))}
                      />
                    </Form.Item>
                    <Form.Item label="基准情景" field="baseline_scenario_id" rules={[{ required: true, message: '请选择基准情景' }]}>
                      <Select placeholder="选择比较基准" disabled={!comparison} options={comparisonScenarios.map((item) => ({ label: item.name, value: item.id }))} />
                    </Form.Item>
                    <div className="form-grid">
                      <Form.Item label="需求 Flow UUID" field="reference_flow_uuid" rules={[{ required: true, message: '请输入需求 Flow UUID' }]}><Input placeholder="精确 reference flow UUID" /></Form.Item>
                      <Form.Item label="需求量" field="amount" rules={[{ required: true, message: '请输入大于 0 的需求量' }]}><InputNumber min={Number.EPSILON} precision={6} placeholder="数值" /></Form.Item>
                      <Form.Item label="单位" field="unit" rules={[{ required: true, message: '请输入单位' }]}><Input placeholder="例如 kg" /></Form.Item>
                      <Form.Item label="单位组 UUID（可选）" field="unit_group_uuid"><Input placeholder="精确单位组身份" /></Form.Item>
                      <Form.Item label="单位组版本（可选）" field="unit_group_version"><Input placeholder="与单位组 UUID 配套" /></Form.Item>
                      <Form.Item label="LCIA 方法（可选）" field="lcia_methods" extra="多个方法用英文逗号分隔"><Input placeholder="由 provider 合同识别的方法名称" /></Form.Item>
                    </div>
                    {execute.isError ? <ErrorState error={execute.error} /> : null}
                    {!comparison?.comparability.compatible && comparison ? <Alert type="warning" content="当前比较未通过兼容性检查，不能提交运行。" /> : null}
                    <div className="form-actions">
                      <Button htmlType="reset" disabled={execute.isPending} onClick={() => { form.resetFields(); localStorage.removeItem(draftKey); }}>重置</Button>
                      <Button type="primary" htmlType="submit" icon={<IconPlayArrow />} loading={execute.isPending} disabled={!comparison?.comparability.compatible || !formReady || execute.isPending}>执行比较</Button>
                    </div>
                  </Form>
                )}
              </section>
              <section className="section-panel scenario-summary">
                <div className="section-heading"><h2>情景范围</h2><span className="helper-text">{comparisonScenarios.length} 个情景</span></div>
                {comparisonScenarios.length === 0 ? <EmptyState description="选择比较方案后查看情景" /> : comparisonScenarios.map((scenario) => (
                  <div className="scenario-row" key={scenario.id}>
                    <div className="truncate"><strong>{scenario.name}</strong><span className="helper-text">Revision {shortId(scenario.system_revision_id)}</span></div>
                    <StatusBadge status={scenario.status} />
                  </div>
                ))}
              </section>
            </div>
          </Tabs.TabPane>
          <Tabs.TabPane key="lineage" title="Revision 分支">
            <section className="section-panel">
              <div className="section-heading"><h2>不可变 revision 关系</h2><span className="helper-text">{models.data?.find((item) => item.id === modelId)?.name}</span></div>
              {revisions.isLoading ? <LoadingState /> : revisions.isError ? <ErrorState error={revisions.error} onRetry={() => revisions.refetch()} /> : revisions.data?.length ? <RevisionLineage revisions={revisions.data} /> : <EmptyState description="该模型尚无 revision" />}
            </section>
          </Tabs.TabPane>
          <Tabs.TabPane key="runs" title="历史运行">
            <section className="section-panel">
              {runs.isLoading ? <LoadingState /> : runs.isError ? <ErrorState error={runs.error} onRetry={() => runs.refetch()} /> : (
                <Table rowKey="id" pagination={false} data={runs.data ?? []} noDataElement={<EmptyState description="尚无比较运行" />} columns={[
                  { title: '运行时间', dataIndex: 'created_at', render: (_, item) => formatDate(item.created_at) },
                  { title: '状态', dataIndex: 'status', render: (status) => <StatusBadge status={status} /> },
                  { title: '情景数', render: (_, item) => item.scenario_results.length },
                  { title: '操作', align: 'right', render: (_, item) => <Button type="text" disabled={item.status !== 'succeeded'} onClick={() => navigate(`/comparison-runs/${item.id}`)}>查看结果</Button> },
                ]} />
              )}
            </section>
          </Tabs.TabPane>
        </Tabs>
      ) : null}
    </main>
  );
}
