import ReactECharts from 'echarts-for-react';
import type { ProductCarbonFootprint } from '../api/types';
import { useI18n } from '../i18n';

export function processName(id: string, nodes: Array<Record<string, unknown>>, fallback = '未提供过程名称') {
  const node = nodes.find((item) => item.id === `process:${id}`);
  return typeof node?.label === 'string' && node.label !== id && node.label !== `process:${id}` ? node.label : fallback;
}

/** Match solved process IDs to names only through exchanges in the same frozen snapshot. */
export function processDisplayNodes({ workspaceNodes, exchanges, mfaNodes, backgroundReceipts, backgroundLabel }: {
  workspaceNodes: Array<{ id: string; name: string }>;
  exchanges: Array<Record<string, unknown>>;
  mfaNodes: Array<Record<string, unknown>>;
  backgroundReceipts: unknown;
  backgroundLabel: string;
}): Array<Record<string, unknown>> {
  const names = new Map(workspaceNodes.map((node) => [node.id, node.name]));
  const candidates = new Map<string, Set<string>>();
  for (const exchange of exchanges) {
    if (typeof exchange.process_id !== 'string' || typeof exchange.exchange_id !== 'string') continue;
    const role = exchange.exchange_id.split('::')[0];
    if (!names.has(role)) continue;
    const labels = candidates.get(exchange.process_id) ?? new Set<string>();
    labels.add(names.get(role)!);
    candidates.set(exchange.process_id, labels);
  }
  const result = new Map<string, string>();
  for (const node of mfaNodes) {
    if (typeof node.process_id !== 'string' || typeof node.label !== 'string'
      || node.label === node.process_id) continue;
    result.set(node.process_id, node.label);
  }
  for (const [id, labels] of candidates) {
    if (labels.size === 1) result.set(id, [...labels][0]);
  }
  if (Array.isArray(backgroundReceipts)) {
    for (const receipt of backgroundReceipts) {
      if (!receipt || typeof receipt !== 'object') continue;
      const row = receipt as Record<string, unknown>;
      if (typeof row.source_process_uuid === 'string' && !result.has(row.source_process_uuid)) {
        result.set(row.source_process_uuid, backgroundLabel);
      }
      if (typeof row.expanded_node_id === 'string') {
        for (const exchange of exchanges) {
          if (typeof exchange.process_id === 'string' && typeof exchange.exchange_id === 'string'
            && exchange.exchange_id.startsWith(`${row.expanded_node_id}::`) && !result.has(exchange.process_id)) {
            result.set(exchange.process_id, backgroundLabel);
          }
        }
      }
    }
  }
  return [...result].map(([id, label]) => ({ id: `process:${id}`, label }));
}

export function ContributionChart({ result, nodes }: {
  result: ProductCarbonFootprint; nodes: Array<Record<string, unknown>>;
}) {
  const { t, formatNumber } = useI18n();
  const rows = result.contribution_analysis.hotspots.slice(0, 8);
  if (!rows.length || result.contribution_analysis.status !== 'available') return null;
  // Keep signed values and separate axes for different contribution units.
  const units = [...new Set(rows.map((row) => row.contribution_unit))];
  const theme = getComputedStyle(document.documentElement);
  return <div className="contribution-charts">{units.map((unit) => {
    const items = rows.filter((row) => row.contribution_unit === unit);
    return <ReactECharts key={unit} opts={{ renderer: 'svg' }} style={{ height: Math.max(180, items.length * 44 + 70) }} option={{
      aria: { enabled: true, description: t('pcf.chartAria') },
      tooltip: { trigger: 'axis', renderMode: 'richText', axisPointer: { type: 'shadow' } },
      grid: { left: 12, right: 60, top: 32, bottom: 16, containLabel: true },
      xAxis: { type: 'value', name: unit, nameLocation: 'middle', nameGap: 22, position: 'top', splitLine: { lineStyle: { type: 'dashed' } } },
      yAxis: { type: 'category', inverse: true, data: items.map((row) => `${row.rank}. ${processName(row.process_id, nodes, t('pcf.unnamedProcess'))}`), axisLabel: { width: 130, overflow: 'truncate' }, axisTick: { show: false }, axisLine: { show: false } },
      series: [{ type: 'bar', barMaxWidth: 22, label: { show: true, position: 'right', formatter: (params: { value: number }) => formatNumber(params.value, { maximumSignificantDigits: 6 }) }, data: items.map((row) => ({ value: row.contribution_value, itemStyle: { color: theme.getPropertyValue(row.contribution_value < 0 ? '--no-color-success' : '--no-color-primary').trim() } })) }],
    }} />;
  })}</div>;
}
