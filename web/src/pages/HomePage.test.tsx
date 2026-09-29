import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import {cleanup, render, screen} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {afterEach, expect, it, vi} from 'vitest';
import {api} from '../api/client';
import {HomePage} from './HomePage';

afterEach(() => {cleanup(); vi.restoreAllMocks();});

it('shows every project the release lists, without hiding any in the browser', async () => {
  const project = (id: string, name: string) => ({id, name, application_type: 'system_analysis', status: 'active',
    description: null, created_at: '2026-09-28T00:00:00Z', updated_at: '2026-09-28T00:00:00Z', context: {}});
  vi.spyOn(api, 'applications').mockResolvedValue([
    project('user', '用户钢厂'), project('second', 'Second works'), project('third', 'Third works'),
  ]);
  render(<QueryClientProvider client={new QueryClient({defaultOptions: {queries: {retry: false}}})}>
    <MemoryRouter><HomePage /></MemoryRouter>
  </QueryClientProvider>);
  expect(screen.getByRole('link', {name: /新建项目/})).toHaveAttribute('href', '/templates');
  for (const name of ['用户钢厂', 'Second works', 'Third works'])
    expect(await screen.findByRole('link', {name: new RegExp(name)})).toBeInTheDocument();
});
