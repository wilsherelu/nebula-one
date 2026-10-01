import { afterEach, expect, it, vi } from 'vitest';
import { handoffStorageKey, modelingApi, openModelingHandoff } from './modeling';

afterEach(() => { vi.restoreAllMocks(); delete window.__NEBULA_ONE_DESKTOP__; sessionStorage.clear(); });

it('transfers only the exact handoff to a separate desktop editor while retaining the current page', async () => {
  const result = {handoff_id:'abcf2b9a-58fa-46e8-b6d8-21bec0529a7a', state:'exact-state', confirmation_token:'private-confirmation',
    editor_url:'http://127.0.0.1:32123/projects/id?handoff_id=abcf2b9a-58fa-46e8-b6d8-21bec0529a7a&state=exact-state'};
  vi.spyOn(modelingApi, 'start').mockResolvedValue(result);
  const openEditor = vi.fn().mockResolvedValue(true);
  window.__NEBULA_ONE_DESKTOP__ = {openEditor};
  const before = window.location.href;
  await openModelingHandoff('Steel', 'model-id', 'exact-revision', 'en');
  expect(modelingApi.start).toHaveBeenCalledWith('Steel', 'model-id', 'exact-revision');
  expect(openEditor).toHaveBeenCalledWith({handoff_id:result.handoff_id, state:result.state,
    confirmation_token:result.confirmation_token, url:result.editor_url+'&lang=en'});
  expect(JSON.parse(sessionStorage.getItem(handoffStorageKey(result.handoff_id))!)).toEqual({state:result.state, confirmation_token:result.confirmation_token});
  expect(window.location.href).toBe(before);
});
