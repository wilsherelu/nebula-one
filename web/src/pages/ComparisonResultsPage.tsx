import { Button, Tabs } from '@arco-design/web-react';
import { IconArrowLeft, IconExperiment, IconFile } from '@arco-design/web-react/icon';
import { useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { api, formatDate } from '../api/client';
import type { ComparisonMetric } from '../api/types';
import { AuditDrawer } from '../components/AuditDrawer';
import { PeriodEnergyComparisonPanel } from '../components/PeriodEnergyComparisonPanel';
import { SankeyViewer } from '../components/SankeyViewer';
import { ScenarioComparisonChart } from '../components/ScenarioComparisonChart';
import { MetricCard } from '../components/ui/MetricCard';
import { PageHeader } from '../components/ui/PageHeader';
import { StatusBadge } from '../components/ui/StatusBadge';
import { EmptyState, ErrorState, LoadingState, NotFoundState } from '../components/ui/States';

function number(value: number): string {
  return value.toLocaleString('zh-CN', { maximumFractionDigits: 4 });
}

function percent(value: number | null): string {
  if (value === null) return '基准为零';
  const sign = value > 0 ? '+' : '';
  return `${sign}${(value * 100).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}%`;
}

function metricLabel(metric: ComparisonMetric): string {
  return metric.subject_name ?? metric.flow_name ?? metric.subject_id ?? metric.metric_key;
}

function scenarioSankeyUrl(result: import('../api/types').ScenarioResult): string {
  const preferred = result.mfa_series?.find(
    (item) => item.unit_group_label?.toLocaleLowerCase() === 'mass',
  ) ?? result.mfa_series?.[0];
  if (!preferred) return result.sankey_url;
  return `/api/v1/solved-system-snapshots/${result.solved_snapshot_id}/mfa/sankey.svg?series_id=${encodeURIComponent(preferred.series_id)}`;
}

export function ComparisonResultsPage() {
  const { runId } = useParams();
  const navigate = useNavigate();
  const [auditVisible, setAuditVisible] = useState(false);
  const [energyRequested, setEnergyRequested] = useState(false);
  const run = useQuery({ queryKey: ['comparison-run', runId], queryFn: () => api.comparisonRun(runId!), enabled: Boolean(runId) });
  const periodEnergy = useQuery({
    queryKey: ['period-energy-comparison', runId],
    queryFn: () => api.periodEnergyComparison(runId!),
    enabled: Boolean(runId && energyRequested),
    retry: false,
  });
  const periodEnergyChart = useQuery({
    queryKey: ['period-energy-comparison-chart', runId],
    queryFn: () => api.periodEnergyComparisonChart(runId!),
    enabled: Boolean(runId && periodEnergy.data),
    retry: false,
  });
  const summaries = useMemo(() => run.data?.metrics.slice(0, 4).map((metric) => {
    const changes = run.data!.scenario_results
      .filter((item) => item.scenario_id !== run.data!.baseline_scenario_id)
      .map((item) => ({ ...item, ...metric.deltas[item.scenario_id] }))
      .filter((item) => typeof item.absolute === 'number');
    const notable = [...changes].sort((a, b) => Math.abs(b.absolute) - Math.abs(a.absolute))[0];
    return { metric, notable };
  }) ?? [], [run.data]);

  if (!runId) return <NotFoundState />;
  if (run.isLoading) return <main className="app-page"><section className="section-panel"><LoadingState rows={8} /></section></main>;
  if (run.isError) return <main className="app-page"><ErrorState error={run.error} onRetry={() => run.refetch()} /></main>;
  if (!run.data) return <NotFoundState />;
  const data = run.data;
  const back = () => navigate(`/applications/${data.application_id}/scenarios`);
  return (
    <main className="app-page">
      <PageHeader
        title="情景比较结果"
        description={`运行完成于 ${formatDate(data.completed_at)}，共 ${data.scenario_results.length} 个冻结情景。`}
        action={<div className="inline-actions"><Button icon={<IconArrowLeft />} onClick={back}>返回配置</Button><Button icon={<IconFile />} onClick={() => setAuditVisible(true)}>审计证据</Button></div>}
      />
      {data.status === 'failed' ? (
        <ErrorState error={new Error(data.error.message ?? '情景比较运行失败，请返回配置检查输入与模型状态。')} />
      ) : (
        <div className="page-grid">
          <div className="result-status-band"><StatusBadge status={data.audit.status ?? data.status} /><span>单位序列分别绘制；相对变化以选定基准情景计算。</span></div>
          <section className="metric-grid">
            {summaries.map(({ metric, notable }) => (
              <MetricCard
                key={metric.metric_key}
                label={metricLabel(metric)}
                value={number(metric.baseline_value)}
                unit={metric.unit}
                delta={notable ? `${notable.scenario_name} ${percent(notable.relative)}` : undefined}
                tone={notable && notable.absolute !== 0 ? (notable.absolute < 0 ? 'positive' : 'negative') : 'neutral'}
              />
            ))}
          </section>
          <section className="section-panel">
            <div className="section-heading"><h2>情景指标对比</h2><a href={`/api/v1/scenario-comparison-runs/${data.id}/chart.svg`} target="_blank" rel="noreferrer">下载对比图</a></div>
            {data.metrics.length ? <ScenarioComparisonChart metrics={data.metrics} scenarioResults={data.scenario_results} /> : <EmptyState description="本次运行没有可比较指标" />}
          </section>
          <details className="section-panel result-details"><summary>扩展分析：报告期能源情景</summary>
            <div className="section-heading">
              <div><h2>报告期能源情景</h2><span className="helper-text">按应用绑定的冻结报告期和已求解能源结果比较</span></div>
              <Button
                icon={<IconExperiment />}
                loading={periodEnergy.isFetching}
                disabled={periodEnergy.isFetching || periodEnergyChart.isFetching}
                onClick={() => {
                  if (energyRequested) void periodEnergy.refetch();
                  else setEnergyRequested(true);
                }}
              >
                {periodEnergy.data ? '刷新结果' : '生成期间能源对比'}
              </Button>
            </div>
            {!energyRequested ? (
              <EmptyState description="按需生成，现有 LCIA 与 MFA 结果不会受到影响" />
            ) : periodEnergy.isError ? (
              <ErrorState error={periodEnergy.error} onRetry={() => periodEnergy.refetch()} />
            ) : periodEnergy.isLoading || !periodEnergy.data ? (
              <LoadingState rows={4} />
            ) : periodEnergyChart.isError ? (
              <ErrorState error={periodEnergyChart.error} onRetry={() => periodEnergyChart.refetch()} />
            ) : (
              <PeriodEnergyComparisonPanel result={periodEnergy.data} chart={periodEnergyChart.data} />
            )}
          </details>
          <section className="section-panel">
            <div className="section-heading"><h2>各情景 MFA</h2><span className="helper-text">每条流均追溯到已求解 exchange</span></div>
            {data.scenario_results.length ? (
              <Tabs destroyOnHide={false}>
                {data.scenario_results.map((result) => (
                  <Tabs.TabPane key={result.scenario_id} title={result.scenario_name}>
                    <div className="sankey-panel">
                      <div className="sankey-panel__meta"><StatusBadge status={result.mfa_audit.status ?? 'unknown'} /><span className="helper-text">Solved snapshot 已冻结</span></div>
                      <SankeyViewer src={scenarioSankeyUrl(result)} alt={`${result.scenario_name} MFA 桑基图`} />
                    </div>
                  </Tabs.TabPane>
                ))}
              </Tabs>
            ) : <EmptyState description="尚未生成 MFA 结果" />}
          </section>
        </div>
      )}
      <AuditDrawer run={data} visible={auditVisible} onClose={() => setAuditVisible(false)} />
    </main>
  );
}
