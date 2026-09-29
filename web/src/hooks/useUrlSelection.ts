import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';

export interface InvalidReference {
  key: string;
  label: string;
  requested: string;
}

export interface UrlSelection {
  /** Raw value from the URL; empty when the analyst did not reference it explicitly. */
  requested: string;
  /** Usable value, or empty while pending or when an explicit reference was rejected. */
  value: string;
  pending: boolean;
  invalid: boolean;
  select: (value: string) => void;
  clear: () => void;
}

export interface UrlSelectionMap {
  requested: Record<string, string>;
  values: Record<string, string>;
  /** Keys whose explicit URL reference was rejected after the catalog loaded: unknown key or value outside its candidates. */
  invalid: string[];
  set: (key: string, value: string) => void;
  clear: () => void;
}

const PAIR_SEPARATOR = ';';
const KEY_SEPARATOR = ':';

export function resolveUrlSelection(
  requested: string | null,
  ids: string[],
  ready: boolean,
  fallbackId?: string,
): { value: string; pending: boolean; invalid: boolean } {
  if (!ready) return { value: '', pending: true, invalid: false };
  if (requested === null) return { value: fallbackId && ids.includes(fallbackId) ? fallbackId : ids[0] ?? '', pending: false, invalid: false };
  return ids.includes(requested)
    ? { value: requested, pending: false, invalid: false }
    : { value: '', pending: false, invalid: true };
}

export function parseUrlSelectionPairs(raw: string | null): Record<string, string> {
  if (!raw) return {};
  return raw.split(PAIR_SEPARATOR).reduce<Record<string, string>>((entries, pair) => {
    const [key, value, ...rest] = pair.split(KEY_SEPARATOR);
    if (key && value && !rest.length) entries[key] = value;
    return entries;
  }, Object.create(null) as Record<string, string>);
}

export function serializeUrlSelectionPairs(entries: Record<string, string>): string {
  return Object.entries(entries)
    .filter(([key, value]) => Boolean(key) && Boolean(value))
    .map(([key, value]) => `${key}${KEY_SEPARATOR}${value}`)
    .join(PAIR_SEPARATOR);
}

export function useParamWriter() {
  const [, setSearchParams] = useSearchParams();
  return useCallback((mutate: (next: URLSearchParams) => void, replace: boolean) => {
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      mutate(next);
      return next;
    }, { replace });
  }, [setSearchParams]);
}

/**
 * URL-backed single selection: an absent parameter keeps the existing initial choice, an
 * explicit reference is only accepted after its catalog has loaded and never falls back.
 */
export function useUrlSelection(key: string, ids: string[], options?: {
  ready?: boolean;
  fallbackId?: string;
  clearKeys?: string[];
}): UrlSelection {
  const ready = options?.ready ?? true;
  const fallbackId = options?.fallbackId;
  const clearKeys = JSON.stringify(options?.clearKeys ?? []);
  const [searchParams] = useSearchParams();
  const write = useParamWriter();
  const requested = searchParams.get(key);
  const catalogKey = ids.join('\n');
  const resolution = useMemo(
    () => resolveUrlSelection(requested, catalogKey ? catalogKey.split('\n') : [], ready, fallbackId),
    [catalogKey, fallbackId, ready, requested],
  );
  return {
    requested: requested ?? '',
    ...resolution,
    select: useCallback((value: string) => write((next) => {
      next.set(key, value);
      (JSON.parse(clearKeys) as string[]).forEach((clearKey) => next.delete(clearKey));
    }, false), [clearKeys, key, write]),
    clear: useCallback(() => write((next) => next.delete(key), true), [key, write]),
  };
}

/** URL-backed `{ key: selectedId }` map, validated per key against that key's candidate ids. */
export function useUrlSelectionMap(key: string, candidates: Record<string, string[]>, options?: {
  ready?: boolean;
}): UrlSelectionMap {
  const ready = options?.ready ?? true;
  const [searchParams] = useSearchParams();
  const write = useParamWriter();
  const raw = searchParams.get(key);
  const requested = useMemo(() => parseUrlSelectionPairs(raw), [raw]);
  const candidateKey = JSON.stringify(candidates);
  const resolution = useMemo(() => {
    if (!ready) return { values: {} as Record<string, string>, invalid: [] as string[] };
    const resolvedCandidates = JSON.parse(candidateKey) as Record<string, string[]>;
    const entries: Record<string, string> = {};
    const invalid: string[] = [];
    const seen = new Set<string>();
    if (raw !== null) {
      for (const pair of raw.split(PAIR_SEPARATOR)) {
        const [entryKey, value, ...rest] = pair.split(KEY_SEPARATOR);
        if (!entryKey || !value || rest.length || seen.has(entryKey)) invalid.push(entryKey || pair || key);
        seen.add(entryKey);
      }
    }
    for (const [entryKey, value] of Object.entries(requested)) {
      const allowed = Object.prototype.hasOwnProperty.call(resolvedCandidates, entryKey) ? resolvedCandidates[entryKey] : undefined;
      if (allowed && allowed.includes(value)) entries[entryKey] = value;
      else invalid.push(entryKey);
    }
    return { values: entries, invalid: [...new Set(invalid)] };
  }, [candidateKey, key, raw, ready, requested]);
  return {
    requested,
    values: resolution.values,
    invalid: resolution.invalid,
    set: useCallback((entryKey: string, value: string) => write((next) => {
      const entries = parseUrlSelectionPairs(next.get(key));
      if (value) entries[entryKey] = value;
      else delete entries[entryKey];
      const serialized = serializeUrlSelectionPairs(entries);
      if (serialized) next.set(key, serialized);
      else next.delete(key);
    }, false), [key, write]),
    clear: useCallback(() => write((next) => next.delete(key), true), [key, write]),
  };
}
