import { Alert, Button, Select, Table } from '@arco-design/web-react';
import { IconExpand } from '@arco-design/web-react/icon';
import { useEffect, useMemo, useState } from 'react';
import type { SpatialDistributionResult } from '../api/types';
import { MetricCard } from './ui/MetricCard';
import { EmptyState, ErrorState, LoadingState } from './ui/States';
import { StatusBadge } from './ui/StatusBadge';

interface Props {
  methodPackages: Array<{ reference: string; label: string }>;
  selectedMethodPackageRef: string;
  onMethodPackageChange: (value: string) => void;
  selectedScenarioId: string;
  onScenarioChange: (value: string) => void;
  result?: SpatialDistributionResult;
  isLoading: boolean;
  error: unknown;
  onRetry: () => void;
  chart?: Blob;
  chartIsLoading: boolean;
  chartError: unknown;
  onChartRetry: () => void;
}

function useObjectUrl(blob: Blob | undefined): string | undefined {
  const [url, setUrl] = useState<string>();
  useEffect(() => {
    if (!blob || typeof URL.createObjectURL !== 'function') {
      setUrl(undefined);
      return undefined;
    }
    const next = URL.createObjectURL(blob);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [blob]);
  return url;
}

function number(value: number): string {
  return new Intl.NumberFormat('zh-CN', { maximumSignificantDigits: 8 }).format(value);
}

function percent(value: number | null): string {
  if (value === null) return '—';
  return new Intl.NumberFormat('zh-CN', { style: 'percent', maximumFractionDigits: 2, signDisplay: 'exceptZero' }).format(value);
}

function sharePercent(value: number): string {
  return new Intl.NumberFormat('zh-CN', { style: 'percent', maximumFractionDigits: 2 }).format(value);
}

export function SpatialDistributionPanel(props: Props) {
  const chartUrl = useObjectUrl(props.chart);
  const scenario = props.result?.scenarios.find((item) => item.scenario_id === props.selectedScenarioId);
  const largest = useMemo(
    () => scenario?.regions.reduce((current, item) => item.amount > current.amount ? item : current, scenario.regions[0]),
    [scenario],
  );
  if (props.isLoading) return <LoadingState rows={7} />;
  if (props.error) return <ErrorState error={props.error} onRetry={props.onRetry} />;
  if (!props.methodPackages.length) return <EmptyState description="当前应用没有绑定省域供应分布方法包。" />;
  if (!props.result || !scenario) return <EmptyState description="该冻结快照尚未生成可展示的省域供应分布。" />;
  return (
    <div className="pcf-result spatial-result">
      <div className="pcf-result__head">
        <div><h3>省域供应分布</h3><p>从冻结边界 Flow 分配声明份额；代表点和情景份额均为案例输入，不改变求解与 LCIA。</p></div>
        <div className="spatial-result__selectors">
          <label htmlFor="distribution-method">方法包</label>
          <Select id="distribution-method" value={props.selectedMethodPackageRef} onChange={props.onMethodPackageChange} options={props.methodPackages.map((item) => ({ label: item.label, value: item.reference }))} />
          <label htmlFor="distribution-scenario">供应情景</label>
          <Select id="distribution-scenario" value={props.selectedScenarioId} onChange={props.onScenarioChange} options={props.result.scenarios.map((item) => ({ label: item.name, value: item.scenario_id }))} />
        </div>
      </div>
      <div className="metric-grid">
        <MetricCard label={`${props.result.source_flow.name} · 边界量`} value={number(props.result.source_flow.amount)} unit={props.result.source_flow.unit} />
        <MetricCard label="来源区域" value={String(scenario.regions.length)} unit="个" />
        <MetricCard label="最大来源" value={largest?.region.name ?? '—'} unit={largest ? sharePercent(largest.share) : undefined} />
        <MetricCard label="分配残差" value={number(scenario.allocation_residual)} unit={props.result.source_flow.unit} />
      </div>
      <Alert type="info" title="演示空间归因，不是行政区统计地图" content={<span>审计状态：<StatusBadge status={props.result.audit.status} />。图中使用省域代表点，不包含官方省界；供应份额不是实测数据。</span>} />
      <div className="pcf-result__chart" role="region" aria-label="省域供应流向图">
        <div className="pcf-result__chart-toolbar"><strong>{scenario.name}</strong>{chartUrl ? <Button type="text" size="small" icon={<IconExpand />} href={chartUrl} target="_blank" rel="noreferrer">打开全图</Button> : null}</div>
        {props.chartIsLoading ? <div className="pcf-result__chart-state"><LoadingState rows={5} /></div> : null}
        {props.chartError ? <div className="pcf-result__chart-state"><ErrorState error={props.chartError} onRetry={props.onChartRetry} /></div> : null}
        {!props.chartIsLoading && !props.chartError && chartUrl ? <img src={chartUrl} alt="省域供应流向图" /> : null}
      </div>
      <Table rowKey={(item) => item.region.region_id} pagination={false} scroll={{ x: 680 }} data={scenario.regions} columns={[
        { title: '来源区域', render: (_, item) => item.region.name },
        { title: '声明份额', align: 'right', render: (_, item) => <span className="tabular">{sharePercent(item.share)}</span> },
        { title: `分配量 (${props.result.source_flow.unit})`, align: 'right', render: (_, item) => <span className="tabular">{number(item.amount)}</span> },
        { title: '较基准变化', align: 'right', render: (_, item) => <span className="tabular">{number(item.amount_delta_from_baseline)} · {percent(item.relative_delta_from_baseline)}</span> },
      ]} />
    </div>
  );
}
