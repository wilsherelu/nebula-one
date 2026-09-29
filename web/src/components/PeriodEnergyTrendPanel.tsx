import { Alert, Button, Descriptions, Drawer, Select, Table } from '@arco-design/web-react';
import { IconInfoCircle } from '@arco-design/web-react/icon';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { api, formatDate, shortId } from '../api/client';
import type {
  EnergyCarrierResult,
  PeriodEnergyTrendRequest,
  PeriodEnergyTrendResult,
  ReportingPeriod,
  SolvedSystemSnapshot,
} from '../api/types';
import { CopyableValue } from './ui/CopyableValue';
import { EmptyState, ErrorState, LoadingState } from './ui/States';
import { StatusBadge } from './ui/StatusBadge';
import { PeriodEnergyTotalPanel } from './PeriodEnergyTotalPanel';

interface Props {
  applicationId: string;
  snapshots: SolvedSystemSnapshot[];
  enabled: boolean;
}

interface TrendRow {
  key: string;
  metric: string;
  period: string;
  value: string;
  baselineDelta: string;
  previousDelta: string;
}

function relative(value: string | null | undefined): string {
  if (value === null) return '基准为零';
  if (value === undefined) return '—';
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return value;
  const sign = parsed > 0 ? '+' : '';
  return `${sign}${(parsed * 100).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}%`;
}

function amount(value: string): string {
  const parsed = Number(value);
  return Number.isFinite(parsed)
    ? parsed.toLocaleString('zh-CN', { maximumSignificantDigits: 8 })
    : value;
}

