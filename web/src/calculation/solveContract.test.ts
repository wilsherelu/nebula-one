import { describe, expect, it } from 'vitest';
import { buildSolvePayload, withRetrySuffix, solveIdempotencyKey } from './solveContract';

describe('buildSolvePayload', () => {
  it('keeps real UUID/hash keys bounded and distinguishes exact method versions and hash drift', async () => {
    const revision = '6760820f-af2e-464c-bdc2-53ed7e834109';
    const ref = { method_id: 'beb19499-59e4-4892-8467-92c228edf941', version: 2, content_sha256: 'a'.repeat(64) };
    const key = await solveIdempotencyKey('organization', revision, 'b'.repeat(64), ref);
    expect(withRetrySuffix(key, 999).length).toBeLessThanOrEqual(128);
    expect(await solveIdempotencyKey('organization', revision, 'b'.repeat(64), { ...ref })).toBe(key);
    expect(await solveIdempotencyKey('organization', revision, 'b'.repeat(64), { ...ref, version: 3 })).not.toBe(key);
    expect(await solveIdempotencyKey('organization', revision, 'b'.repeat(64), { ...ref, content_sha256: 'c'.repeat(64) })).not.toBe(key);
    expect(await solveIdempotencyKey('pcf', revision, 'b'.repeat(64), ref)).not.toBe(key);
  });
  it('emits a minimal MFA quick-start request', () => {
    expect(buildSolvePayload({
      demand: [{ reference_flow_uuid: 'product-flow', amount: 8, unit: 'kg' }],
      idempotencyKey: 'modeling-revision-8',
    })).toEqual({
      demand: [{ reference_flow_uuid: 'product-flow', amount: 8, unit: 'kg' }],
      idempotency_key: 'modeling-revision-8',
    });
  });

  it('adds lcia_methods only when present, matching the scenario case request', () => {
    const demand = [{ reference_flow_uuid: 'flow-final', amount: 1, unit: 'kg' }];
    expect(buildSolvePayload({ demand, idempotencyKey: 'case-x' }).lcia_methods).toBeUndefined();
    expect(buildSolvePayload({ demand, idempotencyKey: 'case-x', lciaMethods: [] }).lcia_methods).toBeUndefined();
    expect(buildSolvePayload({ demand, idempotencyKey: 'case-x', lciaMethods: ['EF v3.1'] }).lcia_methods).toEqual(['EF v3.1']);
  });

  it('keys a full PCF task with pins, method ref, purpose and climate basis', () => {
    const ref = { method_id: 'm-pcf', version: 2, content_sha256: 'a'.repeat(64) };
    expect(buildSolvePayload({
      demand: [{ reference_flow_uuid: 'steel', amount: 1000, unit: 'kg' }],
      backgroundProcessPins: [],
      mappedBackgroundProcessPins: [],
      projectBackgroundPins: [],
      idempotencyKey: 'calc-v2-pcf:r2:cc',
      task: 'pcf',
      calculationMethodRef: ref,
      calculationPurpose: 'lca',
    })).toEqual({
      demand: [{ reference_flow_uuid: 'steel', amount: 1000, unit: 'kg' }],
      background_process_pins: [],
      mapped_background_process_pins: [],
      idempotency_key: 'calc-v2-pcf:r2:cc',
      analysis_task: 'pcf',
      calculation_method_ref: ref,
      calculation_purpose: 'lca',
      climate_default: true,
    });
  });

  it('omits analysis_task for a bare CBAM trial with no purpose or cited method', () => {
    const payload = buildSolvePayload({
      demand: [{ reference_flow_uuid: 'steel', amount: 1, unit: 'kg' }],
      idempotencyKey: 'calc-v2-cbam:r2:cc',
      task: 'cbam',
    });
    expect(payload.analysis_task).toBeUndefined();
  });

  it('uses native_background_inventory instead of climate_default for a native MFA', () => {
    const payload = buildSolvePayload({
      demand: [{ reference_flow_uuid: 'steel', amount: 1, unit: 'kg' }],
      idempotencyKey: 'calc-v2-mfa:r2:cc',
      task: 'mfa',
      nativeBackgroundInventory: true,
    });
    expect(payload.native_background_inventory).toBe(true);
    expect(payload.climate_default).toBeUndefined();
  });

  it('applies the retry suffix only for a positive retry count', () => {
    expect(withRetrySuffix('base', 0)).toBe('base');
    expect(withRetrySuffix('base', 1)).toBe('base:retry-1');
  });
});

