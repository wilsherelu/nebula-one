import { requestJson } from './client';
import type { CalculationMethodDetail } from './types';

/** What the bound package or frozen snapshot literally declares; never inferred from a flow name. */
export interface TemplateMethodRuleSource {
  kind: 'official_package_classification' | 'user_method_rules' | 'none';
  declared: Array<{ exchange_id: string; rule_paths: string[] }>;
  declared_count: number;
  port_count: number;
  undeclared_port_count: number;
  declared_but_absent_from_model: string[];
  provenance: Array<{ source_path: string; url?: string; text?: string }>;
}

export interface TemplateMethodGap {
  code: string;
  message: string;
  source_path: string;
  exchange_id?: string | null;
  clause?: string | null;
}

export interface TemplateFrozenUserMethod {
  method_id: string;
  version: number;
  content_sha256: string;
  status: string;
  name: string | null;
  description: string | null;
  origin_method_id: string | null;
  origin_method_version: number | null;
  model_processing_rules_ref: unknown;
  cbam_boundary_ref: string | null;
  rule_count: number;
  reporting_dimension_count: number;
}

export interface TemplateAccountingMethod {
  method_key: string;
  purpose: string;
  method_group: 'organization' | 'cbam' | 'product' | 'user' | 'other';
  origin: 'official_package' | 'template_user_method' | 'project_user_method' | 'source_user_method';
  display_name: Record<string, string> | null;
  editable: boolean;
  actions: string[];
  base_method_ref: { package_id: string; version: string; content_sha256: string } | null;
  rule_source: TemplateMethodRuleSource;
  coverage_gaps: TemplateMethodGap[];
  user_method: TemplateFrozenUserMethod | null;
  check: { status: string; status_basis: string; problem_count: number; problems: unknown[] };
  package_detail?: {
    jurisdiction: string | null;
    assurance_level: string | null;
    boundary_schema: Record<string, unknown>;
    output_schema: Record<string, unknown>;
    accepted_units: Record<string, unknown>;
    formula_graph: Record<string, unknown>;
  };
  cbam_boundaries?: Array<{
    id: string; name: string; boundary_type: string; status: string; period_id: string | null;
    method_package_ref: string | null; graph_sha256: string | null;
    included_process_count: number; included_flow_rule_count: number; excluded_item_count: number;
  }>;
}

/** One reader-facing task the versioned scheme set declares, grouping the flat methods by role.
 * The backend owns role/default/membership; the frontend never guesses from a name, id or position. */
export interface TemplateAccountingTask {
  role: 'complete_model' | 'cbam' | 'scope_classification';
  default_ref: string | null;
  /** method_keys of the official presets this task binds, the declared default first. */
  preset_keys: string[];
  /** method_keys of the reader's own copies that belong to this task's scheme selector. */
  user_scheme_keys: string[];
}

export interface TemplateAccountingMethods {
  schema_version: string;
  template: {
    id: string;
    kind: 'seed' | 'authored';
    title: string;
    version: string;
    template_sha256: string;
    display_name: Record<string, string> | null;
    official: boolean;
    editable: boolean;
    source_application_id: string;
    source_model_id: string;
    source_revision_id: string | null;
    capabilities: string[];
    template_profile: { id: string; version: string; content_sha256: string } | null;
    method_package_refs: string[];
    method_pins?: Record<string, string>;
    boundary_pins?: Record<string, string>;
    unresolved_method_package_refs: string[];
    model: { process_count: number; port_count: number; graph_sha256: string; graph_basis: string;
      graph_snapshot?: Record<string, unknown> };
  };
  methods: TemplateAccountingMethod[];
  /** Present only when this template version binds a task-declaring scheme set; null keeps the flat view. */
  tasks: TemplateAccountingTask[] | null;
  /** method_keys no task claims, shown under “其他自定义方案” so nothing is hidden. */
  other_scheme_keys: string[];
}

export interface TemplateMethodCopyResult {
  schema_version: string;
  /** The ordinary method detail contract, so the editor opens the copy without a second read. */
  method: CalculationMethodDetail;
  transcription: {
    template_id: string;
    method_key: string;
    package_kind: string;
    purpose: string;
    base_method_ref: { package_id: string; version: string; content_sha256: string };
    application_id: string;
    model_revision_id: string;
    cbam_boundary_ref: string | null;
    rule_count: number;
    port_count: number;
    undeclared_port_count: number;
    declared_but_absent_from_model: string[];
    declared_exchange_ids: string[];
    reporting_dimensions: unknown[];
    reference_product_exchange_id: string | null;
    /** What the copy itself could not take over: the package's own pending rules and conflicts. */
    notes: TemplateMethodGap[];
  };
}

export interface TemplateSaveCandidate {
  method_id: string;
  name: string | null;
  purpose: string;
  method_group: TemplateAccountingMethod['method_group'];
  version: number;
  content_sha256: string | null;
  status: string;
  rule_count: number;
  reporting_dimension_count: number;
  cbam_boundary_ref: string | null;
  already_frozen_in_template: boolean;
  savable: boolean;
  /** Why this working method cannot be frozen into a template, in the server's own words. */
  blocking_reason: string | null;
}

export interface TemplateSavePlan {
  schema_version: string;
  template_id: string;
  kind: 'seed' | 'authored';
  official: boolean;
  title: string;
  version: string;
  template_sha256: string;
  suggested_title: string;
  suggested_version: string;
  source_application_id: string;
  source_model_id: string;
  source_revision_id: string;
  expected_revision_sha256: string;
  method_pins: Array<{ package_id: string; version: string; content_sha256: string }>;
  unresolved_method_package_refs: string[];
  user_methods: TemplateSaveCandidate[];
}

export interface TemplateSaveResult {
  schema_version: string;
  template: {
    id: string; title: string; version: string; template_sha256: string; kind: string;
    user_method_count: number; process_count: number; field_count: number;
  };
  source_template: {
    template_id: string; title: string; version: string; template_sha256: string;
    source_application_id: string; source_model_id: string; source_revision_id: string;
  };
  frozen_user_methods: Array<{ method_id: string; version: number; content_sha256: string }>;
}

export const templateMethodsApi = {
  forTemplate: (templateId: string, lang: string) =>
    requestJson<TemplateAccountingMethods>(
      `/api/v1/project-templates/${encodeURIComponent(templateId)}/accounting-methods?lang=${encodeURIComponent(lang)}`),
  copyOfficial: (templateId: string, payload: {
    method_key: string; name: string; description?: string | null; cbam_boundary_ref?: string | null;
  }) => requestJson<TemplateMethodCopyResult>(
    `/api/v1/project-templates/${encodeURIComponent(templateId)}/accounting-methods/copy`,
    { method: 'POST', body: JSON.stringify(payload) }),
  savePlan: (templateId: string) => requestJson<TemplateSavePlan>(
    `/api/v1/project-templates/${encodeURIComponent(templateId)}/save-plan`),
  saveTemplate: (templateId: string, payload: {
    title: string; version: string;
    user_methods: Array<{ method_id: string; version: number; content_sha256: string }>;
  }) => requestJson<TemplateSaveResult>(
    `/api/v1/project-templates/${encodeURIComponent(templateId)}/save-template`,
    { method: 'POST', body: JSON.stringify(payload) }),
};
