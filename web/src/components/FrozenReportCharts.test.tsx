import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { FrozenReport } from '../api/types';
import { FrozenReportCharts, organizationChartData } from './FrozenReportCharts';

vi.mock('echarts-for-react', () => ({default: ({option}: {option: unknown}) => <pre data-testid="chart">{JSON.stringify(option)}</pre>}));
afterEach(cleanup);
const report: FrozenReport = {kind: 'organization', schema_version: 'nebula_one.frozen-report.v1', snapshot_id: 'snapshot',
  revision_id: 'revision', title: 'Organization', method_name: null, method_version: '1', sources: {}, status_labels: {},
  details: [], process_contributions: [], outside_boundary: [],
  complete_total: null, gaps: [{name: 'Supply', status: 'missing'}], uncharacterized: [],
  group_labels: {direct: 'Direct', energy: 'Energy', other: 'Other'}, summary: [
    {group: 'direct', value: 12, unit: 'kg', status: 'partial'}, {group: 'energy', value: 3, unit: 'kg', status: 'partial'},
    {group: 'other', value: null, unit: 'kg', status: 'missing'},
  ]};
it('uses known values with explicit partial denominator; never replaces null with zero', () => {
  expect(organizationChartData(report)).toMatchObject({denominator: 15, donut: true, partial: true});
  render(<FrozenReportCharts report={report} />);
  const chart = JSON.parse(screen.getByTestId('chart').textContent!);
  expect(chart.series[0].data).toEqual([{name: 'Direct', value: 12}, {name: 'Energy', value: 3}]);
  expect(screen.getByRole('heading', {name: '已计算部分构成'})).toBeVisible();
  expect(screen.getByText(/15 kg/)).toBeVisible();
});
it('keeps negatives and noncomparable units out of percentage charts', () => {
  for (const summary of [[{...report.summary[0], value: -1}], [report.summary[0], {...report.summary[1], unit: 't'}]]) {
    expect(organizationChartData({...report, summary}).donut).toBe(false);
  }
  expect(organizationChartData({...report, summary: report.summary.map(row => ({...row, value: null}))}).rows).toEqual([]);
});
it('CBAM uses its own signed process values and units', () => {
  render(<FrozenReportCharts report={{...report, kind: 'cbam', process_contributions: [
    {group: 'direct', process_id: 'a', process_name: 'A', contribution_value: 7, contribution_unit: 'kg CO2e'},
    {group: 'direct', process_id: 'b', process_name: 'B', contribution_value: -2, contribution_unit: 'kg CO2e'},
  ]}} />);
  const chart = JSON.parse(screen.getByTestId('chart').textContent!);
  expect(chart.series[0].data.map((row: {value:number}) => row.value)).toEqual([7, -2]);
  expect(chart.xAxis.name).toBe('kg CO2e');
});
