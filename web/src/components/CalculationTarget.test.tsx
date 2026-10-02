import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import type { ProjectWorkspace } from '../api/types';
import { I18nProvider } from '../i18n';
import { CalculationTarget } from './CalculationTarget';

afterEach(cleanup);
it('shows the exact target flow name with the frozen demand, not the port amount', () => {
  const workspace = { fields: [
    { reference_product: true, flow_uuid: 'slab', label: '粗钢板坯', value: 1000 },
    { reference_product: true, flow_uuid: 'hot-metal', label: '铁水', value: 900 },
  ], demand: [{ reference_flow_uuid: 'slab', amount: 2000, unit: 'kg' }] } as ProjectWorkspace;
  render(<I18nProvider><CalculationTarget workspace={workspace} /></I18nProvider>);
  expect(screen.getByText('粗钢板坯')).toBeInTheDocument();
  expect(screen.getByText(/2,000 kg/)).toBeInTheDocument();
  expect(screen.queryByText('铁水')).not.toBeInTheDocument();
});
it('does not silently choose the first of multiple products', () => {
  render(<I18nProvider><CalculationTarget demand={[
    { reference_flow_uuid: 'first', amount: 1, unit: 'kg' },
    { reference_flow_uuid: 'second', amount: 2, unit: 'kg' },
  ]} /></I18nProvider>);
  expect(screen.getByText(/多个目标产品/)).toBeInTheDocument();
  expect(screen.queryByText('first')).not.toBeInTheDocument();
});
