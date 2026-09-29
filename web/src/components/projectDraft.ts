export const projectDraftKey = (applicationId: string, revisionId: string) =>
  `nebula-one:project:${applicationId}:${revisionId}`;

export function clearProjectDraft(applicationId: string, revisionId: string): void {
  if (revisionId) localStorage.removeItem(projectDraftKey(applicationId, revisionId));
}

interface DraftShape {
  amounts: number[];
  values: Record<string, number>;
  source: string;
}

/**
 * Unsaved-changes guard for version switching: a draft is dirty only when it differs from the
 * server-saved baseline the form opened with. Emptying a number yields NaN, which never equals a
 * saved value, so cleared required fields correctly count as changes.
 */
export function draftDiffers(draft: DraftShape, saved: DraftShape): boolean {
  if (draft.source !== saved.source) return true;
  if (draft.amounts.length !== saved.amounts.length) return true;
  if (draft.amounts.some((value, index) => value !== saved.amounts[index])) return true;
  const keys = new Set([...Object.keys(saved.values), ...Object.keys(draft.values)]);
  for (const key of keys) if (draft.values[key] !== saved.values[key]) return true;
  return false;
}

/**
 * A background binding saves the server's values as a new data version and never the unsaved
 * inventory edits held on this machine, so the draft moves to that version instead of being
 * orphaned under the version it was typed against.
 */
export function carryProjectDraft(applicationId: string, from: string, to: string): void {
  if (!from || from === to) return;
  const typedInto = projectDraftKey(applicationId, from);
  const draft = localStorage.getItem(typedInto);
  if (!draft) return;
  localStorage.setItem(projectDraftKey(applicationId, to), draft);
  localStorage.removeItem(typedInto);
}