export function buildPeriodEnergyTrendRows(result: PeriodEnergyTrendResult): TrendRow[] {
  return result.metrics.flatMap((metric) => result.observations.map((observation) => {
    const periodId = observation.period.id;
    return {
      key: `${metric.metric_key}:${periodId}`,
      metric: metric.label,
      period: observation.period.name,
      value: `${amount(metric.values[periodId])} ${metric.unit_symbol}`,
      baselineDelta: relative(metric.deltas_from_baseline[periodId]?.relative),
      previousDelta: relative(metric.deltas_from_previous[periodId]?.relative),
    };
  }));
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

function resultLabel(record: EnergyCarrierResult, snapshots: Map<string, SolvedSystemSnapshot>): string {
  const snapshot = snapshots.get(record.solved_snapshot_id);
  return `${formatDate(record.created_at)} · revision ${shortId(snapshot?.system_revision_id)}`;
}

export function PeriodEnergyTrendPanel({ applicationId, snapshots, enabled }: Props) {
  const [bindings, setBindings] = useState<Record<string, string>>({});
  const [baselinePeriodId, setBaselinePeriodId] = useState('');
  const [auditVisible, setAuditVisible] = useState(false);
  const periods = useQuery({
    queryKey: ['periods', applicationId],
    queryFn: () => api.periods(applicationId),
    enabled,
  });
  const energyResults = useQuery({
    queryKey: ['application-energy-results', applicationId, snapshots.map((item) => item.id)],
    queryFn: async () => (await Promise.all(
      snapshots.map((snapshot) => api.energyCarrierResults(snapshot.id)),
    )).flat(),
    enabled: enabled && snapshots.length > 0,
  });
  const run = useMutation({
    mutationFn: async (payload: PeriodEnergyTrendRequest) => {
      const [result, chart] = await Promise.all([
        api.periodEnergyTrend(applicationId, payload),
        api.periodEnergyTrendChart(applicationId, payload),
      ]);
      return { result, chart };
    },
  });
  const chartUrl = useObjectUrl(run.data?.chart);
  const orderedPeriods = useMemo(
    () => [...(periods.data ?? [])].sort((left, right) => (
      left.start_date.localeCompare(right.start_date) || left.id.localeCompare(right.id)
    )),
    [periods.data],
  );
  const snapshotById = useMemo(
    () => new Map(snapshots.map((item) => [item.id, item])),
    [snapshots],
  );
  const selectedBindings = useMemo(
    () => orderedPeriods.flatMap((period) => bindings[period.id]
      ? [{ period_id: period.id, energy_result_id: bindings[period.id] }]
      : []),
    [bindings, orderedPeriods],
  );
  const duplicateResults = new Set(selectedBindings.map((item) => item.energy_result_id)).size
    !== selectedBindings.length;
  const selectedPeriodIds = new Set(selectedBindings.map((item) => item.period_id));
  const canRun = selectedBindings.length >= 2
    && !duplicateResults
    && Boolean(baselinePeriodId)
    && selectedPeriodIds.has(baselinePeriodId);

  useEffect(() => {
    if (!baselinePeriodId && orderedPeriods.length) setBaselinePeriodId(orderedPeriods[0].id);
  }, [baselinePeriodId, orderedPeriods]);

  if (!enabled) return null;
  if (periods.isLoading || energyResults.isLoading) return <LoadingState rows={7} />;
  const loadError = periods.error || energyResults.error;
  if (loadError) return <ErrorState error={loadError} onRetry={() => {
    periods.refetch();
    energyResults.refetch();
  }} />;
  if (orderedPeriods.length < 2) {
    return <EmptyState description="至少需要两个已登记且不重叠的报告期，才能配置跨期能源强度趋势。" />;
  }
  if (!energyResults.data?.length) {
    return <EmptyState description="当前 Application 没有可绑定的冻结能源结果。请先对各期模型状态完成求解和能源载体分析。" />;
  }

  const result = run.data?.result;
  return (
    <div className="period-trend">
      <div className="period-trend__head">
        <div>
          <h3>报告期能源强度</h3>
          <p>为每个报告期选择一份冻结能源结果；只比较同一功能单位和完全一致的能源口径。</p>
        </div>
        <Button
          type="primary"
          loading={run.isPending}
          disabled={!canRun || run.isPending}
          onClick={() => run.mutate({
            observations: selectedBindings,
            baseline_period_id: baselinePeriodId,
          })}
        >生成趋势</Button>
      </div>
      <div className="period-trend__bindings">
        {orderedPeriods.map((period: ReportingPeriod) => (
          <div className="period-trend__binding" key={period.id}>
            <div><strong>{period.name}</strong><small>{period.start_date} – {period.end_date}</small></div>
            <Select
              aria-label={`${period.name}能源结果`}
              allowClear
              placeholder="选择冻结能源结果"
              value={bindings[period.id] || undefined}
              onChange={(value) => {
                setBindings((current) => ({ ...current, [period.id]: value }));
                run.reset();
              }}
              onClear={() => {
                setBindings((current) => {
                  const next = { ...current };
                  delete next[period.id];
                  return next;
                });
                run.reset();
              }}
              options={energyResults.data.map((record) => ({
                value: record.id,
                label: resultLabel(record, snapshotById),
                disabled: Object.entries(bindings).some(([periodId, resultId]) => (
                  periodId !== period.id && resultId === record.id
                )),
              }))}
            />
          </div>
        ))}
      </div>
      <div className="period-trend__baseline">
        <label htmlFor="period-trend-baseline">基准报告期</label>
        <Select
          id="period-trend-baseline"
          value={baselinePeriodId || undefined}
          onChange={(value) => { setBaselinePeriodId(value); run.reset(); }}
          options={orderedPeriods.map((period) => ({
            value: period.id,
            label: period.name,
            disabled: !selectedPeriodIds.has(period.id),
          }))}
        />
      </div>
      {duplicateResults ? <Alert type="warning" content="同一份能源结果不能绑定到多个报告期。" /> : null}
      {run.error ? <ErrorState error={run.error} onRetry={() => canRun && run.mutate({ observations: selectedBindings, baseline_period_id: baselinePeriodId })} /> : null}
      {result ? <>
        <div className="period-trend__summary">
          <StatusBadge status={result.status} />
          <span>{result.audit.counts.period_count} 个报告期</span>
          <span>{result.audit.counts.metric_count} 条独立能源序列</span>
          <Button type="text" size="small" icon={<IconInfoCircle />} onClick={() => setAuditVisible(true)}>趋势审计</Button>
        </div>
        {chartUrl ? <div className="period-trend__chart" tabIndex={0} role="region" aria-label="报告期能源强度趋势图滚动区域"><img src={chartUrl} alt="报告期能源强度趋势图" /></div> : null}
        <Table rowKey="key" size="small" pagination={false} scroll={{ x: 720 }} data={buildPeriodEnergyTrendRows(result)} columns={[
          { title: '能源流', dataIndex: 'metric', width: 220 },
          { title: '报告期', dataIndex: 'period', width: 160 },
          { title: '单位产品结果', dataIndex: 'value', width: 140 },
          { title: '相对基准', dataIndex: 'baselineDelta', width: 120 },
          { title: '相对上期', dataIndex: 'previousDelta', width: 120 },
        ]} />
        <p className="helper-text">这是功能单位强度趋势，不是企业期间能源总量；各能源单位和口径使用独立图板。</p>
        <Drawer className="audit-drawer" width={560} visible={auditVisible} onCancel={() => setAuditVisible(false)} footer={null} title="跨期趋势证据" unmountOnExit>
          <Descriptions column={1} size="small" border data={[
            { label: '结果 hash', value: <CopyableValue value={result.content_sha256} compact={false} /> },
            { label: '功能单位 hash', value: <CopyableValue value={result.value_semantics.functional_unit_sha256} compact={false} /> },
            { label: 'System model', value: <CopyableValue value={result.system_model_id} compact={false} /> },
          ]} />
          <h3 className="audit-heading">可比性检查</h3>
          <pre className="audit-json">{JSON.stringify(result.audit, null, 2)}</pre>
        </Drawer>
      </> : null}
      <PeriodEnergyTotalPanel
        applicationId={applicationId}
        bindings={selectedBindings}
        baselinePeriodId={baselinePeriodId}
        energyResults={energyResults.data}
        snapshots={snapshots}
      />
    </div>
  );
}
