import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createRef } from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { I18nProvider } from '../i18n';
import { ResultMenuActions, ResultMenuProvider, ResultMoreMenu } from './ResultHeaderActions';

afterEach(cleanup);
it('does not open an empty menu before the selected record is ready', () => {
  render(<I18nProvider><ResultMenuProvider scope="loading"><ResultMoreMenu actions={[]} triggerRef={createRef()} /></ResultMenuProvider></I18nProvider>);
  expect(screen.getByRole('button', { name: '更多' })).toBeDisabled();
});
it('updates flat actions to the selected record without stale callbacks and supports keyboard entry', async () => {
  const run = vi.fn();
  const triggerRef = createRef<HTMLButtonElement>();
  const view = (record: string) => <I18nProvider><ResultMenuProvider scope={record}>
    <ResultMoreMenu actions={[]} triggerRef={triggerRef} />
    <ResultMenuActions actions={[{ key: 'busy', label: 'Busy', export: true, disabled: true, run: () => run('disabled') },
      { key: 'export', label: 'Excel', export: true, run: () => run(record) }]} />
  </ResultMenuProvider></I18nProvider>;
  const rendered = render(view('A'));
  rendered.rerender(view('B'));
  await userEvent.click(screen.getByRole('button', { name: '更多' }));
  await userEvent.keyboard('{Escape}');
  expect(screen.getByRole('button', { name: '更多' })).toHaveAttribute('aria-expanded', 'false');
  await userEvent.keyboard('{ArrowDown}');
  const action = await screen.findByRole('menuitem', { name: 'Excel' });
  await waitFor(() => expect(action).toHaveFocus());
  await userEvent.keyboard('{Enter}');
  expect(run).toHaveBeenCalledWith('B');
  expect(run).toHaveBeenCalledOnce();
});
