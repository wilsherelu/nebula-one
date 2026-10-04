import ReactECharts from 'echarts-for-react';
import type { ProductCarbonFootprint } from '../api/types';
import { useI18n } from '../i18n';
import { useEffect, useState } from 'react';

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

export function ContributionChart({ result, nodes, exchangeNames = {} }: {
  result: ProductCarbonFootprint; nodes: Array<Record<string, unknown>>; exchangeNames?: Record<string, string>;
}) {
  const { t } = useI18n();
  const rows = result.contribution_analysis.hotspots.slice(0, 8);
  if (!rows.length || result.contribution_analysis.status !== 'available') return null;
  return <ContributionBars description={t('pcf.chartAria')} rows={rows.map(row => ({
    label: `${row.rank}. ${processName(row.process_id, nodes, t('pcf.unnamedProcess'))}${exchangeNames[row.exchange_id] ? `\n${exchangeNames[row.exchange_id]}` : ''}`,
    value: row.contribution_value, unit: row.contribution_unit,
  }))} />;
}

/** Only presentation is shared: callers supply their own frozen values and units. */
export function ContributionBars({ rows, description }: {
  rows: Array<{label: string; value: number; unit: string}>; description: string;
}) {
  const { formatNumber } = useI18n();
  const [narrow, setNarrow] = useState(() => window.innerWidth < 600);
  useEffect(() => {
    const resize = () => setNarrow(window.innerWidth < 600);
    window.addEventListener('resize', resize);
    return () => window.removeEventListener('resize', resize);
  }, []);
  if (!rows.length) return null;
  // Keep signed values and separate axes for different contribution units.
  const units = [...new Set(rows.map((row) => row.unit))];
  const theme = getComputedStyle(document.documentElement);
  return <div className="contribution-charts">{units.map((unit) => {
    const items = rows.filter((row) => row.unit === unit);
    const short = (name: string) => name.length > 36 ? `${name.slice(0, 35)}…` : name;
    return <ReactECharts key={unit} opts={{ renderer: 'svg' }} style={{ height: Math.max(180, items.length * (narrow ? 72 : 62) + 64) }} option={{
      animation: false,
      aria: { enabled: true, description },
      tooltip: { trigger: 'axis', renderMode: 'richText', axisPointer: { type: 'shadow' } },
      grid: { left: 12, right: 60, top: 32, bottom: 16, containLabel: true },
      xAxis: { type: 'value', name: unit, nameLocation: 'middle', nameGap: 22, position: 'top', splitNumber: narrow ? 2 : 5, axisLabel: { hideOverlap: true }, splitLine: { lineStyle: { type: 'dashed' } } },
      yAxis: { type: 'category', inverse: true, data: items.map((row) => row.label.split('\n').map(short).join('\n')), axisLabel: { width: narrow ? 120 : 270, overflow: 'truncate', lineHeight: 16, hideOverlap: false, showMinLabel: true, showMaxLabel: true }, axisTick: { show: false }, axisLine: { show: false } },
      series: [{ type: 'bar', barMaxWidth: 22, label: { show: true, position: 'right', formatter: (params: { value: number }) => formatNumber(params.value, { maximumSignificantDigits: 6 }) }, data: items.map((row) => ({ value: row.value, itemStyle: { color: theme.getPropertyValue(row.value < 0 ? '--no-color-success' : '--no-color-primary').trim() } })) }],
    }} />;
  })}</div>;
}
