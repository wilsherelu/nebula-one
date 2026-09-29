import { describe, expect, it } from 'vitest';
import type {
  EnergyCarrierResult,
  InventoryDataPoint,
  InventorySnapshot,
  SolvedSystemSnapshot,
} from '../api/types';
import { resolvePeriodTotalRequest } from './PeriodEnergyTotalPanel';


const snapshots = [
  { id: 'snapshot-q1', system_revision_id: 'revision-q1' },
  { id: 'snapshot-q2', system_revision_id: 'revision-q2' },
] as SolvedSystemSnapshot[];
const energyResults = [
  { id: 'energy-q1', solved_snapshot_id: 'snapshot-q1' },
  { id: 'energy-q2', solved_snapshot_id: 'snapshot-q2' },
] as EnergyCarrierResult[];
const inventories = [
  { id: 'inventory-q1', name: 'Q1 output', period_id: 'period-q1', system_revision_id: 'revision-q1', status: 'frozen', content_sha256: 'a'.repeat(64) },
  { id: 'inventory-q2', name: 'Q2 output', period_id: 'period-q2', system_revision_id: 'revision-q2', status: 'frozen', content_sha256: 'b'.repeat(64) },
] as InventorySnapshot[];
const points = inventories.map((inventory, index) => ({
  id: `point-q${index + 1}`,
  inventory_snapshot_id: inventory.id,
  entity_id: null, process_id: null, flow_uuid: null,
  quantity: 1, unit: 'kg', source_type: 'test', evidence_id: 'evidence',
  uncertainty: {}, created_at: '2026-09-03T00:00:00Z',
  metric_key: 'period_product_output',
  quality_status: 'valid',
  review_status: 'approved',
  mapping_target: { role: 'period_product_output' },
})) as InventoryDataPoint[];
const bindings = [
  { period_id: 'period-q1', energy_result_id: 'energy-q1' },
  { period_id: 'period-q2', energy_result_id: 'energy-q2' },
];

describe('period energy total preflight', () => {
  it('does not report evidence readiness before period results are selected', () => {
    expect(resolvePeriodTotalRequest([], '', energyResults, snapshots, inventories, points)).toEqual({
      issues: ['请先为至少两个报告期选择不同的冻结能源结果。'],
    });
  });

  it('binds each period to one exact frozen inventory and approved activity', () => {
    expect(resolvePeriodTotalRequest(
      bindings, 'period-q1', energyResults, snapshots, inventories, points,
    )).toEqual({
      issues: [],
      request: {
        baseline_period_id: 'period-q1',
        observations: [
          { ...bindings[0], inventory_snapshot_id: 'inventory-q1', production_data_point_id: 'point-q1' },
          { ...bindings[1], inventory_snapshot_id: 'inventory-q2', production_data_point_id: 'point-q2' },
        ],
      },
    });
  });

  it('fails closed when an inventory is ambiguous', () => {
    const duplicate = { ...inventories[0], id: 'inventory-q1-copy' };
    const resolved = resolvePeriodTotalRequest(
      bindings, 'period-q1', energyResults, snapshots, [...inventories, duplicate], points,
    );
    expect(resolved.request).toBeUndefined();
    expect(resolved.issues[0]).toContain('需要且只能有一份');
  });
});
