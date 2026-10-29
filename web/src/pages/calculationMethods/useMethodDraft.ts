import { useCallback, useEffect, useMemo, useState } from 'react';
import type { CalculationMethodRule, CalculationMethodVersion, MethodDimension, ModelProcessingRulesRef } from '../../api/types';
import { ruleIdentity } from './labels';

export interface MethodDraftMeta {
  name: string;
  description: string | null;
  cbam_boundary_ref: string | null;
}

/** A draft is an overlay of user edits on top of one exact server version, stored against that version's
 * content hash. When the head moves (a save lands here, or another page/writer saves), the in-progress
 * overlay must NOT be dropped: it stays in storage under its own base hash so unsaved input is never lost.
 * The new head simply has no overlay yet, so the UI shows the previous draft as a quarantined `stale`
 * draft and lets the user compare, discard, or explicitly migrate it. Old inputs are never silently
 * re-applied onto a different base. Editing is always relative to the latest version; history is read-only.
 *
 * Rules are addressed by identity, never by position, because the user both edits inherited rules and
 * adds or removes whole rules. An added rule is a full rule object; a removed server rule is remembered
 * by identity so it drops from the saved list while the server base stays immutable until the save lands. */
interface DraftOverlay {
  based_on: string;
  saved_at: number;
  edits: Record<string, Partial<CalculationMethodRule>>;
  added: CalculationMethodRule[];
  removed: string[];
  meta: Partial<MethodDraftMeta> | null;
  dimensions: MethodDimension[] | null;
  // Three-state binding: undefined inherits the server base, null is an explicit "automatic" choice,
  // an object pins an exact reviewed package. null and undefined mean different things here.
  processing_ref: ModelProcessingRulesRef | null | undefined;
}

const emptyOverlay = (basedOn: string): DraftOverlay =>
  ({ based_on: basedOn, saved_at: 0, edits: {}, added: [], removed: [], meta: null, dimensions: null, processing_ref: undefined });

const hasContent = (overlay: DraftOverlay) =>
  Object.keys(overlay.edits).length > 0 || overlay.added.length > 0 || overlay.removed.length > 0 || overlay.meta !== null || overlay.dimensions !== null || overlay.processing_ref !== undefined;

function draftKey(applicationId: string, revisionId: string, methodId: string, basedOn: string) {
  return `nebula.calc-method-draft:${applicationId}:${revisionId}:${methodId}:${basedOn || 'new'}`;
}

function draftPrefix(applicationId: string, revisionId: string, methodId: string) {
  return `nebula.calc-method-draft:${applicationId}:${revisionId}:${methodId}:`;
}

function parse(raw: string | null): DraftOverlay | null {
  if (!raw) return null;
  try {
    const stored = JSON.parse(raw) as Partial<DraftOverlay>;
    return {
      based_on: stored.based_on ?? '',
      saved_at: stored.saved_at ?? 0,
      edits: stored.edits ?? {},
      added: Array.isArray(stored.added) ? stored.added : [],
      removed: Array.isArray(stored.removed) ? stored.removed : [],
      meta: stored.meta ?? null,
      dimensions: Array.isArray(stored.dimensions) ? stored.dimensions : null,
      // JSON.stringify drops an undefined key, so an absent key means "inherit base" while an explicit
      // null means "the user chose automatic" — the two must not collapse into one on reload.
      processing_ref: 'processing_ref' in stored ? stored.processing_ref : undefined,
    };
  } catch {
    return null;
  }
}

function load(key: string, basedOn: string): DraftOverlay {
  const stored = parse(localStorage.getItem(key));
  // Only resume a draft that was built against this exact base; otherwise the current head starts clean.
  if (!stored || stored.based_on !== basedOn) return emptyOverlay(basedOn);
  return stored;
}

/** Find the most recent draft stored against a different base — the previous version's unsaved input. */
function findStale(prefix: string, activeKey: string, currentBase: string): { overlay: DraftOverlay; key: string } | null {
  let best: { overlay: DraftOverlay; key: string } | null = null;
  for (let index = 0; index < localStorage.length; index += 1) {
    const key = localStorage.key(index);
    if (!key || !key.startsWith(prefix) || key === activeKey) continue;
    const overlay = parse(localStorage.getItem(key));
    if (!overlay || !hasContent(overlay) || overlay.based_on === currentBase) continue;
    if (!best || overlay.saved_at > best.overlay.saved_at) best = { overlay, key };
  }
  return best;
}

/** Reconstruct a base version's rules with an overlay folded in — identity-keyed, server base immutable. */
function foldRules(base: CalculationMethodVersion, overlay: DraftOverlay): CalculationMethodRule[] {
  return [
    ...base.rules
      .filter(rule => !overlay.removed.includes(ruleIdentity(rule)))
      .map(rule => ({ ...rule, ...(overlay.edits[ruleIdentity(rule)] ?? {}) })),
    ...overlay.added,
  ];
}

