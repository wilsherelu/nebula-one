import { Alert, Button, Select, Table } from '@arco-design/web-react';
import { IconExpand } from '@arco-design/web-react/icon';
import { useEffect, useState } from 'react';
import type { CarbonManagementResult } from '../api/types';
import { MetricCard } from './ui/MetricCard';
import { EmptyState, ErrorState, LoadingState } from './ui/States';
import { StatusBadge } from './ui/StatusBadge';

interface Props {
  methodPackages: Array<{ reference: string; label: string }>;
  selectedMethodPackageRef: string;
  onMethodPackageChange: (reference: string) => void;
  result?: CarbonManagementResult;
  isLoading: boolean;
  error: unknown;
  onRetry: () => void;
  chart?: Blob;
  chartIsLoading: boolean;
  chartError: unknown;
  onChartRetry: () => void;
  hasEnergyResult: boolean;
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

export function CarbonManagementPanel(props: Props) {
  const chartUrl = useObjectUrl(props.chart);
  if (!props.methodPackages.length) return <EmptyState description="当前应用没有绑定期间能源碳管理方法包。" />;
  if (!props.hasEnergyResult) return <EmptyState description="请先为当前冻结快照生成能源载体结果；系统不会从 Flow 名称或单位字符串推断能源数据。" />;
  if (props.isLoading) return <LoadingState rows={7} />;
  if (props.error) return <ErrorState error={props.error} onRetry={props.onRetry} />;
  if (!props.result) return <EmptyState description="该冻结快照尚未生成期间能源碳结果。" />;
  const directTotal = props.result.direct_emission_inventory.reduce((sum, item) => sum + item.amount, 0);
  const directUnit = props.result.direct_emission_inventory[0]?.unit ?? '—';
  return (
    <div className="pcf-result">
      <div className="pcf-result__head">
        <div><h3>期间能源碳管理</h3><p>能源、直接排放和气候变化总量均绑定同一冻结快照。</p></div>
        <div className="pcf-result__method">
          <label htmlFor="carbon-method-package">管理方法包</label>
          <Select id="carbon-method-package" value={props.selectedMethodPackageRef} onChange={props.onMethodPackageChange} options={props.methodPackages.map((item) => ({ label: item.label, value: item.reference }))} />
        </div>
      </div>
      <div className="pcf-result__summary">
        <MetricCard label="气候变化总量" value={props.result.climate_change_total ? format(props.result.climate_change_total.value) : '未提供'} unit={props.result.climate_change_total?.unit} />
        <dl className="pcf-result__facts">
          <div><dt>报告期间</dt><dd>{props.result.reporting_period.id} · {props.result.reporting_period.version}</dd></div>
          <div><dt>直接排放实物量</dt><dd>{format(directTotal)} {directUnit}</dd></div>
          <div><dt>审计状态</dt><dd><StatusBadge status={props.result.audit.status} /></dd></div>
        </dl>
      </div>
      <Alert type="warning" title="当前不是 Scope 1/2/3 清单" content="算法层尚未返回按来源拆分的 LCIA 贡献回执，因此直接、购入能源和供应链 CO₂e 均保持空值；本页不会用默认排放因子补算。" />
      <div className="pcf-result__chart" role="region" aria-label="期间能源碳管理图">
        <div className="pcf-result__chart-toolbar"><strong>能源载体与直接排放</strong>{chartUrl ? <Button type="text" size="small" icon={<IconExpand />} href={chartUrl} target="_blank" rel="noreferrer">打开全图</Button> : null}</div>
        {props.chartIsLoading ? <div className="pcf-result__chart-state"><LoadingState rows={5} /></div> : null}
        {props.chartError ? <div className="pcf-result__chart-state"><ErrorState error={props.chartError} onRetry={props.onChartRetry} /></div> : null}
        {!props.chartIsLoading && !props.chartError && chartUrl ? <img src={chartUrl} alt="期间能源碳管理图" /> : null}
      </div>
      <Table rowKey="exchange_id" pagination={false} data={props.result.direct_emission_inventory} columns={[
        { title: '直接排放类别', dataIndex: 'category' },
        { title: '实物量', align: 'right', render: (_, item) => <span className="tabular">{format(item.amount)}</span> },
        { title: '单位', dataIndex: 'unit' },
        { title: '来源交换', dataIndex: 'exchange_id' },
      ]} />
    </div>
  );
}
