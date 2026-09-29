import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, expect, it, vi } from 'vitest';
import { api } from '../api/client';
import type { Application, SystemModel, SystemRevision } from '../api/types';
import { ProfessionalProjectPage } from './ProfessionalProjectPage';

const application = {id: 'app', name: 'Professional project', context: {modeling_source: {project_id: 'upstream', version: 3}, modeling_functional_unit: {flow_uuid: 'product-flow', amount: 8, unit: 'kg'}}} as unknown as Application;
function mount(query = '', app = application) {
  vi.spyOn(api, 'models').mockResolvedValue([{id: 'model', name: 'Imported model', upstream_project_id: 'upstream', upstream_version: 3, upstream_receipt: {base_revision_id: 'revision'}}] as unknown as SystemModel[]);
  vi.spyOn(api, 'revisions').mockResolvedValue([{id: 'revision'}] as SystemRevision[]);
  vi.spyOn(api, 'solvedSnapshots').mockResolvedValue([]);
  render(<QueryClientProvider client={new QueryClient({defaultOptions: {queries: {retry: false}}})}><MemoryRouter initialEntries={['/' + query]}><ProfessionalProjectPage application={app} /></MemoryRouter></QueryClientProvider>);
}
afterEach(() => {cleanup(); vi.restoreAllMocks();});
it('solves the exact imported revision using the provider reference product', async () => {
  const solve = vi.spyOn(api, 'solveAndFreeze').mockRejectedValue(new Error('Engine rejected input'));
  mount();
  await userEvent.click(await screen.findByRole('button', {name: '计算物质流'}));
  await waitFor(() => expect(solve).toHaveBeenCalledWith('app', 'revision', {demand: [{reference_flow_uuid: 'product-flow', amount: 8, unit: 'kg'}], idempotency_key: 'modeling-revision-8'}));
  expect(await screen.findByText('Engine rejected input')).toBeInTheDocument();
});
it('does not replace an invalid explicit model with the first model', async () => {
  const solve = vi.spyOn(api, 'solveAndFreeze');
  mount('?model=unknown');
  expect(await screen.findByText('所选模型或数据版本不属于本项目，请返回项目列表重新进入。')).toBeInTheDocument();
  expect(screen.queryByRole('button', {name: '计算物质流'})).not.toBeInTheDocument();
  expect(solve).not.toHaveBeenCalled();
});
it('does not invent a reference product when the model only has descriptive text', async () => {
  mount('', {...application, context: {...application.context, modeling_functional_unit: '8 kg product'}});
  expect(await screen.findByRole('button', {name: '计算物质流'})).toBeDisabled();
});