/** A previous draft the user never saved, held against its own base version for compare / migrate / discard. */
export interface StaleMethodDraft {
  baseVersion: number;
  baseContentSha256: string;
  rules: CalculationMethodRule[];
  meta: MethodDraftMeta;
  dimensions: MethodDimension[];
  processingRef: ModelProcessingRulesRef | null;
  editedCount: number;
  addedCount: number;
  removedCount: number;
}

export function useMethodDraft(
  applicationId: string,
  revisionId: string,
  methodId: string,
  versions: CalculationMethodVersion[],
  latestVersion: CalculationMethodVersion,
  name: string,
  description: string | null,
) {
  const basedOn = latestVersion.content_sha256 ?? '';
  const key = draftKey(applicationId, revisionId, methodId, basedOn);
  const prefix = draftPrefix(applicationId, revisionId, methodId);

  const [overlay, setOverlay] = useState<DraftOverlay>(() => load(key, basedOn));
  const [staleRecord, setStaleRecord] = useState<{ overlay: DraftOverlay; key: string } | null>(
    () => findStale(prefix, key, basedOn),
  );

  // When the head moves, reload this base's own slot and re-scan for a quarantined previous draft.
  useEffect(() => {
    setOverlay(load(key, basedOn));
    setStaleRecord(findStale(prefix, key, basedOn));
  }, [key, basedOn, prefix]);

  // Persist only the active base's slot. An empty active slot removes just that slot; a previous base's
  // draft lives under a different key and is never touched here.
  useEffect(() => {
    if (overlay.based_on !== basedOn) return;
    if (hasContent(overlay)) localStorage.setItem(key, JSON.stringify({ ...overlay, based_on: basedOn, saved_at: Date.now() }));
    else localStorage.removeItem(key);
  }, [key, basedOn, overlay]);

  const serverMeta = useMemo<MethodDraftMeta>(
    () => ({ name, description, cbam_boundary_ref: latestVersion.cbam_boundary_ref }),
    [name, description, latestVersion.cbam_boundary_ref],
  );
  const meta = useMemo(() => ({ ...serverMeta, ...(overlay.meta ?? {}) }), [serverMeta, overlay.meta]);

  // A method's declared reporting dimensions are method-level like meta: the draft overlays them, and
  // an untouched head inherits exactly what the server version carries.
  const baseDimensions = useMemo<MethodDimension[]>(
    () => latestVersion.reporting_dimensions ?? [],
    [latestVersion.reporting_dimensions],
  );
  const dimensions = useMemo<MethodDimension[]>(
    () => overlay.dimensions ?? baseDimensions,
    [overlay.dimensions, baseDimensions],
  );

  // The bound processing package is a single version-level value like dimensions: an untouched head
  // inherits exactly what the server carries, and selecting "automatic" (null) on a version that
  // already carries null is not a change, so the official default never becomes spuriously dirty.
  const baseProcessingRef = useMemo<ModelProcessingRulesRef | null>(
    () => latestVersion.model_processing_rules_ref ?? null,
    [latestVersion.model_processing_rules_ref],
  );
  const processingRef = useMemo<ModelProcessingRulesRef | null>(
    () => overlay.processing_ref === undefined ? baseProcessingRef : overlay.processing_ref,
    [overlay.processing_ref, baseProcessingRef],
  );

  const rules = useMemo(() => foldRules(latestVersion, overlay), [latestVersion, overlay]);
  const addedIdentities = useMemo(() => new Set(overlay.added.map(ruleIdentity)), [overlay.added]);
  const dirty = useMemo(() => hasContent(overlay), [overlay]);

  // The quarantined draft is surfaced for compare only against its own base version — never folded into
  // the live `rules`/`meta`, which always reflect the current head.
  const stale = useMemo<StaleMethodDraft | null>(() => {
    if (!staleRecord) return null;
    const base = versions.find(item => (item.content_sha256 ?? '') === staleRecord.overlay.based_on);
    if (!base) return null;
    return {
      baseVersion: base.version,
      baseContentSha256: base.content_sha256 ?? '',
      rules: foldRules(base, staleRecord.overlay),
      meta: { name, description, cbam_boundary_ref: base.cbam_boundary_ref, ...staleRecord.overlay.meta },
      dimensions: staleRecord.overlay.dimensions ?? base.reporting_dimensions ?? [],
      processingRef: staleRecord.overlay.processing_ref === undefined
        ? base.model_processing_rules_ref ?? null
        : staleRecord.overlay.processing_ref,
      editedCount: Object.keys(staleRecord.overlay.edits).length,
      addedCount: staleRecord.overlay.added.length,
      removedCount: staleRecord.overlay.removed.length,
    };
  }, [staleRecord, versions, name, description]);

  const updateRule = useCallback((identity: string, patch: Partial<CalculationMethodRule>) => {
    setOverlay(previous => {
      const edits = { ...previous.edits };
      const added = [...previous.added];
      const addedIndex = added.findIndex(rule => ruleIdentity(rule) === identity);
      if (addedIndex >= 0) {
        // An added rule has no server base to revert against; fold the patch straight into the object.
        added[addedIndex] = { ...added[addedIndex], ...patch };
        return { ...previous, added };
      }
      const base = latestVersion.rules.find(rule => ruleIdentity(rule) === identity);
      if (!base) return previous;
      const merged = { ...(previous.edits[identity] ?? {}), ...patch };
      const reverted = Object.entries(merged).every(([field, value]) => {
        const baseValue = base[field as keyof CalculationMethodRule];
        if (baseValue === value) return true;
        // Category maps are objects: an edit that structurally matches the base is not a change.
        if (value && baseValue && typeof value === 'object' && typeof baseValue === 'object') {
          return JSON.stringify(value) === JSON.stringify(baseValue);
        }
        return false;
      });
      if (reverted) delete edits[identity];
      else edits[identity] = merged;
      return { ...previous, edits };
    });
  }, [latestVersion]);

  const addRule = useCallback((rule: CalculationMethodRule) => {
    setOverlay(previous => {
      const identity = ruleIdentity(rule);
      if (previous.added.some(item => ruleIdentity(item) === identity)) return previous;
      // A rule the server already has is re-enabled by clearing its removal + edits, not duplicated.
      const serverBase = latestVersion.rules.find(item => ruleIdentity(item) === identity);
      if (serverBase) {
        const removed = previous.removed.filter(item => item !== identity);
        const edits = { ...previous.edits };
        const patch = Object.fromEntries(Object.entries(rule).filter(([field, value]) =>
          JSON.stringify(value) !== JSON.stringify(serverBase[field as keyof CalculationMethodRule]))) as Partial<CalculationMethodRule>;
        if (Object.keys(patch).length) edits[identity] = patch;
        else delete edits[identity];
        return { ...previous, removed, edits };
      }
      return { ...previous, added: [...previous.added, rule] };
    });
  }, [latestVersion]);

  const removeRule = useCallback((identity: string) => {
    setOverlay(previous => {
      if (previous.added.some(item => ruleIdentity(item) === identity)) {
        return { ...previous, added: previous.added.filter(item => ruleIdentity(item) !== identity) };
      }
      if (!latestVersion.rules.some(item => ruleIdentity(item) === identity)) return previous;
      const edits = { ...previous.edits };
      delete edits[identity];
      return { ...previous, removed: [...previous.removed, identity], edits };
    });
  }, [latestVersion]);

  const setMeta = useCallback((patch: Partial<MethodDraftMeta>) => {
    setOverlay(previous => {
      const current = { ...(previous.meta ?? {}) } as Partial<MethodDraftMeta>;
      for (const [field, value] of Object.entries(patch) as [keyof MethodDraftMeta, unknown][]) {
        if (serverMeta[field] === value) delete current[field];
        else current[field] = value as never;
      }
      return { ...previous, meta: Object.keys(current).length ? current : null };
    });
  }, [serverMeta]);

  // Whole-dimension replacement: the editor hands back the full declared list, and reverting it to
  // exactly the server base clears the overlay so the draft is no longer marked dirty.
  const setDimensions = useCallback((next: MethodDimension[]) => {
    setOverlay(previous => ({
      ...previous,
      dimensions: JSON.stringify(next) === JSON.stringify(baseDimensions) ? null : next,
    }));
  }, [baseDimensions]);

  // Whole-binding replacement: choosing the package (or "automatic") the server base already carries
  // clears the overlay, so an untouched head never reads as a change and reverting a pick is clean.
  const setProcessingRef = useCallback((next: ModelProcessingRulesRef | null) => {
    setOverlay(previous => ({
      ...previous,
      processing_ref: JSON.stringify(next) === JSON.stringify(baseProcessingRef) ? undefined : next,
    }));
  }, [baseProcessingRef]);

  const reloadFromServer = useCallback(() => {
    localStorage.removeItem(key);
    setOverlay(emptyOverlay(basedOn));
  }, [key, basedOn]);

  // Explicit, user-initiated only: fold the previous draft's edits onto the current base. This is the sole
  // path by which old input ever reaches a new head.
  const migrateStale = useCallback(() => {
    if (!staleRecord) return;
    const carried = staleRecord.overlay;
    localStorage.removeItem(staleRecord.key);
    setOverlay({ based_on: basedOn, saved_at: Date.now(), edits: carried.edits, added: carried.added, removed: carried.removed, meta: carried.meta, dimensions: carried.dimensions, processing_ref: carried.processing_ref });
    setStaleRecord(null);
  }, [staleRecord, basedOn]);

  const discardStale = useCallback(() => {
    if (!staleRecord) return;
    localStorage.removeItem(staleRecord.key);
    setStaleRecord(null);
  }, [staleRecord]);

  return {
    rules,
    meta,
    dimensions,
    processingRef,
    dirty,
    addedIdentities,
    updateRule,
    addRule,
    removeRule,
    setMeta,
    setDimensions,
    setProcessingRef,
    reloadFromServer,
    baseVersion: latestVersion.version,
    baseContentSha256: basedOn,
    stale,
    migrateStale,
    discardStale,
  };
}
