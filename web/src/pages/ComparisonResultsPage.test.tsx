import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/client';
import type { ComparisonRun, PeriodEnergyComparisonResult } from '../api/types';
import { ComparisonResultsPage } from './ComparisonResultsPage';

vi.mock('echarts-for-react', () => ({ default: () => <div data-testid="comparison-chart" /> }));

const run: ComparisonRun = {
  id: 'run-1', application_id: 'app-1', comparison_id: 'comparison-1', baseline_scenario_id: 'base', status: 'succeeded',
  request: { baseline_scenario_id: 'base', demand: [{ reference_flow_uuid: 'flow-final', amount: 1, unit: 'kg' }] },
  scenario_results: [{
    scenario_id: 'base', scenario_name: '基准情景', scenario_hash: 'scenario-hash', system_revision_id: 'revision-1', solved_snapshot_id: 'snapshot-1',
    solved_snapshot_hash: 'snapshot-hash', solve_hash: 'solve-hash', provider_receipt: { run_id: 'provider-run' }, mfa_audit: { status: 'passed' }, sankey_url: '/api/sankey.svg',
  }],
  metrics: [{ metric_key: 'feed', flow_uuid: 'flow-feed', flow_name: 'Feedstock', direction: 'input', exchange_type: 'technosphere', unit: 'kg', unit_group: 'ug-mass', series_id: 'ug-mass::kg', baseline_value: 8, scenario_values: { base: 8 }, deltas: { base: { absolute: 0, relative: 0 } } }],
  audit: { status: 'passed', issues: [] }, error: {}, content_sha256: 'content-hash', created_at: '2026-08-30T08:00:00Z', completed_at: '2026-08-30T08:01:00Z',
};

const periodEnergy: PeriodEnergyComparisonResult = {
  schema_version: 'nebula_one.period-energy-scenario-comparison.v1',
  capability_key: 'energy.scenario-comparison.v1',
  reporting_period: { id: 'representative-year', version: '1.0.0', content_sha256: 'a'.repeat(64) },
  source_comparison_run: { id: 'run-1', content_sha256: 'b'.repeat(64) },
  comparison: {
    schema_version: 'nebula.energy-scenario-comparison.v1',
    baseline_scenario_id: 'base',
    base_revision_id: 'revision-0',
    scenarios: [
      { scenario_id: 'base', scenario_name: '基准情景', system_revision_id: 'revision-1', energy_result_content_sha256: 'c'.repeat(64) },
      { scenario_id: 'efficient', scenario_name: '节能情景', system_revision_id: 'revision-2', energy_result_content_sha256: 'd'.repeat(64) },
    ],
    metrics: [{
      metric_key: 'steam', label: '蒸汽', unit_symbol: 'MJ', values: { base: '100', efficient: '80' },
      deltas: { base: { absolute: '0', relative: '0' }, efficient: { absolute: '-20', relative: '-0.2' } },
      content_sha256: 'e'.repeat(64),
    }],
    issues: [], status: 'passed', content_sha256: 'f'.repeat(64),
  },
  audit: { status: 'passed', checks: {}, counts: { scenario_count: 2, metric_count: 1 }, issues: [], limitations: [] },
  content_sha256: '1'.repeat(64),
};

afterEach(() => {cleanup(); vi.restoreAllMocks();});

describe('comparison results page', () => {
  it('renders persisted metrics and keeps technical evidence in the audit drawer', async () => {
    vi.spyOn(api, 'comparisonRun').mockResolvedValue(run);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/comparison-runs/run-1']}>
          <Routes><Route path="/comparison-runs/:runId" element={<ComparisonResultsPage />} /></Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByText('Feedstock')).toBeInTheDocument();
    expect(screen.getByText('8')).toBeInTheDocument();
    expect(screen.queryByText('content-hash')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '审计证据' }));
    expect(await screen.findByText('content-hash')).toBeInTheDocument();
  });

  it('generates a reporting-period energy comparison on demand', async () => {
    vi.spyOn(api, 'comparisonRun').mockResolvedValue(run);
    vi.spyOn(api, 'periodEnergyComparison').mockResolvedValue(periodEnergy);
    vi.spyOn(api, 'periodEnergyComparisonChart').mockResolvedValue(new Blob(['<svg />'], { type: 'image/svg+xml' }));
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:period-energy') });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/comparison-runs/run-1']}>
          <Routes><Route path="/comparison-runs/:runId" element={<ComparisonResultsPage />} /></Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await userEvent.click(await screen.findByRole('button', { name: '生成期间能源对比' }));
    expect(await screen.findByText('representative-year@1.0.0')).toBeInTheDocument();
    expect((await screen.findAllByText('蒸汽')).length).toBe(2);
    expect(screen.getByText('-20%')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'representative-year 能源情景对比图' })).toHaveAttribute('src', 'blob:period-energy');
  });
});
