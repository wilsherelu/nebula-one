import type { Lang } from '../i18n/messages';
import type {
  FrozenReport,
  ApiProblem,
  Application,
  ProjectWorkspace,
  BackgroundProcessPin,
  MappedBackgroundProcessPin,
  ProjectBackgroundPin,
  ModelProcessingRulesRef,
  Comparison,
  ComparisonExecuteRequest,
  ComparisonRun,
  CapabilityCatalogResponse,
  Scenario,
  CasePackCatalogResponse,
  SystemModel,
  SystemRevision,
  SolveAndFreezeRequest,
  SolvedSystemSnapshot,
  ClimateMethodResolution,
  EnergyCarrierResult,
  CarbonManagementResult,
  OrganizationGhgInventoryRequest,
  OrganizationGhgInventoryResult,
  OrganizationGhgInventoryV1Request,
  OrganizationGhgInventoryV1Result,
  SystemBinding,
  SolvedMfaResult,
  MethodPackage,
  ProductCarbonFootprint,
  PcfBasisRequest,
  OrganizationPeriodRequest,
  OrganizationPeriodResult,
  OrganizationLifecycleRequest,
  OrganizationLifecycleResult,
  OrganizationLifecycleDisplay,
  SetupStatus,
  CasePackMaterializeRequest,
  CasePackMaterializeResult,
  BoundaryDefinition,
  CalculationMethod,
  CalculationMethodDetail,
  CalculationMethodVersion,
  CalculationMethodSavePayload,
  CalculationMethodClonePayload,
  CalculationMethodCreatePayload,
  CalculationMethodValidation,
  CalculationMethodCapabilities,
  ClassificationSuggestions,
  ProcessingPackageOption,
  TagGroupingRequest,
  TagGroupingResult,
  ResultCategoryConversionPreview,
  ResultCategoryConversionPayload,
  ResultCategoryConversionOptions,
  SpatialAggregateResult,
  SpatialEnergyResult,
  SpatialDistributionResult,
  PeriodEnergyComparisonResult,
  PeriodEnergyTrendRequest,
  PeriodEnergyTrendResult,
  PeriodEnergyTotalRequest,
  PeriodEnergyTotalResult,
  ReportingPeriod,
  InventorySnapshot,
  InventoryDataPoint,
  CbamTrialRequest,
  CbamPartialReviewRequest,
  CbamPartialReviewResult,
  CbamComplexTrialRequest,
  CbamTrialResult,
  CbamComplexTrialResult,
  ModelSource,
  ModelSourceAttachResult,
  ModelSourcePreview,
  EngineStatus,
} from './types';

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
    readonly details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

/**
 * A 4xx problem body is a deterministic refusal, so retrying cannot turn it into a result;
 * while a retry waits, react-query reports the query as `pending` + `paused`, which leaves
 * a calculation panel blank instead of showing why the request was refused.
 */
export function retryAfterTransientFailure(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError) return failureCount < 1 && ([408, 429].includes(error.status) || error.status >= 500);
  return failureCount < 1;
}

/**
 * The saved data version moved under this editor, so resending the same payload is refused again;
 * re-reading the version is the only step that can make the next attempt succeed.
 */
export function isStaleDataVersion(error: unknown): boolean {
  return error instanceof ApiError && error.code === 'PROJECT_INPUT_CONFLICT';
}

/** The method's head version moved under this editor; only re-reading can unblock the next save. */
export function isCalculationMethodConflict(error: unknown): boolean {
  return error instanceof ApiError && error.code === 'CALCULATION_METHOD_CONFLICT';
}

/** GET export/report carry the result basis as query params so the file matches the on-screen口径. */
function pcfExportQuery(methodPackageRef: string, basis?: PcfBasisRequest): string {
  const params = new URLSearchParams({ method_package_ref: methodPackageRef });
  if (basis && basis.result_basis !== 'total') {
    params.set('result_basis', basis.result_basis);
    if (basis.base_amount !== undefined) params.set('base_amount', String(basis.base_amount));
    if (basis.base_unit) params.set('base_unit', basis.base_unit);
  }
  return params.toString();
}

