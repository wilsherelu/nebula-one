import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { expect, it } from 'vitest';
import { AppShell } from './AppShell';

it('gives an exact method editor the full width without global navigation', () => {
  render(<MemoryRouter initialEntries={['/templates/steel/config?method=exact-method']}>
    <AppShell><main>Rule workspace</main></AppShell></MemoryRouter>);
  expect(screen.queryByRole('menuitem', {name:'首页'})).not.toBeInTheDocument();
  expect(screen.getByText('Rule workspace').closest('.app-shell')).toHaveStyle('--no-sidebar-width: 0px');
});

it('collapses and expands with keyboard while retaining accessible language selection', async () => {
  render(<MemoryRouter><AppShell><main>Workspace</main></AppShell></MemoryRouter>);
  const toggle = screen.getByRole('button', {name:'收起导航'});
  toggle.focus();
  await userEvent.keyboard('{Enter}');
  expect(screen.getByRole('button', {name:'展开导航'})).toHaveAttribute('aria-expanded', 'false');
  expect(screen.getByRole('button', {name:'界面语言'})).toBeInTheDocument();
  expect(screen.getByRole('menuitem', {name:'首页'})).toHaveAttribute('aria-current', 'page');
  expect(screen.getByText('Workspace').closest('.app-shell')).toHaveStyle('--no-sidebar-width: 64px');
  await userEvent.keyboard('{Enter}');
  expect(screen.getByRole('button', {name:'收起导航'})).toHaveAttribute('aria-expanded', 'true');
  expect(screen.getByRole('radio', {name:'English'})).toBeInTheDocument();
});
