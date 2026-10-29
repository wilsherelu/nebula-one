import { requestJson } from './client';
import type { BackgroundProcessPin, MappedBackgroundProcessPin, ProjectBackgroundPin, ModelProcessingRulesRef, CalculationMethodRef } from './types';

export interface MappedCandidates {
  consumer_exchange_id: string; requires_confirmation: boolean;
  mapping: {package_hash: string; package_id: string; package_version: string; mapping_level: string;
    source_unit: string; target_unit: string; amount_factor: number; mapping_reason: string};
  providers: Array<{process_uuid: string; process_name: string; location: string; database_release: string | null; executable: boolean}>;
}

export interface SeedProjectTemplate {
  id: string; title: string; version: string; template_sha256: string; seed_id: string;
  kind?: 'authored';
  user_method_count?: number;
  installed_application_id: string; source_application_id: string; source_model_id: string; source_revision_id: string | null;
  process_count: number; field_count: number; capabilities: string[];
  /** Short names the release declares for this template; absent means the real name is the only one. */
  display_name?: Record<string, string>;
}

/** The name a reader should see: the declared projection, or the template's real name. */
export function templateName(item: Pick<SeedProjectTemplate, 'title' | 'display_name'>, lang: string): string {
  const declared = (item.display_name ?? {})[lang]?.trim();
  return declared || item.title;
}
export const seedProjectsApi = {
  userSupplyProjects: (applicationId: string, revisionId: string) =>
    requestJson<{items: Array<{project_id: string; name: string; latest_version: number | null}>}>(`/api/v1/applications/${applicationId}/workspace/${revisionId}/background/user-projects`),
  userSupplyVersions: (applicationId: string, revisionId: string, projectId: string) =>
    requestJson<{items: Array<{version: number; created_at: string; graph_hash: string}>}>(`/api/v1/applications/${applicationId}/workspace/${revisionId}/background/user-projects/${encodeURIComponent(projectId)}/versions`),
  mappedCandidates: (applicationId: string, revisionId: string, consumerId: string) =>
    requestJson<MappedCandidates>(`/api/v1/applications/${applicationId}/workspace/${revisionId}/background/mapped-candidates?${new URLSearchParams({consumer_exchange_id: consumerId})}`),
  resolveMapped: (applicationId: string, revisionId: string, payload: {consumer_exchange_id: string; process_uuid: string; expected_mapping_package_hash: string; confirmed: boolean}) =>
    requestJson<{pin: MappedBackgroundProcessPin; name: string}>(`/api/v1/applications/${applicationId}/workspace/${revisionId}/background/mapped-resolve`, {method: 'POST', body: JSON.stringify(payload)}),
  resolveBackground: (applicationId: string, revisionId: string, payload: {consumer_exchange_id: string; process_uuid: string; version: string}) =>
    requestJson<{pin: BackgroundProcessPin; name: string}>(`/api/v1/applications/${applicationId}/workspace/${revisionId}/background/resolve`, {method: 'POST', body: JSON.stringify(payload)}),
  resolveUserProject: (applicationId: string, revisionId: string, payload: {consumer_exchange_id: string; project_id: string; version: number}) =>
    requestJson<{pin: ProjectBackgroundPin; name: string; consumer_unit: string; reference_unit: string; model_processing_rules_ref?: ModelProcessingRulesRef}>(`/api/v1/applications/${applicationId}/workspace/${revisionId}/background/user-project-resolve`, {method: 'POST', body: JSON.stringify(payload)}),
  catalog: () => requestJson<{items: SeedProjectTemplate[]}>('/api/v1/project-templates'),
  publish: (payload: {title: string; version: string; source_application_id: string; source_model_id: string;
    source_revision_id: string; expected_revision_sha256: string;
    methods: Array<{package_id: string; version: string; content_sha256: string}>; user_methods?: CalculationMethodRef[]}) =>
    requestJson<SeedProjectTemplate>('/api/v1/project-templates/authored', {method: 'POST', body: JSON.stringify(payload)}),
  create: (id: string, payload: {name: string; project_key: string; expected_template_sha256: string}) =>
    requestJson<{application_id: string; system_model_id: string; revision_id: string}>(`/api/v1/project-templates/${id}/projects`, {method: 'POST', body: JSON.stringify(payload)}),
};
