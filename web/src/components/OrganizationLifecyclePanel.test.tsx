import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { api } from '../api/client';
import type { MethodPackage, SolvedSystemSnapshot } from '../api/types';
import { I18nProvider, LANGUAGE_STORAGE_KEY } from '../i18n';
import { OrganizationLifecyclePanel } from './OrganizationLifecyclePanel';

afterEach(() => {
  cleanup();
  window.localStorage.removeItem(LANGUAGE_STORAGE_KEY);
  vi.restoreAllMocks();
});

it('explains the missing exact supply receipt in English without a numeric result', () => {
  window.localStorage.setItem(LANGUAGE_STORAGE_KEY, 'en');
  vi.spyOn(api, 'periods').mockResolvedValue([]);
  vi.spyOn(api, 'workspace').mockRejectedValue(new Error('not needed for this state'));
  vi.spyOn(api, 'organizationLifecycleInventories').mockResolvedValue([]);
  const snapshot = {
    id: 'snapshot', system_revision_id: 'revision', provider_receipt: {},
  } as SolvedSystemSnapshot;
  const method = {
    package_id: 'organization-method', version: '1.0.0',
    manifest: { classification_rules: { energy_path_source: 'project_background_process_receipts' } },
  } as unknown as MethodPackage;
  render(<I18nProvider><QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <OrganizationLifecyclePanel applicationId="application" snapshot={snapshot} method={method} />
  </QueryClientProvider></I18nProvider>);
  expect(screen.getByText('This calculation method needs an exact supply receipt. Link a supply and recalculate.')).toBeInTheDocument();
  expect(screen.queryByText('0 kg CO₂e')).not.toBeInTheDocument();
});

it('uses the versioned English projection for organization categories and exchanges', async () => {
  window.localStorage.setItem(LANGUAGE_STORAGE_KEY, 'en');
  vi.spyOn(api, 'periods').mockResolvedValue([]);
  vi.spyOn(api, 'workspace').mockResolvedValue({ process_graph: { nodes: [{ id: 'steel' }] } } as never);
  vi.spyOn(api, 'organizationLifecycleInventories').mockResolvedValue([{
    id: 'record', solved_snapshot_id: 'snapshot', content_sha256: 'c'.repeat(64),
    result: { method_package: { reference: 'org.steel@1.0.5' }, reporting_period: { name: '2026', start_date: '2026-01-01', end_date: '2026-12-31' }, facility: 'Steel',
      activity_basis: { mode: 'per_unit_product', period_output: 1000, scale_factor: 1 },
      groups: { on_site_direct: { value: 10, unit: 'kg CO2-Eq', label: '范围 1：厂内直接排放', status: 'calculated_from_controlled_foreground' },
        purchased_energy_lifecycle: { value: 2, unit: 'kg CO2-Eq', label: 'LC-Scope 2：外购二次能源生命周期排放', status: 'calculated_from_exclusive_energy_background_paths' },
        other_value_chain: { value: null, unit: 'kg CO2-Eq', label: 'LC-Scope 3：其他价值链排放', status: 'partial', categories: [] } },
      combined_total: null, coverage: { missing_categories: ['purchased_iron_ore'], not_in_boundary_categories: [], demonstration_proxy_activity_ids: [] } },
  }] as never);
  vi.spyOn(api, 'organizationLifecycleDisplay').mockResolvedValue({
    schema_version: 'nebula_one.organization-lifecycle-display.v1', version: '1.0.0', language: 'en',
    projection_sha256: 'a'.repeat(64), method_package: { package_id: 'org.steel', version: '1.0.5', content_sha256: 'b'.repeat(64) },
    labels: { input_basis: { per_unit_product: 'Per unit of product' }, group_status: { partial: 'Some required data is missing' },
      categories: { purchased_iron_ore: 'Upstream purchased iron ore' },
      exchanges: { 'ore-sintering::iron-ore-in': 'Iron ore purchased for sintering' } },
  });
  const snapshot = { id: 'snapshot', system_revision_id: 'revision',
    provider_receipt: { project_background_process_receipts: [{}], calculation_basis: { demand: [{ amount: 1000, unit: 'kg' }] } },
    scaled_technosphere_exchanges: [{ exchange_id: 'ore-sintering::iron-ore-in', amount: 10, unit: 'kg' }],
  } as unknown as SolvedSystemSnapshot;
  const method = { package_id: 'org.steel', version: '1.0.5', content_sha256: 'b'.repeat(64),
    manifest: { classification_rules: { energy_path_source: 'project_background_process_receipts', other_value_chain_categories: {
      purchased_iron_ore: { name: '采购铁矿石上游', eligible_consumer_exchange_ids: ['ore-sintering::iron-ore-in'],
        exchange_labels: { 'ore-sintering::iron-ore-in': '烧结工序外购铁矿石' } },
    } } },
  } as unknown as MethodPackage;
  render(<I18nProvider><QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <OrganizationLifecyclePanel applicationId="application" snapshot={snapshot} method={method} />
  </QueryClientProvider></I18nProvider>);
  expect(await screen.findByText('2026-01-01—2026-12-31 · Steel')).toBeInTheDocument();
  expect(screen.queryByText('Iron ore purchased for sintering')).not.toBeInTheDocument();
  expect(screen.queryByRole('textbox', { name: 'Organization or facility name' })).not.toBeInTheDocument();
  expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  expect(screen.getByText('Scope 1: on site direct emissions')).toBeInTheDocument();
  expect(screen.getByText('Some required data is missing')).toBeInTheDocument();
  expect(screen.getByText('2026-01-01—2026-12-31 · Steel')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Open HTML report' })).toHaveAttribute('href', expect.stringContaining('report.html?lang=en'));
  expect(screen.queryByText('采购铁矿石上游')).not.toBeInTheDocument();
  expect(screen.queryByText('范围 1：厂内直接排放')).not.toBeInTheDocument();
  screen.getByRole('button', { name: 'Period scaling and additional activities' }).click();
  expect(await screen.findByText('Iron ore purchased for sintering')).toBeInTheDocument();
  expect(screen.getByRole('checkbox')).toBeInTheDocument();
});
