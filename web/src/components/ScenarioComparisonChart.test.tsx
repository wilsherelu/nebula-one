import { describe, expect, it } from 'vitest';
import { buildComparisonChartOption } from './ScenarioComparisonChart';
import type { ComparisonMetric } from '../api/types';

const metrics: ComparisonMetric[] = [{
  metric_key: 'feed',
  flow_uuid: 'flow-feed',
  flow_name: 'Feedstock',
  direction: 'input',
  exchange_type: 'technosphere',
  unit: 'kg',
  unit_group: 'ug-mass',
  series_id: 'ug-mass:kg',
  baseline_value: 8,
  scenario_values: { base: 8, efficient: 7 },
  deltas: { base: { absolute: 0, relative: 0 }, efficient: { absolute: -1, relative: -0.125 } },
}];

const scenarioResults = [
  { scenario_id: 'base', scenario_name: '基准' },
  { scenario_id: 'efficient', scenario_name: '资源效率' },
] as never;

describe('comparison chart mapping', () => {
  it('maps every scenario to a grouped bar series without changing values', () => {
    const option = buildComparisonChartOption(metrics, scenarioResults);
    expect(option.yAxis).toMatchObject({ type: 'category', data: ['Feedstock'] });
    expect(option.series).toEqual(expect.arrayContaining([
      expect.objectContaining({ name: '基准', data: [8] }),
      expect.objectContaining({ name: '资源效率', data: [7] }),
    ]));
  });

  it('uses the exact LCIA indicator key instead of an ambiguous provider label', () => {
    const option = buildComparisonChartOption([{
      metric_key: 'lcia-climate',
      metric_kind: 'lcia_indicator',
      subject_id: 'climate change',
      subject_name: 'Climate change GWP100',
      indicator_key: 'climate change',
      method: 'EF v3.1',
      database_release: 'EF3.1',
      indicator_metadata_hash: 'a'.repeat(64),
      unit: 'kg CO2-Eq',
      unit_group: 'EF v3.1',
      unit_group_label: 'EF v3.1',
      series_id: 'lcia::EF3.1::EF v3.1::kg CO2-Eq',
      baseline_value: 2,
      scenario_values: { base: 2, efficient: 1.5 },
      deltas: { base: { absolute: 0, relative: 0 }, efficient: { absolute: -0.5, relative: -0.25 } },
    }], scenarioResults);

    expect(option.yAxis).toMatchObject({ type: 'category', data: ['climate change'] });
  });

  it('uses a narrower readable axis at the mobile breakpoint', () => {
    const option = buildComparisonChartOption(metrics, scenarioResults, true);
    expect(option.grid).toMatchObject({ left: 4, right: 8, top: 20, containLabel: true });
    expect(option.yAxis).toMatchObject({ axisLabel: { width: 92, fontSize: 10 } });
  });
});
