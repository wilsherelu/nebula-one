import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useNavigate, useSearchParams } from 'react-router-dom';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import {
  parseUrlSelectionPairs,
  resolveUrlSelection,
  serializeUrlSelectionPairs,
  useUrlSelection,
  useUrlSelectionMap,
} from './useUrlSelection';

afterEach(cleanup);

describe('resolveUrlSelection', () => {
  it('keeps the initial choice only when the analyst did not reference anything', () => {
    expect(resolveUrlSelection(null, ['first', 'second'], true)).toEqual({ value: 'first', pending: false, invalid: false });
    expect(resolveUrlSelection(null, [], true)).toEqual({ value: '', pending: false, invalid: false });
  });

  it('accepts an explicit reference and rejects one outside the catalog instead of falling back', () => {
    expect(resolveUrlSelection('second', ['first', 'second'], true)).toEqual({ value: 'second', pending: false, invalid: false });
    expect(resolveUrlSelection('other-app', ['first', 'second'], true)).toEqual({ value: '', pending: false, invalid: true });
  });

  it('holds an explicit reference unresolved while its catalog is still loading', () => {
    expect(resolveUrlSelection('second', [], false)).toEqual({ value: '', pending: true, invalid: false });
  });

  it('uses a fallback only when it exists in the catalog', () => {
    expect(resolveUrlSelection(null, ['first', 'second'], true, 'second')).toEqual({ value: 'second', pending: false, invalid: false });
    expect(resolveUrlSelection(null, ['first', 'second'], true, 'gone')).toEqual({ value: 'first', pending: false, invalid: false });
    expect(resolveUrlSelection('', ['first'], true)).toEqual({ value: '', pending: false, invalid: true });
  });
});

describe('selection pair encoding', () => {
  it('round-trips period bindings and drops malformed entries', () => {
    expect(serializeUrlSelectionPairs({ q1: 'energy-1', q2: 'energy-2' })).toBe('q1:energy-1;q2:energy-2');
    expect(parseUrlSelectionPairs('q1:energy-1;q2:energy-2')).toEqual({ q1: 'energy-1', q2: 'energy-2' });
    expect(parseUrlSelectionPairs('broken;q:;q2:energy-2')).toEqual({ q2: 'energy-2' });
    expect(parseUrlSelectionPairs('q1:energy-1;q2:energy-2:extra')).toEqual({ q1: 'energy-1' });
    expect(parseUrlSelectionPairs(null)).toEqual({});
  });
});

function SingleProbe({ ids, ready }: { ids: string[]; ready: boolean }) {
  const selection = useUrlSelection('method', ids, { ready, clearKeys: ['scenario'] });
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  return <>
    <output data-testid="state">{JSON.stringify({ value: selection.value, requested: selection.requested, pending: selection.pending, invalid: selection.invalid })}</output>
    <output data-testid="search">{searchParams.toString()}</output>
    <button onClick={() => selection.select('second')}>选择 second</button>
    <button onClick={selection.clear}>清除引用</button>
    <button onClick={() => navigate(-1)}>浏览器后退</button>
  </>;
}

function MapProbe({ ready }: { ready: boolean }) {
  const bindings = useUrlSelectionMap('bindings', { q1: ['energy-1', 'energy-2'], q2: ['energy-1'] }, { ready });
  return <output data-testid="map">{JSON.stringify({ values: bindings.values, invalid: bindings.invalid })}</output>;
}

function renderAt(entry: string, ui: ReactNode) {
  return render(<MemoryRouter initialEntries={[entry]}><div>{ui}</div></MemoryRouter>);
}

