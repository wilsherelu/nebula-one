import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import type { CalculationMethodRule, CalculationMethodVersion, MethodDimension, ModelProcessingRulesRef } from '../../api/types';
import { useMethodDraft } from './useMethodDraft';

const APP = 'app';
const REV = 'rev';
const METHOD = 'method';

const ruleA: CalculationMethodRule = {
  process_instance_id: 'p1', exchange_id: 'e1', flow_uuid: 'f1', direction: 'emission',
  boundary_status: 'selected', location_role: 'onsite', scope: 'scope_1', cbam_relevant: false, classification_basis: 'user',
};
const ruleB: CalculationMethodRule = {
  process_instance_id: 'p2', exchange_id: null, flow_uuid: null, direction: 'emission',
  boundary_status: 'pending', location_role: 'other', scope: null, cbam_relevant: false, classification_basis: 'user',
};

const SHA1 = 'a'.repeat(64);
const SHA2 = 'b'.repeat(64);

const version = (n: number, sha: string, rules: CalculationMethodRule[]): CalculationMethodVersion => ({
  id: `v${n}`, method_id: METHOD, version: n, cbam_boundary_ref: null, content_sha256: sha,
  status: 'ready', created_at: '', validated_at: null, rules,
});

const slotKey = (sha: string) => `nebula.calc-method-draft:${APP}:${REV}:${METHOD}:${sha}`;

const mountDraft = (latest: CalculationMethodVersion, versions: CalculationMethodVersion[]) =>
  renderHook(props => useMethodDraft(APP, REV, METHOD, props.versions, props.latest, 'My Method', null),
    { initialProps: { latest, versions } });

describe('useMethodDraft keeps an unsaved draft when the head version moves', () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => localStorage.clear());

  it('preserves the previous draft and does not auto-apply it to the new version', () => {
    const v1 = version(1, SHA1, [ruleA, ruleB]);
    const { result, rerender } = mountDraft(v1, [v1]);

    act(() => { result.current.updateRule('p1::e1::f1::emission', { scope: 'scope_2' }); });
    expect(result.current.dirty).toBe(true);
    expect(JSON.parse(localStorage.getItem(slotKey(SHA1)) as string).edits['p1::e1::f1::emission']).toEqual({ scope: 'scope_2' });

    // Another page/writer lands v2; this page's latestVersion and versions change to the new head.
    const v2 = version(2, SHA2, [ruleA, ruleB]);
    rerender({ latest: v2, versions: [v1, v2] });

    // Unsaved input survives: the v1 slot is untouched and surfaced as a quarantined stale draft.
    expect(localStorage.getItem(slotKey(SHA1))).not.toBeNull();
    expect(result.current.stale).not.toBeNull();
    expect(result.current.stale?.baseVersion).toBe(1);
    expect(result.current.stale?.editedCount).toBe(1);

    // The old edit is NOT silently folded onto the new head: current rules stay v2's server content.
    expect(result.current.dirty).toBe(false);
    expect(result.current.rules.find(r => r.process_instance_id === 'p1')?.scope).toBe('scope_1');
  });

  it('survives a page reload against the new head', () => {
    const v1 = version(1, SHA1, [ruleA, ruleB]);
    const first = mountDraft(v1, [v1]);
    act(() => { first.result.current.addRule({ ...ruleB, process_instance_id: 'p9', flow_uuid: null, exchange_id: null }); });
    first.unmount();

    // A fresh mount with the head now on v2 still finds the preserved v1 draft from storage.
    const v2 = version(2, SHA2, [ruleA, ruleB]);
    const remounted = mountDraft(v2, [v1, v2]);
    expect(remounted.result.current.stale).not.toBeNull();
    expect(remounted.result.current.stale?.addedCount).toBe(1);
    expect(remounted.result.current.dirty).toBe(false);
  });

  it('migrates the old draft onto the current head only on explicit request', () => {
    const v1 = version(1, SHA1, [ruleA, ruleB]);
    const { result, rerender } = mountDraft(v1, [v1]);
    act(() => { result.current.updateRule('p1::e1::f1::emission', { scope: 'scope_2' }); });
    const v2 = version(2, SHA2, [ruleA, ruleB]);
    rerender({ latest: v2, versions: [v1, v2] });
    expect(result.current.rules.find(r => r.process_instance_id === 'p1')?.scope).toBe('scope_1');

    act(() => { result.current.migrateStale(); });
    expect(result.current.stale).toBeNull();
    expect(result.current.dirty).toBe(true);
    expect(result.current.rules.find(r => r.process_instance_id === 'p1')?.scope).toBe('scope_2');
  });

  it('discards the old draft without touching the current base slot', () => {
    const v1 = version(1, SHA1, [ruleA, ruleB]);
    const { result, rerender } = mountDraft(v1, [v1]);
    act(() => { result.current.updateRule('p1::e1::f1::emission', { scope: 'scope_2' }); });
    const v2 = version(2, SHA2, [ruleA, ruleB]);
    rerender({ latest: v2, versions: [v1, v2] });

    act(() => { result.current.discardStale(); });
    expect(result.current.stale).toBeNull();
    expect(localStorage.getItem(slotKey(SHA1))).toBeNull();
  });
});

const PLANT_SPLIT: MethodDimension = {
  id: 'plant_split', name: 'Plant split', source: 'user',
  categories: [
    { id: 'onsite_production', name: 'Onsite production', is_leaf: true },
    { id: 'purchased_energy', name: 'Purchased energy', is_leaf: true },
  ],
};

