import { Alert, Button, Select, Table } from '@arco-design/web-react';
import { IconExpand } from '@arco-design/web-react/icon';
import { useEffect, useMemo, useState } from 'react';
import type { BoundaryDefinition, SpatialAggregateResult } from '../api/types';
import { MetricCard } from './ui/MetricCard';
import { EmptyState, ErrorState, LoadingState } from './ui/States';
import { StatusBadge } from './ui/StatusBadge';

interface Props {
  boundaries: BoundaryDefinition[];
  selectedBoundaryId: string;
  onBoundaryChange: (value: string) => void;
  selectedSeriesId: string;
  onSeriesChange: (value: string) => void;
  result?: SpatialAggregateResult;
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

function format(value: number): string {
  return new Intl.NumberFormat('zh-CN', { maximumSignificantDigits: 8 }).format(value);
}

export function SpatialAggregatePanel(props: Props) {
  const chartUrl = useObjectUrl(props.chart);
  const series = props.result?.series.find((item) => item.series_id === props.selectedSeriesId);
  const facilityById = useMemo(
    () => new Map(props.result?.facilities.map((item) => [item.entity_id, item.name]) ?? []),
    [props.result?.facilities],
  );
  if (props.isLoading) return <LoadingState rows={7} />;
  if (props.error) return <ErrorState error={props.error} onRetry={props.onRetry} />;
  if (!props.boundaries.length) return <EmptyState description="当前应用没有已冻结的园区边界；请从石化园区案例物化设施与 Process 绑定。" />;
  if (!props.result || !series) return <EmptyState description="该冻结快照尚未生成可展示的园区合并 MFA。" />;
  return (
    <div className="pcf-result spatial-result">
      <div className="pcf-result__head">
        <div><h3>园区边界合并 MFA</h3><p>设施 Process 绑定、内部抵消与外部边界 Flow 均追溯到同一冻结快照。</p></div>
        <div className="spatial-result__selectors">
          <label htmlFor="spatial-boundary">园区边界</label>
          <Select id="spatial-boundary" value={props.selectedBoundaryId} onChange={props.onBoundaryChange} options={props.boundaries.map((item) => ({ label: item.name, value: item.id }))} />
          {props.result.series.length > 1 ? <><label htmlFor="spatial-series">数量序列</label><Select id="spatial-series" value={props.selectedSeriesId} onChange={props.onSeriesChange} options={props.result.series.map((item) => ({ label: `${item.unit_group_label} · ${item.unit}`, value: item.series_id }))} /></> : null}
        </div>
      </div>
      <div className="metric-grid">
        <MetricCard label="园区外部输入" value={format(series.totals.external_input)} unit={series.unit} />
        <MetricCard label="园区外部输出" value={format(series.totals.external_output)} unit={series.unit} />
        <MetricCard label="设施间交换" value={format(series.totals.inter_facility)} unit={series.unit} />
        <MetricCard label="设施内抵消" value={format(series.totals.eliminated_intra_facility)} unit={series.unit} />
      </div>
      <Alert type="info" title={`${props.result.park.name} · ${props.result.facilities.length} 个设施`} content={<span>审计状态：<StatusBadge status={props.result.audit.status} />。设施内交换只在合并视图中抵消，原始 exchange 追溯保留在审计证据中。</span>} />
      <div className="pcf-result__chart" role="region" aria-label="园区合并物质流桑基图">
        <div className="pcf-result__chart-toolbar"><strong>园区输入、设施间交换与园区输出</strong>{chartUrl ? <Button type="text" size="small" icon={<IconExpand />} href={chartUrl} target="_blank" rel="noreferrer">打开全图</Button> : null}</div>
        {props.chartIsLoading ? <div className="pcf-result__chart-state"><LoadingState rows={5} /></div> : null}
        {props.chartError ? <div className="pcf-result__chart-state"><ErrorState error={props.chartError} onRetry={props.onChartRetry} /></div> : null}
        {!props.chartIsLoading && !props.chartError && chartUrl ? <img src={chartUrl} alt="园区合并物质流桑基图" /> : null}
      </div>
      <Table rowKey="entity_id" pagination={false} data={series.facility_metrics} columns={[
        { title: '设施', render: (_, item) => facilityById.get(item.entity_id) ?? '未命名设施' },
        { title: '外部输入', align: 'right', render: (_, item) => <span className="tabular">{format(item.external_input)}</span> },
        { title: '设施间输入', align: 'right', render: (_, item) => <span className="tabular">{format(item.inter_facility_input)}</span> },
        { title: '设施间输出', align: 'right', render: (_, item) => <span className="tabular">{format(item.inter_facility_output)}</span> },
        { title: '外部输出', align: 'right', render: (_, item) => <span className="tabular">{format(item.external_output)}</span> },
      ]} />
    </div>
  );
}