describe('useUrlSelection', () => {
  it('changes a method and resets its dependent selection in one history entry', async () => {
    renderAt('/results?view=organization-ghg&method=first&scenario=old', <SingleProbe ids={['first', 'second']} ready />);
    await userEvent.click(screen.getByRole('button', { name: '选择 second' }));
    expect(screen.getByTestId('search').textContent).toBe('view=organization-ghg&method=second');
    await userEvent.click(screen.getByRole('button', { name: '浏览器后退' }));
    expect(screen.getByTestId('search').textContent).toBe('view=organization-ghg&method=first&scenario=old');
  });

  it('writes the choice into the URL and keeps unrelated query parameters', async () => {
    renderAt('/applications/app-1/results?view=cbam&snapshot=snapshot-1', <SingleProbe ids={['first', 'second']} ready />);
    expect(JSON.parse(screen.getByTestId('state').textContent ?? '{}')).toEqual({ value: 'first', requested: '', pending: false, invalid: false });
    await userEvent.click(screen.getByRole('button', { name: '选择 second' }));
    expect(JSON.parse(screen.getByTestId('state').textContent ?? '{}')).toEqual({ value: 'second', requested: 'second', pending: false, invalid: false });
    expect(screen.getByTestId('search').textContent).toBe('view=cbam&snapshot=snapshot-1&method=second');
  });

  it('returns to the previous selection with browser back', async () => {
    renderAt('/applications/app-1/results?view=cbam&snapshot=snapshot-1', <SingleProbe ids={['first', 'second']} ready />);
    await userEvent.click(screen.getByRole('button', { name: '选择 second' }));
    await userEvent.click(screen.getByRole('button', { name: '浏览器后退' }));
    expect(JSON.parse(screen.getByTestId('state').textContent ?? '{}')).toMatchObject({ value: 'first', requested: '' });
    expect(screen.getByTestId('search').textContent).toBe('view=cbam&snapshot=snapshot-1');
  });

  it('clears a rejected reference without dropping other parameters', async () => {
    renderAt('/applications/app-1/results?view=cbam&method=removed-package', <SingleProbe ids={['first', 'second']} ready />);
    expect(JSON.parse(screen.getByTestId('state').textContent ?? '{}')).toEqual({ value: '', requested: 'removed-package', pending: false, invalid: true });
    await userEvent.click(screen.getByRole('button', { name: '清除引用' }));
    expect(JSON.parse(screen.getByTestId('state').textContent ?? '{}')).toMatchObject({ value: 'first', requested: '', invalid: false });
    expect(screen.getByTestId('search').textContent).toBe('view=cbam');
  });

  it('does not mark an explicit reference invalid before its catalog arrives', () => {
    renderAt('/applications/app-1/results?method=second', <SingleProbe ids={[]} ready={false} />);
    expect(JSON.parse(screen.getByTestId('state').textContent ?? '{}')).toEqual({ value: '', requested: 'second', pending: true, invalid: false });
  });
});

describe('useUrlSelectionMap', () => {
  it.each(['broken', 'q1:', 'q1:energy-1:extra', 'q1:energy-1;q1:energy-2', 'constructor:energy-1', '__proto__:energy-1'])('rejects malformed or ambiguous bindings: %s', (raw) => {
    renderAt(`/results?bindings=${raw}`, <MapProbe ready />);
    const state = JSON.parse(screen.getByTestId('map').textContent ?? '{}');
    expect(state.invalid.length).toBeGreaterThan(0);
  });

  it('resolves explicit entries against each key candidates', () => {
    renderAt('/results?bindings=q1:energy-2;q2:energy-1', <MapProbe ready />);
    expect(JSON.parse(screen.getByTestId('map').textContent ?? '{}')).toEqual({ values: { q1: 'energy-2', q2: 'energy-1' }, invalid: [] });
  });

  it('reports a rejected period or energy result instead of guessing', () => {
    renderAt('/results?bindings=q1:energy-9;q3:energy-1', <MapProbe ready />);
    expect(JSON.parse(screen.getByTestId('map').textContent ?? '{}')).toEqual({ values: {}, invalid: ['q1', 'q3'] });
  });

  it('holds explicit entries unresolved while the catalog loads', () => {
    renderAt('/results?bindings=q1:energy-2', <MapProbe ready={false} />);
    expect(JSON.parse(screen.getByTestId('map').textContent ?? '{}')).toEqual({ values: {}, invalid: [] });
  });
});
