import { cleanup, render, screen, fireEvent } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import userEvent from '@testing-library/user-event';
import { FlowColumnTitle } from './FlowColumnTitle';

afterEach(cleanup);
it.each(['hover', 'focus', 'click'])('explains flows on %s', async (mode) => {
  render(<FlowColumnTitle />);
  const button = screen.getByRole('button', {name: /流是过程的投入和产出/});
  if (mode === 'hover') fireEvent.mouseEnter(button);
  if (mode === 'focus') fireEvent.focus(button);
  if (mode === 'click') await userEvent.setup().click(button);
  expect(await screen.findByText(/流是过程的投入和产出/)).toBeVisible();
});
