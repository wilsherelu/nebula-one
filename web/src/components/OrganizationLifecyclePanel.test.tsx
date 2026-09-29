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
  expect(screen.getByText('Link a user supplied process and calculate a product climate result that includes it first.')).toBeInTheDocument();
  expect(screen.queryByText('0 kg CO₂e')).not.toBeInTheDocument();
});

it('uses the versioned English projection for organization categories and exchanges', async () => {
  window.localStorage.setItem(LANGUAGE_STORAGE_KEY, 'en');
  vi.spyOn(api, 'periods').mockResolvedValue([]);
  vi.spyOn(api, 'workspace').mockResolvedValue({ process_graph: { nodes: [{ id: 'steel' }] } } as never);
  vi.spyOn(api, 'organizationLifecycleInventories').mockResolvedValue([]);
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
  expect(await screen.findByText('Upstream purchased iron ore')).toBeInTheDocument();
  expect(screen.getByText('Iron ore purchased for sintering')).toBeInTheDocument();
  expect(screen.queryByText('采购铁矿石上游')).not.toBeInTheDocument();
});
