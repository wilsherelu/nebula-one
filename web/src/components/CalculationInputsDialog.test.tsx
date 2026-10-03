import { act, cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
import { api } from '../api/client';
import type { ProjectWorkspace, SolvedSystemSnapshot } from '../api/types';
import { CalculationInputsDialog } from './CalculationInputsDialog';
import { I18nProvider } from '../i18n';

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
it('keeps the selected frozen revision when an older inventory request finishes late; closing only closes', async () => {
  let resolveOld!: (workspace: ProjectWorkspace) => void;
  const old = new Promise<ProjectWorkspace>(resolve => { resolveOld = resolve; });
  const workspace = (revision: string, amount: number) => ({ revision_id: revision, demand: [],
    fields: [{ key: 'power', label: 'Electricity', process: 'Sinter', unit: 'MJ', value: amount }],
  } as unknown as ProjectWorkspace);
  const read = vi.spyOn(api, 'workspace').mockImplementation((_, revision) => revision === 'old' ? old : Promise.resolve(workspace('new', 610)));
  const close = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const snapshot = (revision: string) => ({ id: revision, system_revision_id: revision, created_at: '2026-10-03', provider_receipt: {} } as SolvedSystemSnapshot);
  const view = (revision: string) => <I18nProvider><QueryClientProvider client={client}>
    <CalculationInputsDialog applicationId="app" snapshot={snapshot(revision)} visible onClose={close} afterClose={() => {}} />
  </QueryClientProvider></I18nProvider>;
  const rendered = render(view('old'));
  rendered.rerender(view('new'));
  expect(await screen.findByText('610')).toBeInTheDocument();
  await act(async () => resolveOld(workspace('old', 600)));
  expect(screen.queryByText('600')).toBeNull();
  expect(screen.queryByRole('spinbutton')).toBeNull();
  await userEvent.click(screen.getByRole('button', { name: '关闭' }));
  expect(close).toHaveBeenCalledOnce();
  expect(read.mock.calls).toEqual([['app', 'old', 'zh'], ['app', 'new', 'zh']]);
});
