import { afterEach, expect, it } from 'vitest';
import { carryProjectDraft, clearProjectDraft, draftDiffers, projectDraftKey } from './projectDraft';

afterEach(() => localStorage.clear());

it('moves an unsaved inventory draft onto the version a background binding just created', () => {
  const draft = JSON.stringify({ amounts: [1000], values: { power: 600 }, source: '生产台账' });
  localStorage.setItem(projectDraftKey('app-steel', 'r2'), draft);
  carryProjectDraft('app-steel', 'r2', 'r3');
  expect(localStorage.getItem(projectDraftKey('app-steel', 'r3'))).toBe(draft);
  expect(localStorage.getItem(projectDraftKey('app-steel', 'r2'))).toBeNull();
});

it('writes nothing when there is no draft or the binding returned the same version', () => {
  carryProjectDraft('app-steel', 'r2', 'r3');
  expect(localStorage.getItem(projectDraftKey('app-steel', 'r3'))).toBeNull();
  localStorage.setItem(projectDraftKey('app-steel', 'r2'), '{}');
  carryProjectDraft('app-steel', 'r2', 'r2');
  expect(localStorage.getItem(projectDraftKey('app-steel', 'r2'))).toBe('{}');
});

it('flags a draft dirty only when it differs from the saved baseline', () => {
  const saved = { amounts: [1000], values: { power: 50, crude: 1 }, source: '生产台账' };
  expect(draftDiffers(saved, saved)).toBe(false);
  expect(draftDiffers({ ...saved, values: { ...saved.values, power: 60 } }, saved)).toBe(true);
  expect(draftDiffers({ ...saved, source: '改过来源' }, saved)).toBe(true);
  // An emptied required field reads as NaN and must count as an unsaved change.
  expect(draftDiffers({ ...saved, values: { ...saved.values, power: NaN } }, saved)).toBe(true);
});

it('discards only the named version draft, leaving the rest of the scope untouched', () => {
  localStorage.setItem(projectDraftKey('app-steel', 'r2'), '{"values":{}}');
  localStorage.setItem(projectDraftKey('app-steel', 'r3'), '{"values":{}}');
  clearProjectDraft('app-steel', 'r2');
  expect(localStorage.getItem(projectDraftKey('app-steel', 'r2'))).toBeNull();
  expect(localStorage.getItem(projectDraftKey('app-steel', 'r3'))).toBe('{"values":{}}');
});
