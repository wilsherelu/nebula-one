import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { api } from '../api/client';
import type { Application, ProjectWorkspace, SolvedSystemSnapshot } from '../api/types';
import { CalculationInputsPage } from './CalculationInputsPage';

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
it('reads the exact record revision and switches inventory with records, never current data', async () => {
  vi.spyOn(api, 'application').mockResolvedValue({ name: 'Steel' } as Application);
  vi.spyOn(api, 'solvedSnapshots').mockResolvedValue([
    { id: 'A', system_revision_id: 'old', created_at: '2026-10-01', provider_receipt: { calculation_basis: { demand: [{ reference_flow_uuid: 'product', amount: 1000, unit: 'kg' }] } } },
    { id: 'B', system_revision_id: 'new', created_at: '2026-10-02', provider_receipt: { calculation_basis: { demand: [{ reference_flow_uuid: 'product', amount: 2000, unit: 'kg' }] } } },
  ] as unknown as SolvedSystemSnapshot[]);
  const read = vi.spyOn(api, 'workspace').mockImplementation(async (_, revision) => ({
    revision_id: revision, content_sha256: `${revision}-hash`, demand: [],
    fields: [{ key: 'power', process: 'Sinter', label: 'Electricity', unit: 'MJ', value: revision === 'old' ? 600 : 610 }],
    project_background_pins: [{ consumer_exchange_id: 'sinter::electricity', project_id: 'supply', version: revision === 'old' ? 1 : 2, expected_graph_hash: `${revision}-background` }],
  } as unknown as ProjectWorkspace));
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={['/applications/app/calculation-inputs?snapshot=A']}><Routes>
      <Route path="/applications/:applicationId/calculation-inputs" element={<CalculationInputsPage />} />
      <Route path="/applications/:applicationId/workbench" element={<p>Current project</p>} />
    </Routes></MemoryRouter>
  </QueryClientProvider>);
  expect(await screen.findByText('600')).toBeInTheDocument();
  expect(read).toHaveBeenLastCalledWith('app', 'old', 'zh');
  expect(screen.getByText(/old-background/)).toBeInTheDocument();
  expect(screen.queryByRole('spinbutton')).toBeNull();
  await userEvent.click(screen.getByRole('combobox'));
  fireEvent.click(screen.getByRole('option', { name: /记录 2/ }));
  expect(await screen.findByText('610')).toBeInTheDocument();
  await waitFor(() => expect(read).toHaveBeenLastCalledWith('app', 'new', 'zh'));
  expect(screen.getByText(/new-background/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: '返回项目' }));
  expect(await screen.findByText('Current project')).toBeInTheDocument();
});