describe('useMethodDraft threads user-defined reporting dimensions', () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => localStorage.clear());

  it('inherits the base dimensions with no edit and starts clean', () => {
    const v1 = { ...version(1, SHA1, [ruleA, ruleB]), reporting_dimensions: [PLANT_SPLIT] };
    const { result } = mountDraft(v1, [v1]);
    expect(result.current.dimensions).toEqual([PLANT_SPLIT]);
    expect(result.current.dirty).toBe(false);
  });

  it('marks dirty on a dimension edit, persists it, and clears when reverted to the base', () => {
    const v1 = { ...version(1, SHA1, [ruleA, ruleB]), reporting_dimensions: [PLANT_SPLIT] };
    const { result } = mountDraft(v1, [v1]);

    const edited: MethodDimension[] = [{ ...PLANT_SPLIT, categories: [...PLANT_SPLIT.categories, { id: 'upstream_materials', name: 'Upstream materials', is_leaf: true }] }];
    act(() => { result.current.setDimensions(edited); });
    expect(result.current.dimensions).toEqual(edited);
    expect(result.current.dirty).toBe(true);
    expect(JSON.parse(localStorage.getItem(slotKey(SHA1)) as string).dimensions).toEqual(edited);

    // Reverting to exactly the server base drops the overlay so the draft is no longer marked dirty.
    act(() => { result.current.setDimensions([PLANT_SPLIT]); });
    expect(result.current.dirty).toBe(false);
    expect(localStorage.getItem(slotKey(SHA1))).toBeNull();
  });

  it('carries a declared dimension into a quarantined stale draft and migrates it onto the new head', () => {
    const v1 = version(1, SHA1, [ruleA, ruleB]);
    const { result, rerender } = mountDraft(v1, [v1]);
    act(() => { result.current.setDimensions([PLANT_SPLIT]); });
    expect(result.current.dimensions).toEqual([PLANT_SPLIT]);

    const v2 = version(2, SHA2, [ruleA, ruleB]);
    rerender({ latest: v2, versions: [v1, v2] });
    expect(result.current.stale?.dimensions).toEqual([PLANT_SPLIT]);

    act(() => { result.current.migrateStale(); });
    expect(result.current.dimensions).toEqual([PLANT_SPLIT]);
    expect(result.current.dirty).toBe(true);
  });
});

const VARIANT_REF: ModelProcessingRulesRef = { package_id: 'steel-bf-bof.model-processing', version: '1.0.12', content_sha256: 'c'.repeat(64) };

describe('useMethodDraft binds an exact processing package for a variant', () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => localStorage.clear());

  it('keeps the official default clean and unbound', () => {
    const v1 = version(1, SHA1, [ruleA, ruleB]);
    const { result } = mountDraft(v1, [v1]);
    expect(result.current.processingRef).toBeNull();
    expect(result.current.dirty).toBe(false);
  });

  it('marks dirty on a package bind, persists it, and clears when reverted to the base', () => {
    const v1 = version(1, SHA1, [ruleA, ruleB]);
    const { result } = mountDraft(v1, [v1]);

    act(() => { result.current.setProcessingRef(VARIANT_REF); });
    expect(result.current.processingRef).toEqual(VARIANT_REF);
    expect(result.current.dirty).toBe(true);
    expect(JSON.parse(localStorage.getItem(slotKey(SHA1)) as string).processing_ref).toEqual(VARIANT_REF);

    // Reverting to the automatic default the base already carries clears the overlay, not a null-vs-absent bug.
    act(() => { result.current.setProcessingRef(null); });
    expect(result.current.processingRef).toBeNull();
    expect(result.current.dirty).toBe(false);
    expect(localStorage.getItem(slotKey(SHA1))).toBeNull();
  });

  it('treats an explicit automatic choice as a real change on a version that already binds a package', () => {
    const v1 = { ...version(1, SHA1, [ruleA, ruleB]), model_processing_rules_ref: VARIANT_REF };
    const { result } = mountDraft(v1, [v1]);

    // Untouched head inherits the base binding exactly, with no false dirty.
    expect(result.current.processingRef).toEqual(VARIANT_REF);
    expect(result.current.dirty).toBe(false);

    // Switching to automatic on a base that carries a package IS a change and survives reload as null.
    act(() => { result.current.setProcessingRef(null); });
    expect(result.current.processingRef).toBeNull();
    expect(result.current.dirty).toBe(true);
    expect(JSON.parse(localStorage.getItem(slotKey(SHA1)) as string).processing_ref).toBeNull();
  });

  it('carries the binding into a quarantined stale draft and migrates it onto the new head', () => {
    const v1 = version(1, SHA1, [ruleA, ruleB]);
    const { result, rerender } = mountDraft(v1, [v1]);
    act(() => { result.current.setProcessingRef(VARIANT_REF); });

    const v2 = version(2, SHA2, [ruleA, ruleB]);
    rerender({ latest: v2, versions: [v1, v2] });
    expect(result.current.stale?.processingRef).toEqual(VARIANT_REF);
    expect(result.current.processingRef).toBeNull();

    act(() => { result.current.migrateStale(); });
    expect(result.current.processingRef).toEqual(VARIANT_REF);
    expect(result.current.dirty).toBe(true);
  });
});
