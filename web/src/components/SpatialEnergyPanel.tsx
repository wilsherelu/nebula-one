import { Alert, Button, Select, Table } from '@arco-design/web-react';
import { IconExpand } from '@arco-design/web-react/icon';
import { useEffect, useMemo, useState } from 'react';
import type { SpatialEnergyResult } from '../api/types';
import { MetricCard } from './ui/MetricCard';
import { EmptyState, ErrorState, LoadingState } from './ui/States';
import { StatusBadge } from './ui/StatusBadge';

interface Props {
  result?: SpatialEnergyResult;
  isLoading: boolean;
  error: unknown;
  onRetry: () => void;
  selectedSeriesId: string;
  onSeriesChange: (value: string) => void;
  chart?: Blob;
  chartIsLoading: boolean;
  chartError: unknown;
  onChartRetry: () => void;
  ready: boolean;
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

function format(value: string): string {
  return new Intl.NumberFormat('zh-CN', { maximumSignificantDigits: 8 }).format(Number(value));
}

export function SpatialEnergyPanel(props: Props) {
  const chartUrl = useObjectUrl(props.chart);
  const series = props.result?.series.find((item) => item.series_id === props.selectedSeriesId);
  const facilityById = useMemo(
    () => new Map(props.result?.facilities.map((item) => [item.entity_id, item.name]) ?? []),
    [props.result?.facilities],
  );
  if (!props.ready) return <EmptyState description="需要同一冻结快照的能源载体结果和已冻结园区边界，才能进行设施能源归属。" />;
  if (props.isLoading) return <LoadingState rows={7} />;
  if (props.error) return <ErrorState error={props.error} onRetry={props.onRetry} />;
  if (!props.result || !series) return <EmptyState description="该快照没有可展示的园区能源序列。" />;
  const facilitiesWithEnergy = series.facility_metrics.filter((item) => Number(item.amount) > 0).length;
  return (
    <div className="pcf-result spatial-result">
      <div className="pcf-result__head">
        <div><h3>园区外部能源投入</h3><p>把能源条目的源 exchange 精确连接到 Process—设施绑定，不按名称或比例推测归属。</p></div>
        {props.result.series.length > 1 ? <div className="spatial-result__selectors"><label htmlFor="spatial-energy-series">能源序列</label><Select id="spatial-energy-series" value={props.selectedSeriesId} onChange={props.onSeriesChange} options={props.result.series.map((item) => ({ label: `${item.unit_group_label} · ${item.unit}`, value: item.series_id }))} /></div> : null}
      </div>
      <div className="metric-grid">
        <MetricCard label="外部能源投入" value={format(series.total_amount)} unit={series.unit} />
        <MetricCard label="有能源投入的设施" value={String(facilitiesWithEnergy)} unit="个" />
        <MetricCard label="能源载体" value={String(series.carrier_metrics.length)} unit="种" />
        <MetricCard label="可追溯条目" value={String(series.links.length)} unit="项" />
      </div>
      <Alert type="info" title={`${props.result.park.name} · ${series.unit_group_label}`} content={<span>审计状态：<StatusBadge status={props.result.audit.status} />。当前只归属已求解的园区外部能源投入，不推断装置转换、损耗或下游分配。</span>} />
      <div className="pcf-result__chart" role="region" aria-label="园区外部能源投入桑基图">
        <div className="pcf-result__chart-toolbar"><strong>能源载体到设施的精确归属</strong>{chartUrl ? <Button type="text" size="small" icon={<IconExpand />} href={chartUrl} target="_blank" rel="noreferrer">打开全图</Button> : null}</div>
        {props.chartIsLoading ? <div className="pcf-result__chart-state"><LoadingState rows={5} /></div> : null}
        {props.chartError ? <div className="pcf-result__chart-state"><ErrorState error={props.chartError} onRetry={props.onChartRetry} /></div> : null}
        {!props.chartIsLoading && !props.chartError && chartUrl ? <div className="spatial-energy-chart__viewport" tabIndex={0} aria-label="园区能源桑基图滚动区域"><img src={chartUrl} alt="园区外部能源投入桑基图" /></div> : null}
      </div>
      <Table rowKey="entity_id" pagination={false} data={series.facility_metrics} columns={[
        { title: '设施', render: (_, item) => facilityById.get(item.entity_id) ?? '未命名设施' },
        { title: '能源投入', align: 'right', render: (_, item) => <span className="tabular">{format(item.amount)}</span> },
        { title: '占本序列', align: 'right', render: (_, item) => <span className="tabular">{item.share === null ? '—' : `${(Number(item.share) * 100).toFixed(1)}%`}</span> },
      ]} />
    </div>
  );
}
