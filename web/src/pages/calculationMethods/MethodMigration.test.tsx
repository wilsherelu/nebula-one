import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { api } from '../../api/client';
import { MethodMigration } from './MethodMigration';
import type { CalculationMethod, CalculationMethodDetail } from '../../api/types';

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
it('copies an explicitly selected history version onto the exact target revision', async () => {
  const source = { id: 'source', name: '旧规则', purpose: 'pcf', model_revision_id: 'old' } as CalculationMethod;
  vi.spyOn(api, 'calculationMethods').mockResolvedValue([source, { ...source, id: 'foreign', model_revision_id: 'other-model' }]);
  vi.spyOn(api, 'calculationMethod').mockResolvedValue({ method: source, latest_version: 3, versions: [{ version: 1 }, { version: 3 }] } as CalculationMethodDetail);
  const clone = vi.spyOn(api, 'cloneCalculationMethod').mockResolvedValue({ method: { ...source, id: 'copy' } } as CalculationMethodDetail);
  const created = vi.fn();
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MethodMigration applicationId="app" revisionId="new" modelRevisionIds={['old', 'new']} onCreated={created} />
  </QueryClientProvider>);
  fireEvent.click(await screen.findByRole('combobox', { name: '来源核算方法' }));
  fireEvent.click(await screen.findByText('旧规则', { selector: '.arco-select-option' }));
  expect(screen.queryByText('foreign')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('combobox', { name: '来源规则版本' }));
  fireEvent.click(await screen.findByText('v1', { selector: '.arco-select-option' }));
  fireEvent.click(screen.getByRole('button', { name: '复制到当前数据版本' }));
  await waitFor(() => expect(clone).toHaveBeenCalledWith('source', 1, { name: '旧规则', purpose: 'pcf', model_revision_id: 'new' }));
  expect(created).toHaveBeenCalledWith('copy');
});
