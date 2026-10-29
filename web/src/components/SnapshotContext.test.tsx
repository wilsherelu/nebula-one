import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/client';
import type { SolvedSystemSnapshot, SystemModel, SystemRevision } from '../api/types';
import { SnapshotContext, referenceUnit, userCalculationMethod } from './SnapshotContext';

const base: SolvedSystemSnapshot = {
  id: 'snapshot-1', application_id: 'app-1', system_revision_id: 'revision-1',
  inventory_snapshot_id: null, parameter_set_id: null,
  solve_hash: 'solve-hash', provider: 'nebula-lca', provider_receipt: {},
  functional_unit: { amount: 1, unit: 'kg' }, database_release: 'EF3.1', solver_version: 'provider-v1',
  activity_vector: [], scaled_technosphere_exchanges: [], scaled_elementary_exchanges: [],
  internal_transfers: [], boundary_flows: [], process_balance_residuals: [],
  contribution_graph: {}, lcia_results: {},
  content_sha256: 'snapshot-hash', created_at: '2026-09-01T08:00:00Z',
};

const methodContentHash = 'c'.repeat(64);

const methodSnapshot: SolvedSystemSnapshot = {
  ...base,
  provider_receipt: {
    user_calculation_method: {
      method_id: 'm-1',
      name: '集团范围一方法',
      purpose: 'organization',
      version: 3,
      model_revision_id: 'revision-1',
      content_sha256: methodContentHash,
      execution_plan_sha256: 'e'.repeat(64),
      compiler_version: 'nebula_one.method-compiler.v1',
      cbam_boundary_ref: null,
      validated_at: '2026-09-01T07:00:00Z',
      rules: [
        { process_instance_id: 'p1', direction: 'emission', boundary_status: 'selected', scope: 'scope_1', location_role: 'onsite', cbam_relevant: false, classification_basis: 'user', exchange_id: null, flow_uuid: null },
        { process_instance_id: 'p2', direction: 'emission', boundary_status: 'selected', scope: 'scope_1', location_role: 'onsite', cbam_relevant: false, classification_basis: 'user', exchange_id: null, flow_uuid: null },
        { process_instance_id: 'p3', direction: 'exchange', boundary_status: 'selected', scope: 'scope_2', location_role: 'purchased_energy', cbam_relevant: false, classification_basis: 'user', exchange_id: null, flow_uuid: null },
        { process_instance_id: 'p4', direction: 'emission', boundary_status: 'unclassified', scope: null, location_role: 'onsite', cbam_relevant: false, classification_basis: 'user', exchange_id: null, flow_uuid: null },
      ],
    },
  },
};

function mockContextQuery() {
  vi.spyOn(api, 'models').mockResolvedValue([{ id: 'model-1', name: '钢铁模型' } as SystemModel]);
  vi.spyOn(api, 'revisions').mockResolvedValue([{ id: 'revision-1', revision_number: 7 } as SystemRevision]);
}

function renderContext(snapshot: SolvedSystemSnapshot) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SnapshotContext snapshot={snapshot} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('userCalculationMethod', () => {
  it('reads the frozen method from the provider receipt', () => {
    const method = userCalculationMethod(methodSnapshot);
    expect(method).not.toBeNull();
    expect(method?.method_id).toBe('m-1');
    expect(method?.version).toBe(3);
  });

  it('returns null when no method was frozen', () => {
    expect(userCalculationMethod(base)).toBeNull();
  });

  it('returns null for a non-object receipt value', () => {
    expect(userCalculationMethod({ ...base, provider_receipt: { user_calculation_method: [] } })).toBeNull();
  });
});

describe('referenceUnit', () => {
  it('formats an object functional unit', () => {
    expect(referenceUnit({ amount: 2, unit: 'kg steel' })).toBe('2 kg steel');
  });

  it('passes through a string and falls back when absent', () => {
    expect(referenceUnit('1 kg')).toBe('1 kg');
    expect(referenceUnit(null)).toBe('未提供');
  });
});

describe('SnapshotContext with a frozen user method', () => {
  it('shows the method name/version and counts only selected rules by scope', async () => {
    mockContextQuery();
    const { container } = renderContext(methodSnapshot);

    expect(await screen.findByText('钢铁模型 · R7')).toBeInTheDocument();

    const methodLine = container.querySelector('.analysis-context__method');
    expect(methodLine?.textContent).toContain('集团范围一方法');
    expect(methodLine?.textContent).toContain('v3');

    const grouping = container.querySelector('.analysis-context__grouping');
    // p1+p2 -> scope_1, p3 -> scope_2, the unclassified rule adds to no scope count.
    expect(grouping?.textContent).toContain('Scope 1 2');
    expect(grouping?.textContent).toContain('Scope 2 1');
    expect(grouping?.textContent).toContain('Scope 3 0');
    // The grouping note states explicitly that uncovered items are not shown as zero.
    expect(grouping?.textContent).toContain('不会显示为零');

    const identity = container.querySelector('.frozen-input-identity pre');
    expect(identity?.textContent).toContain(methodContentHash);
    expect(identity?.textContent).toContain('revision-1');
    expect(identity?.textContent).toContain('e'.repeat(64));
    expect(identity?.textContent).toContain('nebula_one.method-compiler.v1');
  });

  it('omits the method line and grouping for a snapshot without a method', async () => {
    mockContextQuery();
    const { container } = renderContext(base);

    expect(await screen.findByText('钢铁模型 · R7')).toBeInTheDocument();
    expect(container.querySelector('.analysis-context__method')).toBeNull();
    expect(container.querySelector('.analysis-context__grouping')).toBeNull();
  });
});
