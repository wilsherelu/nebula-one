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
