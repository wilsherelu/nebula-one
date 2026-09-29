import { render, screen, cleanup } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ProductCarbonFootprint } from '../api/types';
import { ContributionChart, processName } from './ContributionChart';

vi.mock('echarts-for-react', () => ({ default: ({ option }: { option: unknown }) => <pre data-testid="chart-option">{JSON.stringify(option)}</pre> }));
afterEach(cleanup);

describe('contribution chart projection', () => {
  it('preserves signed values, exact process labels and separate unit axes', () => {
    const result = { contribution_analysis: { status: 'available', hotspots: [
      { rank: 1, process_id: 'p', contribution_value: 12, contribution_unit: 'kg CO2-Eq' },
      { rank: 2, process_id: 'p', contribution_value: -2, contribution_unit: 'kg CO2-Eq' },
      { rank: 3, process_id: 'q', contribution_value: 0.5, contribution_unit: 't CO2-Eq' },
    ] } } as ProductCarbonFootprint;
    render(<ContributionChart result={result} nodes={[{ id: 'process:p', label: 'Hydrogen production' }]} />);
    const options = screen.getAllByTestId('chart-option').map((item) => JSON.parse(item.textContent!));
    expect(options).toHaveLength(2);
    expect(options[0].series[0].data.map((item: { value: number }) => item.value)).toEqual([12, -2]);
    expect(options[1].xAxis.name).toBe('t CO2-Eq');
    expect(options[0].yAxis.data[0]).toBe('1. Hydrogen production');
    expect(processName('unknown', [])).toBe('未提供过程名称');
  });
  it('does not invent a chart when receipts are unavailable', () => {
    render(<ContributionChart result={{ contribution_analysis: { status: 'unavailable', hotspots: [] } } as unknown as ProductCarbonFootprint} nodes={[]} />);
    expect(screen.queryByTestId('chart-option')).not.toBeInTheDocument();
  });
});
