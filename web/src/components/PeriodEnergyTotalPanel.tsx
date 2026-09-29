import { Alert, Button, Descriptions, Drawer, Table } from '@arco-design/web-react';
import { IconInfoCircle } from '@arco-design/web-react/icon';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import type {
  EnergyCarrierResult,
  InventoryDataPoint,
  InventorySnapshot,
  PeriodEnergyTotalRequest,
  PeriodEnergyTotalResult,
  SolvedSystemSnapshot,
} from '../api/types';
import { CopyableValue } from './ui/CopyableValue';
import { ErrorState, LoadingState } from './ui/States';
import { StatusBadge } from './ui/StatusBadge';

export interface PeriodEnergyBinding {
  period_id: string;
  energy_result_id: string;
}

interface Props {
  applicationId: string;
  bindings: PeriodEnergyBinding[];
  baselinePeriodId: string;
  energyResults: EnergyCarrierResult[];
  snapshots: SolvedSystemSnapshot[];
}

interface Resolution {
  request?: PeriodEnergyTotalRequest;
  issues: string[];
}

export function resolvePeriodTotalRequest(
  bindings: PeriodEnergyBinding[],
  baselinePeriodId: string,
  energyResults: EnergyCarrierResult[],
  snapshots: SolvedSystemSnapshot[],
  inventories: InventorySnapshot[],
  points: InventoryDataPoint[],
): Resolution {
  const issues: string[] = [];
  if (bindings.length < 2) {
    return { issues: ['请先为至少两个报告期选择不同的冻结能源结果。'] };
  }
  const energyById = new Map(energyResults.map((item) => [item.id, item]));
  const snapshotById = new Map(snapshots.map((item) => [item.id, item]));
  const observations = bindings.flatMap((binding) => {
    const energy = energyById.get(binding.energy_result_id);
    const snapshot = energy ? snapshotById.get(energy.solved_snapshot_id) : undefined;
    if (!energy || !snapshot) {
      issues.push('所选能源结果缺少对应的冻结求解快照。');
      return [];
    }
    const matches = inventories.filter((item) => item.status === 'frozen'
      && Boolean(item.content_sha256)
      && item.period_id === binding.period_id
      && item.system_revision_id === snapshot.system_revision_id);
    if (matches.length !== 1) {
      issues.push(`报告期 ${binding.period_id} 需要且只能有一份匹配 revision 的冻结产量清单。`);
      return [];
    }
    const inventory = matches[0];
    const productionPoints = points.filter((item) => item.inventory_snapshot_id === inventory.id
      && item.metric_key === 'period_product_output'
      && item.quality_status !== 'invalid'
      && item.quality_status !== 'rejected'
      && item.review_status === 'approved'
      && item.mapping_target.role === 'period_product_output');
    if (productionPoints.length !== 1) {
      issues.push(`冻结清单 ${inventory.name} 需要且只能有一个已批准的产品产量数据点。`);
      return [];
    }
    return [{
      ...binding,
      inventory_snapshot_id: inventory.id,
      production_data_point_id: productionPoints[0].id,
    }];
  });
  const uniqueIssues = [...new Set(issues)];
  if (uniqueIssues.length || observations.length !== bindings.length) {
    return { issues: uniqueIssues };
  }
  return { issues: [], request: { observations, baseline_period_id: baselinePeriodId } };
}

function amount(value: string): string {
  const parsed = Number(value);
  return Number.isFinite(parsed)
    ? parsed.toLocaleString('zh-CN', { maximumSignificantDigits: 8 })
    : value;
}