export async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!response.ok) {
    let problem: ApiProblem = {};
    try {
      problem = (await response.json()) as ApiProblem;
    } catch {
      // Response bodies are optional on transport failures.
    }
    const nested = typeof problem.detail === 'object' ? problem.detail : undefined;
    const message = problem.message ?? problem.error?.message ?? nested?.message ?? (typeof problem.detail === 'string' ? problem.detail : undefined);
    throw new ApiError(message ?? '请求未完成，请稍后重试。', response.status, problem.code ?? problem.error?.code ?? nested?.code,
      problem.error?.details ?? problem.details ?? nested?.details);
  }
  return (await response.json()) as T;
}

async function requestForm<T>(path: string, form: FormData): Promise<T> {
  const response = await fetch(path, { method: 'POST', body: form });
  if (!response.ok) {
    let problem: ApiProblem = {};
    try {
      problem = (await response.json()) as ApiProblem;
    } catch {
      // Multipart failures may not include a JSON problem body.
    }
    const nested = typeof problem.detail === 'object' ? problem.detail : undefined;
    const message = problem.message ?? problem.error?.message ?? nested?.message ?? (typeof problem.detail === 'string' ? problem.detail : undefined);
    throw new ApiError(message ?? '模型导入未完成，请检查文件后重试。', response.status, problem.code ?? problem.error?.code ?? nested?.code);
  }
  return (await response.json()) as T;
}

async function requestBlob(path: string, init?: RequestInit, failureMessage = '图表暂时无法加载，请稍后重试。'): Promise<Blob> {
  const response = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!response.ok) {
    let problem: ApiProblem = {};
    try {
      problem = (await response.json()) as ApiProblem;
    } catch {
      // A chart transport failure may not include a JSON problem body.
    }
    const nested = typeof problem.detail === 'object' ? problem.detail : undefined;
    const message = problem.message ?? problem.error?.message ?? nested?.message ?? (typeof problem.detail === 'string' ? problem.detail : undefined);
    throw new ApiError(message ?? failureMessage, response.status, problem.code ?? problem.error?.code ?? nested?.code);
  }
  return response.blob();
}

/** Reads that project a display name ask for the reader's language; the server keeps the real name as fallback. */
function withLang(path: string, lang?: Lang): string {
  return lang ? `${path}${path.includes('?') ? '&' : '?'}${new URLSearchParams({ lang })}` : path;
}

