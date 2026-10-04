import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { expect, it } from 'vitest';
import { AppShell } from './AppShell';

it('collapses and expands with keyboard while retaining accessible language selection', async () => {
  render(<MemoryRouter><AppShell><main>Workspace</main></AppShell></MemoryRouter>);
  const toggle = screen.getByRole('button', {name:'收起导航'});
  toggle.focus();
  await userEvent.keyboard('{Enter}');
  expect(screen.getByRole('button', {name:'展开导航'})).toHaveAttribute('aria-expanded', 'false');
  expect(screen.getByRole('button', {name:'界面语言'})).toBeInTheDocument();
  expect(screen.getByText('Workspace').closest('.app-shell')).toHaveStyle('--no-sidebar-width: 64px');
  await userEvent.keyboard('{Enter}');
  expect(screen.getByRole('button', {name:'收起导航'})).toHaveAttribute('aria-expanded', 'true');
  expect(screen.getByRole('radio', {name:'English'})).toBeInTheDocument();
});