function useObjectUrl(blob: Blob | undefined): string | undefined {
  const [url, setUrl] = useState<string>();
  useEffect(() => {
    if (!blob || typeof URL.createObjectURL !== 'function') return setUrl(undefined);
    const next = URL.createObjectURL(blob);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [blob]);
  return url;
}

export function buildPeriodEnergyTotalRows(result: PeriodEnergyTotalResult) {
  return result.metrics.flatMap((metric) => result.observations.map((observation) => {
    const periodId = observation.period.id;
    const activity = result.activities.find((item) => item.period_id === periodId);
    return {
      key: `${metric.metric_key}:${periodId}`,
      metric: metric.label,
      period: observation.period.name,
      production: activity ? `${amount(String(activity.data_point.quantity))} ${activity.data_point.unit}` : '—',
      intensity: `${amount(metric.intensity_values[periodId])} ${metric.unit_symbol}`,
      total: `${amount(metric.period_total_values[periodId])} ${metric.unit_symbol}`,
    };
  }));
}

export function PeriodEnergyTotalPanel(props: Props) {
  const [auditVisible, setAuditVisible] = useState(false);
  const inventories = useQuery({
    queryKey: ['inventory-snapshots', props.applicationId],
    queryFn: () => api.inventorySnapshots(props.applicationId),
    enabled: props.bindings.length >= 2,
  });
  const frozenInventoryIds = useMemo(() => (inventories.data ?? [])
    .filter((item) => item.status === 'frozen')
    .map((item) => item.id)
    .sort(), [inventories.data]);
  const points = useQuery({
    queryKey: ['period-total-points', props.applicationId, frozenInventoryIds],
    queryFn: async () => (await Promise.all(
      frozenInventoryIds.map((id) => api.inventoryDataPoints(id)),
    )).flat(),
    enabled: frozenInventoryIds.length > 0,
  });
  const resolution = useMemo(() => resolvePeriodTotalRequest(
    props.bindings,
    props.baselinePeriodId,
    props.energyResults,
    props.snapshots,
    inventories.data ?? [],
    points.data ?? [],
  ), [props, inventories.data, points.data]);
  const run = useMutation({
    mutationFn: async (payload: PeriodEnergyTotalRequest) => {
      const [result, chart] = await Promise.all([
        api.periodEnergyTotal(props.applicationId, payload),
        api.periodEnergyTotalChart(props.applicationId, payload),
      ]);
      return { result, chart };
    },
  });
  const chartUrl = useObjectUrl(run.data?.chart);
  const result = run.data?.result;
  if (inventories.isLoading || points.isLoading) return <LoadingState rows={4} />;
  const loadError = inventories.error || points.error;
  if (loadError) return <ErrorState error={loadError} onRetry={() => {
    inventories.refetch();
    points.refetch();
  }} />;
  return <section className="period-total" aria-labelledby="period-total-title">
    <div className="period-trend__head">
      <div>
        <h3 id="period-total-title">报告期能源总量</h3>
        <p>使用每期已审核产品产量缩放单位产品能源结果；系统不会推断产量或换算单位。</p>
      </div>
      <Button type="primary" loading={run.isPending} disabled={!resolution.request || run.isPending}
        onClick={() => resolution.request && run.mutate(resolution.request)}>生成期间总量</Button>
    </div>
    {resolution.issues.length ? <Alert type="warning" title="产量证据尚未就绪"
      content={resolution.issues.join(' ')} /> : <Alert type="success" content="每个报告期均已解析到唯一的冻结产量清单和已批准数据点。" />}
    {run.error ? <ErrorState error={run.error} onRetry={() => resolution.request && run.mutate(resolution.request)} /> : null}
    {result ? <>
      <div className="period-trend__summary">
        <StatusBadge status={result.status} />
        <span>{result.audit.counts.period_count} 个报告期</span>
        <span>{result.audit.counts.evidence_count} 份产量证据</span>
        <Button type="text" size="small" icon={<IconInfoCircle />} onClick={() => setAuditVisible(true)}>总量审计</Button>
      </div>
      {chartUrl ? <div className="period-trend__chart" tabIndex={0} role="region" aria-label="报告期能源总量图滚动区域"><img src={chartUrl} alt="报告期能源总量图" /></div> : null}
      <Table rowKey="key" size="small" pagination={false} scroll={{ x: 820 }}
        data={buildPeriodEnergyTotalRows(result)} columns={[
          { title: '能源流', dataIndex: 'metric', width: 220 },
          { title: '报告期', dataIndex: 'period', width: 140 },
          { title: '审核产量', dataIndex: 'production', width: 150 },
          { title: '单位产品强度', dataIndex: 'intensity', width: 150 },
          { title: '期间总量', dataIndex: 'total', width: 160 },
        ]} />
      <p className="helper-text">总量只覆盖所选的不重叠报告期，不代表完整炼厂能源平衡。</p>
      <Drawer className="audit-drawer" width={560} visible={auditVisible} onCancel={() => setAuditVisible(false)} footer={null} title="期间总量证据" unmountOnExit>
        <Descriptions column={1} size="small" border data={[
          { label: '结果 hash', value: <CopyableValue value={result.content_sha256} compact={false} /> },
          { label: '来源趋势 hash', value: <CopyableValue value={result.source_intensity_trend.content_sha256} compact={false} /> },
          { label: 'System model', value: <CopyableValue value={result.system_model_id} compact={false} /> },
        ]} />
        <h3 className="audit-heading">证据与缩放检查</h3>
        <pre className="audit-json">{JSON.stringify(result.audit, null, 2)}</pre>
      </Drawer>
    </> : null}
  </section>;
}