export const api = {
  cbamReportData: (snapshotId: string, payload: CbamTrialRequest) => requestJson<FrozenReport>(`/api/v1/solved-system-snapshots/${snapshotId}/cbam-trial/report-data`, { method: 'POST', body: JSON.stringify(payload) }),
  cbamFullReport: (snapshotId: string, payload: CbamTrialRequest) => requestBlob(`/api/v1/solved-system-snapshots/${snapshotId}/cbam-trial/full-report.html`, { method: 'POST', body: JSON.stringify(payload) }),
  cbamReportExcel: (snapshotId: string, payload: CbamTrialRequest) => requestBlob(`/api/v1/solved-system-snapshots/${snapshotId}/cbam-trial/export.xlsx`, { method: 'POST', body: JSON.stringify(payload) }),
  organizationReportData: (applicationId: string, recordId: string, lang = 'zh') => requestJson<FrozenReport>(`/api/v1/applications/${applicationId}/organization-lifecycle-inventories/${recordId}/report-data?lang=${lang}`),
  organizationReportExcel: (applicationId: string, recordId: string, lang = 'zh') => requestBlob(`/api/v1/applications/${applicationId}/organization-lifecycle-inventories/${recordId}/export.xlsx?lang=${lang}`),
  organizationFullReport: (applicationId: string, recordId: string, lang = 'zh') => requestBlob(`/api/v1/applications/${applicationId}/organization-lifecycle-inventories/${recordId}/full-report.html?lang=${lang}`),
  workspace: (applicationId: string, revisionId: string, lang?: Lang) =>
    requestJson<ProjectWorkspace>(withLang(`/api/v1/applications/${applicationId}/workspace/${revisionId}`, lang)),
  applyReviewedCbam: (applicationId: string, revisionId: string, lang?: Lang) => requestJson<ProjectWorkspace>(
    withLang(`/api/v1/applications/${applicationId}/workspace/${revisionId}/reviewed-cbam`, lang), { method: 'POST' }),
  saveProjectInputs: (applicationId: string, payload: { revision_id: string; expected_content_sha256: string; amounts: number[]; demand_mode?: 'explicit' | 'reference_output'; values: Record<string, number>; source: string; background_process_pins?: BackgroundProcessPin[]; mapped_background_process_pins?: MappedBackgroundProcessPin[]; project_background_pins?: ProjectBackgroundPin[]; model_processing_rules_ref?: ModelProcessingRulesRef | null }, lang?: Lang) =>
    requestJson<ProjectWorkspace>(withLang(`/api/v1/applications/${applicationId}/workspace/inputs`, lang), { method: 'POST', body: JSON.stringify(payload) }),
  engine: () => requestJson<EngineStatus>('/api/v1/engine'),
  casepacks: () => requestJson<CasePackCatalogResponse>('/api/v1/casepacks'),
  setupStatus: () => requestJson<SetupStatus>('/api/v1/setup-status'),
  materializeCasePack: (
    casePackId: string,
    casePackVersion: string,
    applicationCaseId: string,
    applicationCaseVersion: string,
    payload: CasePackMaterializeRequest,
  ) => requestJson<CasePackMaterializeResult>(
    `/api/v1/casepacks/${encodeURIComponent(casePackId)}/versions/${encodeURIComponent(casePackVersion)}`
      + `/application-cases/${encodeURIComponent(applicationCaseId)}/versions/${encodeURIComponent(applicationCaseVersion)}/materialize`,
    { method: 'POST', body: JSON.stringify(payload) },
  ),
  capabilities: () => requestJson<CapabilityCatalogResponse>('/api/v1/capabilities'),
  applications: (lang?: Lang) => requestJson<Application[]>(withLang('/api/v1/applications', lang)),
  application: (id: string, lang?: Lang) => requestJson<Application>(withLang(`/api/v1/applications/${id}`, lang)),
  models: (applicationId: string) => requestJson<SystemModel[]>(`/api/v1/applications/${applicationId}/system-models`),
  modelSources: (applicationId: string) => requestJson<ModelSource[]>(`/api/v1/applications/${applicationId}/model-sources`),
  connectNebulaProject: (applicationId: string, payload: { name: string; upstream_project_id: string; upstream_version: number }) =>
    requestJson<ModelSourceAttachResult>(`/api/v1/applications/${applicationId}/model-sources/nebula-project`, {
      method: 'POST', body: JSON.stringify(payload),
    }),
  previewTidasBundle: (file: File) => {
    const form = new FormData(); form.append('file', file);
    return requestForm<ModelSourcePreview>('/api/v1/model-sources/tidas/preview', form);
  },
  inspectNativeBundle: (file: File) => {
    const form = new FormData(); form.append('file', file);
    return requestForm<ModelSourcePreview>('/api/v1/model-sources/native/inspect', form);
  },
  importTidasBundle: (applicationId: string, file: File, name: string, previewSha256: string) => {
    const form = new FormData();
    form.append('file', file); form.append('name', name); form.append('confirmed', 'true'); form.append('expected_preview_sha256', previewSha256);
    return requestForm<ModelSource>(`/api/v1/applications/${applicationId}/model-sources/tidas/import`, form);
  },
  restoreNativeBundle: (applicationId: string, file: File, name: string, previewSha256: string, conflictPolicy: 'rename' | 'fail') => {
    const form = new FormData();
    form.append('file', file); form.append('name', name); form.append('confirmed', 'true'); form.append('expected_preview_sha256', previewSha256); form.append('conflict_policy', conflictPolicy);
    return requestForm<ModelSource>(`/api/v1/applications/${applicationId}/model-sources/native/restore`, form);
  },
  attachModelSource: (sourceId: string, upstreamProjectId: string, upstreamVersion: number) =>
    requestJson<ModelSourceAttachResult>(`/api/v1/model-sources/${sourceId}/attach`, {
      method: 'POST', body: JSON.stringify({ upstream_project_id: upstreamProjectId, upstream_version: upstreamVersion }),
    }),
  revisions: (modelId: string) => requestJson<SystemRevision[]>(`/api/v1/system-models/${modelId}/revisions`),
  solvedSnapshots: (applicationId: string) => requestJson<SolvedSystemSnapshot[]>(`/api/v1/applications/${applicationId}/solved-system-snapshots`),
  pcfDefaultMethod: (snapshotId: string) => requestJson<ClimateMethodResolution>(`/api/v1/solved-system-snapshots/${snapshotId}/product-carbon-footprint/default-method`),
  periods: (applicationId: string) => requestJson<ReportingPeriod[]>(`/api/v1/applications/${applicationId}/periods`),
  methodPackages: () => requestJson<MethodPackage[]>('/api/v1/method-packages'),
  organizationLifecycleDisplay: (method: MethodPackage, lang: Lang) =>
    requestJson<OrganizationLifecycleDisplay>(`/api/v1/method-packages/organization-lifecycle-display?method_package_ref=${encodeURIComponent(`${method.package_id}@${method.version}`)}&method_package_sha256=${encodeURIComponent(method.content_sha256)}&lang=${lang}`),
  organizationPeriodInventories: (applicationId: string) => requestJson<OrganizationPeriodResult[]>(`/api/v1/applications/${applicationId}/organization-period-inventories`),
  createOrganizationPeriodInventory: (applicationId: string, payload: OrganizationPeriodRequest) =>
    requestJson<OrganizationPeriodResult>(`/api/v1/applications/${applicationId}/organization-period-inventories`, {
      method: 'POST', body: JSON.stringify(payload),
    }),
  organizationLifecycleInventories: (applicationId: string) => requestJson<OrganizationLifecycleResult[]>(`/api/v1/applications/${applicationId}/organization-lifecycle-inventories`),
  createOrganizationCurrentModel: (applicationId: string, payload: { solved_snapshot_id: string; method_package_ref: string }) =>
    requestJson<OrganizationLifecycleResult>(`/api/v1/applications/${applicationId}/organization-lifecycle-inventories/current-model`, {
      method: 'POST', body: JSON.stringify(payload),
    }),
  createOrganizationLifecycleInventory: (applicationId: string, payload: OrganizationLifecycleRequest) =>
    requestJson<OrganizationLifecycleResult>(`/api/v1/applications/${applicationId}/organization-lifecycle-inventories`, {
      method: 'POST', body: JSON.stringify(payload),
    }),
  productCarbonFootprint: (snapshotId: string, methodPackageRef: string, basis?: PcfBasisRequest) =>
    requestJson<ProductCarbonFootprint>(`/api/v1/solved-system-snapshots/${snapshotId}/product-carbon-footprint`, {
      method: 'POST',
      body: JSON.stringify({ method_package_ref: methodPackageRef, ...(basis && basis.result_basis !== 'total'
        ? { result_basis: basis.result_basis, base_amount: basis.base_amount, base_unit: basis.base_unit }
        : {}) }),
    }),
  productCarbonFootprintChart: (snapshotId: string, methodPackageRef: string, basis?: PcfBasisRequest) =>
    requestBlob(`/api/v1/solved-system-snapshots/${snapshotId}/product-carbon-footprint/chart.svg`, {
      method: 'POST',
      body: JSON.stringify({ method_package_ref: methodPackageRef, ...(basis && basis.result_basis !== 'total'
        ? { result_basis: basis.result_basis, base_amount: basis.base_amount, base_unit: basis.base_unit }
        : {}) }),
    }),
  productCarbonFootprintExport: (snapshotId: string, methodPackageRef: string, basis?: PcfBasisRequest) =>
    requestBlob(
      `/api/v1/solved-system-snapshots/${snapshotId}/product-carbon-footprint/export.xlsx?${pcfExportQuery(methodPackageRef, basis)}`,
      undefined,
      '产品碳足迹 Excel 暂时无法下载，请稍后重试。',
    ),
  productCarbonFootprintReport: (snapshotId: string, methodPackageRef: string, basis?: PcfBasisRequest) =>
    requestBlob(
      `/api/v1/solved-system-snapshots/${snapshotId}/product-carbon-footprint/report.html?${pcfExportQuery(methodPackageRef, basis)}`,
      undefined,
      '产品碳足迹报告暂时无法打开，请稍后重试。',
    ),
  nativeClimateExport: (snapshotId: string) =>
    requestBlob(
      `/api/v1/solved-system-snapshots/${snapshotId}/native-background-climate/export.xlsx`,
      undefined,
      '部分背景气候结果 Excel 暂时无法下载，请稍后重试。',
    ),
  nativeClimateReport: (snapshotId: string) =>
    requestBlob(
      `/api/v1/solved-system-snapshots/${snapshotId}/native-background-climate/report.html`,
      undefined,
      '部分背景气候结果报告暂时无法打开，请稍后重试。',
    ),
  energyCarrierResults: (snapshotId: string) => requestJson<EnergyCarrierResult[]>(`/api/v1/solved-system-snapshots/${snapshotId}/energy-carrier-results`),
  carbonManagement: (snapshotId: string, methodPackageRef: string, energyCarrierResultId: string) =>
    requestJson<CarbonManagementResult>(`/api/v1/solved-system-snapshots/${snapshotId}/carbon-management`, {
      method: 'POST',
      body: JSON.stringify({ method_package_ref: methodPackageRef, energy_carrier_result_id: energyCarrierResultId }),
    }),
  carbonManagementChart: (snapshotId: string, methodPackageRef: string, energyCarrierResultId: string) =>
    requestBlob(`/api/v1/solved-system-snapshots/${snapshotId}/carbon-management/chart.svg`, {
      method: 'POST',
      body: JSON.stringify({ method_package_ref: methodPackageRef, energy_carrier_result_id: energyCarrierResultId }),
    }),
  organizationGhgInventory: (applicationId: string, payload: OrganizationGhgInventoryRequest) =>
    requestJson<OrganizationGhgInventoryResult>(`/api/v1/applications/${applicationId}/organization-ghg-inventory-trial`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  organizationGhgInventoryChart: (applicationId: string, payload: OrganizationGhgInventoryRequest) =>
    requestBlob(`/api/v1/applications/${applicationId}/organization-ghg-inventory-trial/chart.svg`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  systemBindings: (applicationId: string) =>
    requestJson<SystemBinding[]>(`/api/v1/applications/${applicationId}/system-bindings`),
  organizationGhgInventoryV1: (applicationId: string, payload: OrganizationGhgInventoryV1Request) =>
    requestJson<OrganizationGhgInventoryV1Result>(`/api/v1/applications/${applicationId}/organization-ghg-inventory`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  organizationGhgInventoryV1Chart: (applicationId: string, payload: OrganizationGhgInventoryV1Request) =>
    requestBlob(`/api/v1/applications/${applicationId}/organization-ghg-inventory/chart.svg`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  cbamTrial: (snapshotId: string, payload: CbamTrialRequest) =>
    requestJson<CbamTrialResult>(`/api/v1/solved-system-snapshots/${snapshotId}/cbam-trial`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  cbamPartialReview: (snapshotId: string, payload: CbamPartialReviewRequest) =>
    requestJson<CbamPartialReviewResult>(`/api/v1/solved-system-snapshots/${snapshotId}/cbam-partial-review`, {
      method: 'POST', body: JSON.stringify(payload),
    }),
  cbamPartialReviewReport: (snapshotId: string, payload: CbamPartialReviewRequest) =>
    requestBlob(`/api/v1/solved-system-snapshots/${snapshotId}/cbam-partial-review/report.md`, {
      method: 'POST', body: JSON.stringify(payload),
    }),
  cbamTrialReport: (snapshotId: string, payload: CbamTrialRequest) =>
    requestBlob(`/api/v1/solved-system-snapshots/${snapshotId}/cbam-trial/report.html`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  cbamTrialChart: (snapshotId: string, payload: CbamTrialRequest) =>
    requestBlob(`/api/v1/solved-system-snapshots/${snapshotId}/cbam-trial/chart.svg`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  cbamComplexTrial: (snapshotId: string, payload: CbamComplexTrialRequest) =>
    requestJson<CbamComplexTrialResult>(`/api/v1/solved-system-snapshots/${snapshotId}/cbam-complex-trial`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  cbamComplexTrialChart: (snapshotId: string, payload: CbamComplexTrialRequest) =>
    requestBlob(`/api/v1/solved-system-snapshots/${snapshotId}/cbam-complex-trial/chart.svg`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  solvedMfa: (snapshotId: string, lang = 'zh') => requestJson<SolvedMfaResult>(`/api/v1/solved-system-snapshots/${snapshotId}/mfa?lang=${lang}`),
  boundaries: (applicationId: string) => requestJson<BoundaryDefinition[]>(`/api/v1/applications/${applicationId}/boundaries`),
  calculationMethods: (applicationId: string, modelRevisionId?: string) =>
    requestJson<CalculationMethod[]>(`/api/v1/applications/${applicationId}/calculation-methods${modelRevisionId ? `?model_revision_id=${encodeURIComponent(modelRevisionId)}` : ''}`),
  createCalculationMethod: (applicationId: string, payload: CalculationMethodCreatePayload) =>
    requestJson<CalculationMethodDetail>(`/api/v1/applications/${applicationId}/calculation-methods`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  calculationMethod: (methodId: string) => requestJson<CalculationMethodDetail>(`/api/v1/calculation-methods/${methodId}`),
  calculationMethodVersion: (methodId: string, version: number) =>
    requestJson<CalculationMethodVersion>(`/api/v1/calculation-methods/${methodId}/versions/${version}`),
  saveCalculationMethodVersion: (methodId: string, version: number, payload: CalculationMethodSavePayload) =>
    requestJson<CalculationMethodDetail>(`/api/v1/calculation-methods/${methodId}/versions/${version}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  cloneCalculationMethod: (methodId: string, version: number, payload: CalculationMethodClonePayload) =>
    requestJson<CalculationMethodDetail>(`/api/v1/calculation-methods/${methodId}/versions/${version}/clone`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  validateCalculationMethodVersion: (methodId: string, version: number) =>
    requestJson<CalculationMethodValidation>(`/api/v1/calculation-methods/${methodId}/versions/${version}/validate`, {
      method: 'POST',
    }),
  resultCategoryConversionPreview: (methodId: string, version: number) =>
    requestJson<ResultCategoryConversionPreview>(`/api/v1/calculation-methods/${methodId}/versions/${version}/conversion-preview`),
  resultCategoryConversionPreviewMapping: (methodId: string, version: number, options: ResultCategoryConversionOptions) =>
    requestJson<ResultCategoryConversionPreview>(`/api/v1/calculation-methods/${methodId}/versions/${version}/conversion-preview`, {
      method: 'POST',
      body: JSON.stringify(options),
    }),
  convertToResultCategory: (methodId: string, version: number, payload: ResultCategoryConversionPayload) =>
    requestJson<CalculationMethodDetail>(`/api/v1/calculation-methods/${methodId}/versions/${version}/convert`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  classificationSuggestions: (methodId: string, version: number) =>
    requestJson<ClassificationSuggestions>(`/api/v1/calculation-methods/${methodId}/versions/${version}/classification-suggestions`),
  selectableProcessingPackages: (methodId: string) =>
    requestJson<ProcessingPackageOption[]>(`/api/v1/calculation-methods/${methodId}/selectable-processing-packages`),
  calculationMethodCapabilities: (methodId: string) =>
    requestJson<CalculationMethodCapabilities>(`/api/v1/calculation-methods/${methodId}/capabilities`),
  archiveCalculationMethod: (methodId: string) =>
    requestJson<CalculationMethod>(`/api/v1/calculation-methods/${methodId}/archive`, { method: 'POST' }),
  tagGrouping: (applicationId: string, payload: TagGroupingRequest) =>
    requestJson<TagGroupingResult>(`/api/v1/applications/${applicationId}/tag-grouping`, {
      method: 'POST', body: JSON.stringify(payload),
    }),
  tagGroupingHistory: (applicationId: string, snapshotId: string) =>
    requestJson<TagGroupingResult[]>(`/api/v1/applications/${applicationId}/tag-grouping-results?snapshot_id=${encodeURIComponent(snapshotId)}`),
  tagGroupingResult: (applicationId: string, resultId: string) =>
    requestJson<TagGroupingResult>(`/api/v1/applications/${applicationId}/tag-grouping-results/${encodeURIComponent(resultId)}`),
  tagGroupingExport: (applicationId: string, resultId: string, format: 'html' | 'json') =>
    requestBlob(`/api/v1/applications/${applicationId}/tag-grouping-results/${encodeURIComponent(resultId)}/export?format=${format}`),
  spatialAggregate: (snapshotId: string, boundaryId: string) =>
    requestJson<SpatialAggregateResult>(`/api/v1/solved-system-snapshots/${snapshotId}/spatial-aggregate`, {
      method: 'POST',
      body: JSON.stringify({ boundary_id: boundaryId }),
    }),
  spatialAggregateChart: (snapshotId: string, boundaryId: string, seriesId: string) =>
    requestBlob(`/api/v1/solved-system-snapshots/${snapshotId}/spatial-aggregate/sankey.svg`, {
      method: 'POST',
      body: JSON.stringify({ boundary_id: boundaryId, series_id: seriesId }),
    }),
  spatialEnergy: (snapshotId: string, boundaryId: string, energyCarrierResultId: string) =>
    requestJson<SpatialEnergyResult>(`/api/v1/solved-system-snapshots/${snapshotId}/spatial-energy`, {
      method: 'POST',
      body: JSON.stringify({ boundary_id: boundaryId, energy_carrier_result_id: energyCarrierResultId }),
    }),
  spatialEnergyChart: (snapshotId: string, boundaryId: string, energyCarrierResultId: string, seriesId: string) =>
    requestBlob(`/api/v1/solved-system-snapshots/${snapshotId}/spatial-energy/sankey.svg`, {
      method: 'POST',
      body: JSON.stringify({ boundary_id: boundaryId, energy_carrier_result_id: energyCarrierResultId, series_id: seriesId }),
    }),
  spatialDistribution: (snapshotId: string, methodPackageRef: string) =>
    requestJson<SpatialDistributionResult>(`/api/v1/solved-system-snapshots/${snapshotId}/spatial-distribution`, {
      method: 'POST',
      body: JSON.stringify({ method_package_ref: methodPackageRef }),
    }),
  spatialDistributionMap: (snapshotId: string, methodPackageRef: string, scenarioId: string) =>
    requestBlob(`/api/v1/solved-system-snapshots/${snapshotId}/spatial-distribution/map.svg`, {
      method: 'POST',
      body: JSON.stringify({ method_package_ref: methodPackageRef, scenario_id: scenarioId }),
    }),
  solveAndFreeze: (applicationId: string, revisionId: string, payload: SolveAndFreezeRequest) =>
    requestJson<SolvedSystemSnapshot>(`/api/v1/applications/${applicationId}/system-revisions/${revisionId}/solve`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  scenarios: (applicationId: string) => requestJson<Scenario[]>(`/api/v1/applications/${applicationId}/scenarios`),
  comparisons: (applicationId: string) => requestJson<Comparison[]>(`/api/v1/applications/${applicationId}/comparisons`),
  comparisonRuns: (applicationId: string) => requestJson<ComparisonRun[]>(`/api/v1/applications/${applicationId}/scenario-comparison-runs`),
  comparisonRun: (runId: string) => requestJson<ComparisonRun>(`/api/v1/scenario-comparison-runs/${runId}`),
  periodEnergyComparison: (runId: string) =>
    requestJson<PeriodEnergyComparisonResult>(`/api/v1/scenario-comparison-runs/${runId}/period-energy-comparison`, {
      method: 'POST',
      body: JSON.stringify({}),
    }),
  periodEnergyComparisonChart: (runId: string) =>
    requestBlob(`/api/v1/scenario-comparison-runs/${runId}/period-energy-comparison/chart.svg`, {
      method: 'POST',
      body: JSON.stringify({}),
    }),
  periodEnergyTrend: (applicationId: string, payload: PeriodEnergyTrendRequest) =>
    requestJson<PeriodEnergyTrendResult>(`/api/v1/applications/${applicationId}/period-energy-trend`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  periodEnergyTrendChart: (applicationId: string, payload: PeriodEnergyTrendRequest) =>
    requestBlob(`/api/v1/applications/${applicationId}/period-energy-trend/chart.svg`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  inventorySnapshots: (applicationId: string) =>
    requestJson<InventorySnapshot[]>(`/api/v1/applications/${applicationId}/inventory-snapshots`),
  inventoryDataPoints: (inventoryId: string) =>
    requestJson<InventoryDataPoint[]>(`/api/v1/inventory-snapshots/${inventoryId}/data-points`),
  periodEnergyTotal: (applicationId: string, payload: PeriodEnergyTotalRequest) =>
    requestJson<PeriodEnergyTotalResult>(`/api/v1/applications/${applicationId}/period-energy-total`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  periodEnergyTotalChart: (applicationId: string, payload: PeriodEnergyTotalRequest) =>
    requestBlob(`/api/v1/applications/${applicationId}/period-energy-total/chart.svg`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  executeComparison: (comparisonId: string, payload: ComparisonExecuteRequest) =>
    requestJson<ComparisonRun>(`/api/v1/comparisons/${comparisonId}/execute`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
};

export function shortId(value: string | null | undefined): string {
  if (!value) return '未记录';
  return value.length > 18 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return '未记录';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '未记录';
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}
