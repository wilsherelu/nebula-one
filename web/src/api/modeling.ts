import { requestJson } from './client';
import { languageParam, type Lang } from '../i18n';

export interface ModelingCandidate {
  state: string; confirmation_token: string; project_id: string;
  base_version?: number; saved_version: number; upstream_graph_hash: string;
}
export interface ModelingResult { application_id: string; system_model_id: string; revision_id: string }
declare global {
  interface Window {
    __NEBULA_ONE_DESKTOP__?: {
      openEditor(payload: {url: string; handoff_id: string; state: string; confirmation_token: string}): Promise<boolean>;
      openEditorHome?: (lang: Lang) => Promise<boolean>;
    };
  }
}
export interface ModelingPreview {
  name: string; project_id: string; version: number; upstream_graph_hash: string;
  hydrated_graph_sha256: string; node_count: number; status: string; result: Partial<ModelingResult>;
  issues: unknown[];
}
const post = <T,>(path: string, payload: unknown) => requestJson<T>(path, { method: 'POST', body: JSON.stringify(payload) });
export const modelingApi = {
  configuration: () => requestJson<{available: boolean; message: string; editor_url: string | null}>('/api/v1/modeling/configuration'),
  start: (name: string, base_model_id?: string, base_revision_id?: string) => post<{handoff_id: string; state: string; confirmation_token: string; editor_url: string}>('/api/v1/modeling/handoffs', { name, base_model_id, base_revision_id }),
  preview: (id: string, payload: ModelingCandidate) => post<ModelingPreview>(`/api/v1/modeling/handoffs/${id}/preview`, payload),
  confirm: (id: string, payload: ModelingCandidate) => post<ModelingResult>(`/api/v1/modeling/handoffs/${id}/confirm`, payload),
  cancel: (id: string, payload: Pick<ModelingCandidate, 'state' | 'confirmation_token'>) => post(`/api/v1/modeling/handoffs/${id}/cancel`, payload),
};
export const handoffStorageKey = (id: string) => `nebula-one:modeling:${id}`;

/** The editor runs on its own origin, so the reader's language has to travel in the URL. */
export function withLanguage(url: string, lang: Lang): string {
  const target = new URL(url);
  target.searchParams.set('lang', lang);
  return target.toString();
}

export async function openModelingHandoff(name: string, baseModelId: string, baseRevisionId: string | undefined, lang: Lang) {
  const result = await modelingApi.start(name, baseModelId, baseRevisionId);
  sessionStorage.setItem(handoffStorageKey(result.handoff_id), JSON.stringify({state: result.state, confirmation_token: result.confirmation_token}));
  const url = withLanguage(result.editor_url, lang);
  if (window.__NEBULA_ONE_DESKTOP__) {
    await window.__NEBULA_ONE_DESKTOP__.openEditor({
    url, handoff_id: result.handoff_id, state: result.state, confirmation_token: result.confirmation_token,
    });
    return;
  }
  window.location.assign(url);
}
