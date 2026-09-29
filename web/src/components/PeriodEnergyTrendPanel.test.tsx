import { describe, expect, it } from 'vitest';
import type { PeriodEnergyTrendResult } from '../api/types';
import { buildPeriodEnergyTrendRows } from './PeriodEnergyTrendPanel';

const result: PeriodEnergyTrendResult = {
  schema_version: 'nebula_one.period-energy-trend.v1',
  capability_key: 'energy.period-trend.v1',
  application_id: 'app-1',
  system_model_id: 'model-1',
  value_semantics: {
    kind: 'functional_unit_intensity',
    functional_unit: '1 kg product',
    functional_unit_sha256: 'a'.repeat(64),
    aggregation: 'none',
  },
  baseline_period_id: 'period-q1',
  observations: [
    {
      period: { id: 'period-q1', application_id: 'app-1', key: 'q1', name: '2025 Q1', start_date: '2025-01-01', end_date: '2025-03-31', resolution: 'quarter', created_at: '2026-09-01T00:00:00Z', content_sha256: 'b'.repeat(64) },
      source: {}, energy_result_content_sha256: 'c'.repeat(64),
    },
    {
      period: { id: 'period-q2', application_id: 'app-1', key: 'q2', name: '2025 Q2', start_date: '2025-04-01', end_date: '2025-06-30', resolution: 'quarter', created_at: '2026-09-01T00:00:00Z', content_sha256: 'd'.repeat(64) },
      source: {}, energy_result_content_sha256: 'e'.repeat(64),
    },
  ],
  metrics: [{
    metric_key: 'declared-energy', label: 'Purchased electricity', unit_symbol: 'MJ',
    basis: { energy_convention: 'declared_energy', material_condition: 'not_applicable' },
    values: { 'period-q1': '10', 'period-q2': '8' },
    deltas_from_baseline: {
      'period-q1': { absolute: '0', relative: '0' },
      'period-q2': { absolute: '-2', relative: '-0.2' },
    },
    deltas_from_previous: {
      'period-q1': null,
      'period-q2': { absolute: '-2', relative: '-0.2' },
    },
    summary: { minimum: '8', maximum: '10', arithmetic_mean: '9' },
    content_sha256: 'f'.repeat(64),
  }],
  issues: [], status: 'passed',
  audit: { status: 'passed', checks: {}, counts: { period_count: 2, metric_count: 1 }, limitations: [] },
  content_sha256: '1'.repeat(64),
};

describe('period energy trend table mapping', () => {
  it('keeps period order, units and both comparison meanings', () => {
    expect(buildPeriodEnergyTrendRows(result)).toEqual([
      { key: 'declared-energy:period-q1', metric: 'Purchased electricity', period: '2025 Q1', value: '10 MJ', baselineDelta: '0%', previousDelta: '—' },
      { key: 'declared-energy:period-q2', metric: 'Purchased electricity', period: '2025 Q2', value: '8 MJ', baselineDelta: '-20%', previousDelta: '-20%' },
    ]);
  });
});
