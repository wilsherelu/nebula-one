import { useEffect, useState } from 'react';
import ReactECharts from 'echarts-for-react';
import type { EChartsOption } from 'echarts';
import type { ComparisonMetric, ScenarioResult } from '../api/types';

function metricAxisLabel(metric: ComparisonMetric): string {
  if (metric.metric_kind === 'lcia_indicator') {
    return metric.indicator_key ?? metric.subject_name ?? metric.subject_id ?? metric.metric_key;
  }
  return metric.subject_name ?? metric.flow_name ?? metric.subject_id ?? metric.metric_key;
}

function useCompactChart(): boolean {
  const [compact, setCompact] = useState(() => typeof window !== 'undefined' && window.innerWidth <= 767);
  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return undefined;
    const query = window.matchMedia('(max-width: 767px)');
    const update = () => setCompact(query.matches);
    update();
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);
  return compact;
}

export function buildComparisonChartOption(
  metrics: ComparisonMetric[],
  scenarioResults: ScenarioResult[],
  compact = false,
): EChartsOption {
  const labels = metrics.map(metricAxisLabel);
  const scenarios = scenarioResults.map((item) => [item.scenario_id, item.scenario_name] as const);
  return {
    color: ['#2878ff', '#27a277', '#e59a2f', '#886bd8', '#d85d75'],
    animationDuration: 350,
    aria: { enabled: true, decal: { show: true } },
    tooltip: {
      trigger: 'axis',
      renderMode: 'richText',
      axisPointer: { type: 'shadow' },
      valueFormatter: (value) => typeof value === 'number' ? value.toLocaleString('zh-CN', { maximumFractionDigits: 4 }) : String(value),
    },
    legend: { show: false },
    grid: { left: compact ? 4 : 20, right: compact ? 8 : 24, top: 20, bottom: compact ? 32 : 24, containLabel: true },
    xAxis: { type: 'value', axisLabel: { color: '#5e718d', fontSize: compact ? 10 : 12 }, splitLine: { lineStyle: { color: '#edf1f6' } } },
    yAxis: { type: 'category', data: labels, axisLabel: { color: '#172b4d', fontSize: compact ? 10 : 12, width: compact ? 92 : 180, overflow: 'truncate' } },
    series: scenarios.map(([scenarioId, scenarioName]) => ({
      name: scenarioName,
      type: 'bar',
      barMaxWidth: compact ? 14 : 20,
      emphasis: { focus: 'series' },
      data: metrics.map((metric) => metric.scenario_values[scenarioId] ?? null),
    })),
  };
}

export function ScenarioComparisonChart({ metrics, scenarioResults }: { metrics: ComparisonMetric[]; scenarioResults: ScenarioResult[] }) {
  const compact = useCompactChart();
  const groups = Array.from(
    metrics.reduce((map, metric) => {
      const group = map.get(metric.series_id) ?? [];
      group.push(metric);
      map.set(metric.series_id, group);
      return map;
    }, new Map<string, ComparisonMetric[]>()),
  );
  return (
    <div className="comparison-chart-stack">
      <ul className="comparison-chart-legend" aria-label="情景图例">
        {scenarioResults.map((scenario, index) => (
          <li key={scenario.scenario_id}>
            <span className={`comparison-chart-legend__swatch comparison-chart-legend__swatch--${index % 5}`} aria-hidden="true" />
            {scenario.scenario_name}
          </li>
        ))}
      </ul>
      {groups.map(([seriesId, items]) => (
        <section className="comparison-chart-series" key={seriesId}>
          <div className="comparison-chart-series__title">
            {items[0].unit_group_label ?? items[0].unit_group} · {items[0].unit}
          </div>
          <ReactECharts
            option={buildComparisonChartOption(items, scenarioResults, compact)}
            style={{ height: Math.max(compact ? 240 : 280, items.length * (compact ? 46 : 58)) }}
            notMerge
          />
        </section>
      ))}
    </div>
  );
}
