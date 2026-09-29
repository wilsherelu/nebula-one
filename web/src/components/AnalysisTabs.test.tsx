import { Tabs } from '@arco-design/web-react';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { AnalysisTabs } from './AnalysisTabs';

afterEach(cleanup);

it('does not expose unsupported application panels for a template project', () => {
  render(<AnalysisTabs activeTab="pcf" allowedKeys={['mfa', 'pcf']} onChange={vi.fn()}>
    <Tabs.TabPane key="mfa" title="物质流">Material result</Tabs.TabPane>
    <Tabs.TabPane key="pcf" title="足迹">Footprint result</Tabs.TabPane>
    <Tabs.TabPane key="cbam" title="CBAM">Unbound CBAM</Tabs.TabPane>
    <Tabs.TabPane key="energy" title="能源">Unbound energy</Tabs.TabPane>
  </AnalysisTabs>);
  expect(screen.getByRole('tab', { name: '足迹' })).toHaveAttribute('aria-selected', 'true');
  expect(screen.getByText('Footprint result')).toBeVisible();
  expect(screen.queryByRole('tab', { name: 'CBAM' })).not.toBeInTheDocument();
  expect(screen.queryByText('Unbound CBAM')).not.toBeInTheDocument();
  expect(screen.queryByLabelText('更多分析')).not.toBeInTheDocument();
});

it('keeps the result tab list mounted while active content changes', () => {
  const change = vi.fn();
  const view = (activeTab: string) => <AnalysisTabs activeTab={activeTab} allowedKeys={['mfa', 'pcf', 'cbam']} onChange={change}>
    <Tabs.TabPane key="mfa" title="物质流">Material result</Tabs.TabPane>
    <Tabs.TabPane key="pcf" title="足迹">Footprint result</Tabs.TabPane>
    <Tabs.TabPane key="cbam" title="CBAM 试算">CBAM result</Tabs.TabPane>
  </AnalysisTabs>;
  const { rerender } = render(view('cbam'));
  const tabs = screen.getByRole('tablist', { name: '结果分析' });
  expect(screen.getByRole('tab', { name: 'CBAM 试算' })).toHaveAttribute('aria-selected', 'true');
  rerender(view('pcf'));
  expect(screen.getByRole('tablist', { name: '结果分析' })).toBe(tabs);
  expect(screen.getByRole('tab', { name: 'CBAM 试算' })).toBeVisible();
  expect(screen.getByText('Footprint result')).toBeVisible();
});
