import { Table } from '@arco-design/web-react';
import { useEffect, useMemo, useState } from 'react';
import type { PeriodEnergyComparisonResult } from '../api/types';
import { StatusBadge } from './ui/StatusBadge';

interface Props {
  result: PeriodEnergyComparisonResult;
  chart?: Blob;
}

function amount(value: string): string {
  const parsed = Number(value);
  return Number.isFinite(parsed)
    ? parsed.toLocaleString('zh-CN', { maximumFractionDigits: 4 })
    : value;
}

function relative(value: string | null): string {
  if (value === null) return '基准为零';
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return value;
  const sign = parsed > 0 ? '+' : '';
  return `${sign}${(parsed * 100).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}%`;
}

export function PeriodEnergyComparisonPanel({ result, chart }: Props) {
  const [chartUrl, setChartUrl] = useState('');
  const scenarioNames = useMemo(
    () => Object.fromEntries(result.comparison.scenarios.map((item) => [item.scenario_id, item.scenario_name])),
    [result.comparison.scenarios],
  );

  useEffect(() => {
    if (!chart || typeof URL.createObjectURL !== 'function') {
      setChartUrl('');
      return undefined;
    }
    const next = URL.createObjectURL(chart);
    setChartUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [chart]);

  const rows = result.comparison.metrics.flatMap((metric) => (
    result.comparison.scenarios.map((scenario) => ({
      key: `${metric.metric_key}:${scenario.scenario_id}`,
      metric: metric.label,
      scenario: scenario.scenario_name,
      value: `${amount(metric.values[scenario.scenario_id])} ${metric.unit_symbol}`,
      delta: relative(metric.deltas[scenario.scenario_id]?.relative ?? null),
    }))
  ));

  return (
    <div className="period-energy-panel">
      <div className="period-energy-panel__summary">
        <StatusBadge status={result.audit.status} />
        <span>{result.reporting_period.id}@{result.reporting_period.version}</span>
        <span>{result.audit.counts.scenario_count} 个情景</span>
        <span>{result.audit.counts.metric_count} 条同口径能源序列</span>
      </div>
      {chartUrl ? (
        <div className="period-energy-panel__chart">
          <img src={chartUrl} alt={`${result.reporting_period.id} 能源情景对比图`} />
        </div>
      ) : null}
      <Table
        rowKey="key"
        size="small"
        pagination={false}
        scroll={{ x: 640 }}
        data={rows}
        columns={[
          { title: '能源流', dataIndex: 'metric', width: 220 },
          { title: '情景', dataIndex: 'scenario', width: 180 },
          { title: '结果', dataIndex: 'value', width: 140 },
          { title: '相对基准', dataIndex: 'delta', width: 120 },
        ]}
      />
      <p className="helper-text">
        基准情景：{scenarioNames[result.comparison.baseline_scenario_id]}。不同单位或能量口径不会合并；本结果不代表完整能源平衡。
      </p>
    </div>
  );
}
