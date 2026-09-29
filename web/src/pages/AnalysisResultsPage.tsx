import { Alert, Button, Descriptions, Drawer, Select, Table, Tabs } from '@arco-design/web-react';
import { IconArrowLeft, IconFile, IconInfoCircle } from '@arco-design/web-react/icon';
import { useQuery } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useUrlSelection } from '../hooks/useUrlSelection';
import { api } from '../api/client';
import { useI18n } from '../i18n';
import { projectResultViews } from '../api/projectViews';
import type { MethodPackage, SolvedSystemSnapshot } from '../api/types';
import { EnergyCarrierResultPanel } from '../components/EnergyCarrierResultPanel';
import { ProductCarbonFootprintPanel } from '../components/ProductCarbonFootprintPanel';
import { processDisplayNodes } from '../components/ContributionChart';
import { NativeClimatePanel } from '../components/NativeClimatePanel';
import { PeriodEnergyTrendPanel } from '../components/PeriodEnergyTrendPanel';
import { CarbonManagementPanel } from '../components/CarbonManagementPanel';
import { CbamRuleTrialPanel } from '../components/CbamRuleTrialPanel';
import { OrganizationGhgInventoryPanel } from '../components/OrganizationGhgInventoryPanel';
import { OrganizationPeriodPanel } from '../components/OrganizationPeriodPanel';
import { OrganizationLifecyclePanel } from '../components/OrganizationLifecyclePanel';
import { CbamPartialReviewPanel } from '../components/CbamPartialReviewPanel';
import { SpatialAggregatePanel } from '../components/SpatialAggregatePanel';
import { SpatialEnergyPanel } from '../components/SpatialEnergyPanel';
import { SpatialDistributionPanel } from '../components/SpatialDistributionPanel';
import { AnalysisTabs } from '../components/AnalysisTabs';
import { MfaResultPanel } from '../components/MfaResultPanel';
import { SnapshotContext } from '../components/SnapshotContext';
import { CopyableValue } from '../components/ui/CopyableValue';
import { InvalidReferencesAlert } from '../components/ui/InvalidReferencesAlert';
import { EmptyState, ErrorState, LoadingState, NotFoundState } from '../components/ui/States';

interface IndicatorResult {
  _row_key: string;
  canonical_indicator_key?: string;
  indicator_en?: string;
  method_en?: string;
  method?: string;
  value?: number;
  indicator_unit?: string;
  unit?: string;
}

const RESULT_TAB_KEYS = new Set(['mfa', 'lcia', 'spatial', 'spatial-energy', 'distribution', 'energy', 'period-energy', 'pcf', 'carbon', 'organization-ghg', 'organization-period', 'organization-lifecycle', 'cbam', 'scenario', 'climate']);

function indicators(snapshot: SolvedSystemSnapshot): IndicatorResult[] {
  const values = snapshot.lcia_results.indicator_results;
  return Array.isArray(values)
    ? values.flatMap((item, index) => {
      if (!item || typeof item !== 'object') return [];
      const indicator = item as Omit<IndicatorResult, '_row_key'>;
      return [{
        ...indicator,
        _row_key: `${indicator.canonical_indicator_key ?? indicator.indicator_en ?? 'indicator'}:${index}`,
      }];
    })
    : [];
}

function methodPackageRefs(context: Record<string, unknown> | undefined): string[] {
  const values = context?.method_package_refs;
  return Array.isArray(values)
    ? values.filter((value): value is string => typeof value === 'string' && value.trim().length > 0)
    : [];
}

/** cbam.trial.v2 computes against a named frozen boundary; the manifest is the only routing basis. */
const CBAM_TRIAL_V2_SCHEMA_VERSION = 'nebula_one.cbam.trial.v2';

function outputsCbamTrialV2(pkg: MethodPackage): boolean {
  const outputSchema: unknown = pkg.manifest.output_schema;
  return typeof outputSchema === 'object' && outputSchema !== null
    && (outputSchema as Record<string, unknown>).schema_version === CBAM_TRIAL_V2_SCHEMA_VERSION;
}

function snapshotPurpose(snapshot: SolvedSystemSnapshot | undefined): string | undefined {
  const basis = snapshot?.provider_receipt?.calculation_basis as { model_derivation?: { purpose?: string } } | undefined;
  return basis?.model_derivation?.purpose;
}

// A native climate answer or a project supply receipt is a property of the frozen snapshot. Tasks
// that read the climate total can only run against a snapshot that actually carries one; the base
// solve never substitutes for it, which is what kept a pure MFA record from triggering a 422.
function hasClimateReceipt(snapshot: SolvedSystemSnapshot): boolean {
  return Boolean(snapshot.native_background_climate);
}
function hasProjectReceipts(snapshot: SolvedSystemSnapshot): boolean {
  return Array.isArray(snapshot.provider_receipt.project_background_process_receipts)
    && snapshot.provider_receipt.project_background_process_receipts.length > 0;
}
function hasClimateAnswer(snapshot: SolvedSystemSnapshot): boolean {
  return hasClimateReceipt(snapshot) || hasProjectReceipts(snapshot);
}

function hasPinnedClimateMethod(snapshot: SolvedSystemSnapshot): boolean {
  const basis = snapshot.provider_receipt.calculation_basis as {
    calculation_method?: { reference?: string; content_sha256?: string; lcia_method?: string };
    lcia_methods?: string[];
  } | undefined;
  const method = basis?.calculation_method;
  return typeof method?.reference === 'string' && method.reference.length > 0
    && typeof method.content_sha256 === 'string' && /^[0-9a-f]{64}$/.test(method.content_sha256)
    && typeof method.lcia_method === 'string'
    && basis?.lcia_methods?.includes(method.lcia_method) === true
    && (snapshot.lcia_results.method === method.lcia_method
      || snapshot.native_background_climate?.response.indicator.method === method.lcia_method);
}

/** Each result tab is served only by records that carry the receipt that task computes from. */
function recordCompatible(snapshot: SolvedSystemSnapshot, task: string, strict: boolean): boolean {
  if (task === 'cbam') return snapshotPurpose(snapshot) === 'cbam';
  if (task === 'pcf') return !strict || (hasClimateAnswer(snapshot)
    && (snapshotPurpose(snapshot) === 'lca'
      || (snapshotPurpose(snapshot) === undefined && hasPinnedClimateMethod(snapshot))));
  if (task === 'climate' || task === 'organization-lifecycle' || task === 'organization-period') return hasClimateAnswer(snapshot);
  return true;
}

function taskComputeHref(applicationId: string, revisionId?: string): string {
  return `/applications/${applicationId}/workbench?step=reports${revisionId ? `&revision=${revisionId}` : ''}`;
}

/** A task tab with no compatible record offers one compute action back to the workbench, never a
 *  read of an incompatible snapshot. */
function TaskComputePrompt({ applicationId, revisionId, label }: { applicationId: string; revisionId?: string; label: string }) {
  const { t } = useI18n();
  return <>
    <EmptyState description={t('results.taskMissing')} />
    <div className="form-actions"><Link className="arco-btn arco-btn-primary" to={taskComputeHref(applicationId, revisionId)} aria-label={t('results.compute', { task: label })}>{t('results.compute', { task: label })}</Link></div>
  </>;
}

function TaskBackgroundPrompt({ applicationId, revisionId }: { applicationId: string; revisionId: string }) {
  const { t } = useI18n();
  return <>
    <EmptyState description={t('results.supplyMissing')} />
    <div className="form-actions"><Link className="arco-btn arco-btn-primary" to={`/applications/${applicationId}/workbench?step=data&revision=${revisionId}`}>{t('results.linkSupply')}</Link></div>
  </>;
}

export function AnalysisResultsPage() {
  const { lang, t, formatDate, formatNumber } = useI18n();
  const { applicationId } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const [auditVisible, setAuditVisible] = useState(false);
  const [selectedMfaSeriesId, setSelectedMfaSeriesId] = useState('');
  const [selectedCarbonMethodRef, setSelectedCarbonMethodRef] = useState('');
  const [selectedSpatialBoundaryId, setSelectedSpatialBoundaryId] = useState('');
  const [selectedSpatialSeriesId, setSelectedSpatialSeriesId] = useState('');
  const [selectedSpatialEnergySeriesId, setSelectedSpatialEnergySeriesId] = useState('');
  const [selectedDistributionMethodRef, setSelectedDistributionMethodRef] = useState('');
  const [selectedDistributionScenarioId, setSelectedDistributionScenarioId] = useState('');
  const requestedResultTab = searchParams.get('view') ?? '';
  const knownResultTab = RESULT_TAB_KEYS.has(requestedResultTab);
  const application = useQuery({ queryKey: ['application', applicationId, lang], queryFn: () => api.application(applicationId!, lang), enabled: Boolean(applicationId) });
  const declaredViews = application.data?.context.template_locked || application.data?.context.modeling_handoff_id ? projectResultViews(application.data.context.project_capabilities) : undefined;
  const snapshots = useQuery({ queryKey: ['solved-snapshots', applicationId], queryFn: () => api.solvedSnapshots(applicationId!), enabled: Boolean(applicationId) });
  const comparisonRuns = useQuery({ queryKey: ['comparison-runs', applicationId], queryFn: () => api.comparisonRuns(applicationId!), enabled: Boolean(applicationId) });
  const boundMethodPackageRefs = useMemo(() => methodPackageRefs(application.data?.context), [application.data?.context]);
  const methodPackages = useQuery({
    queryKey: ['method-packages', applicationId],
    queryFn: () => api.methodPackages(),
    enabled: Boolean(applicationId),
  });
  const carbonMethodPackages = useMemo(() => (methodPackages.data ?? []).flatMap((item) => {
    const reference = `${item.package_id}@${item.version}`;
    if (item.package_kind !== 'period_carbon_management' || !boundMethodPackageRefs.includes(reference)) return [];
    return [{ reference, label: `${item.package_id} · ${item.version}` }];
  }), [boundMethodPackageRefs, methodPackages.data]);
  const distributionMethodPackages = useMemo(() => (methodPackages.data ?? []).flatMap((item) => {
    const reference = `${item.package_id}@${item.version}`;
    if (item.package_kind !== 'spatial_distribution' || !boundMethodPackageRefs.includes(reference)) return [];
    return [{ reference, label: `${item.package_id} · ${item.version}` }];
  }), [boundMethodPackageRefs, methodPackages.data]);
  const cbamMethods = useMemo(() => (methodPackages.data ?? []).reduce((groups, item) => {
    const reference = `${item.package_id}@${item.version}`;
    if (!boundMethodPackageRefs.includes(reference)) return groups;
    const option = { reference, label: `${item.package_id} · ${item.version}` };
    if (item.package_kind === 'cbam_trial') groups.simple.push(option);
    if (item.package_kind === 'cbam_complex_trial') groups.complex.push(option);
    return groups;
  }, { simple: [] as Array<{ reference: string; label: string }>, complex: [] as Array<{ reference: string; label: string }> }), [boundMethodPackageRefs, methodPackages.data]);
  const organizationGhgMethods = useMemo(() => (methodPackages.data ?? []).filter((item) => (
    item.package_kind === 'organization_ghg_inventory_trial'
    && boundMethodPackageRefs.includes(`${item.package_id}@${item.version}`)
  )), [boundMethodPackageRefs, methodPackages.data]);
  const formalOrganizationGhgMethods = useMemo(() => (methodPackages.data ?? []).filter((item) => (
    item.package_kind === 'organization_ghg_inventory'
    && boundMethodPackageRefs.includes(`${item.package_id}@${item.version}`)
  )), [boundMethodPackageRefs, methodPackages.data]);
  const organizationPcfMethods = useMemo(() => (methodPackages.data ?? []).filter((item) => (
    item.package_kind === 'product_carbon_footprint'
    && boundMethodPackageRefs.includes(`${item.package_id}@${item.version}`)
  )), [boundMethodPackageRefs, methodPackages.data]);
  const organizationPeriodMethod = useMemo(() => boundMethodPackageRefs.slice().reverse()
    .map(reference => (methodPackages.data ?? []).find(item => `${item.package_id}@${item.version}` === reference))
    .find(item => item?.package_kind === 'organization_period_inventory'), [boundMethodPackageRefs, methodPackages.data]);
  const organizationLifecycleMethod = useMemo(() => boundMethodPackageRefs.slice().reverse()
    .map(reference => (methodPackages.data ?? []).find(item => `${item.package_id}@${item.version}` === reference))
    .find(item => item?.package_kind === 'organization_lifecycle_carbon'), [boundMethodPackageRefs, methodPackages.data]);
  const cbamPartialReviewMethod = useMemo(() => boundMethodPackageRefs.slice().reverse()
    .map(reference => (methodPackages.data ?? []).find(item => `${item.package_id}@${item.version}` === reference))
    .find(item => item?.package_kind === 'cbam_partial_review'), [boundMethodPackageRefs, methodPackages.data]);
  const provinceElectricityMethods = useMemo(() => (methodPackages.data ?? []).filter((item) => (
    item.package_kind === 'province_electricity_factor'
    && boundMethodPackageRefs.includes(`${item.package_id}@${item.version}`)
  )), [boundMethodPackageRefs, methodPackages.data]);
  const organizationCarbonMethods = useMemo(() => (methodPackages.data ?? []).filter((item) => (
    item.package_kind === 'period_carbon_management'
    && boundMethodPackageRefs.includes(`${item.package_id}@${item.version}`)
  )), [boundMethodPackageRefs, methodPackages.data]);
  const requestedId = searchParams.get('snapshot');
  const requestedRevision = searchParams.get('revision');
  // A native climate answer is a property of the frozen snapshot, not of the template, so the climate
  // tab is offered only when some record actually carries one; a projection snapshot still refuses the
  // deep link instead of borrowing another task's result.
  const climateOffered = (snapshots.data ?? []).some(hasClimateAnswer);
  const allowedViews = climateOffered && declaredViews !== undefined
    ? [...declaredViews, 'climate']
    : declaredViews;
  const invalidResultView = searchParams.has('view') && (!knownResultTab || (allowedViews !== undefined && !allowedViews.includes(requestedResultTab)));
  const activeResultTab = knownResultTab ? requestedResultTab : (allowedViews?.[0] ?? 'mfa');
  // Each task reads only the records that carry its own receipt: the same source revision can be
  // solved as several tasks, and a pure MFA record is never handed to a climate-backed reader.
  const taskRecords = (snapshots.data ?? []).filter((item) =>
    (!requestedRevision || item.system_revision_id === requestedRevision) && recordCompatible(item, activeResultTab, declaredViews !== undefined));
  const requestedMissing = Boolean(requestedId) && !(snapshots.data ?? []).some((item) => item.id === requestedId);
  const requestedRecord = (snapshots.data ?? []).find((item) => item.id === requestedId);
  const missingTaskBackground = !requestedMissing && requestedRecord && !hasClimateAnswer(requestedRecord)
    && ['pcf', 'organization-lifecycle'].includes(activeResultTab);
  const selected = requestedMissing
    ? undefined
    : requestedId
      ? taskRecords.find((item) => item.id === requestedId)
      : taskRecords.at(-1);
  const selectedPurpose = snapshotPurpose(selected);
  const selectedDemand = (selected?.provider_receipt.calculation_basis as { demand?: Array<{ amount: number; unit: string }> } | undefined)?.demand;
  // Names come from the exact saved model revision, never a client-side UUID dictionary.
  const resultWorkspace = useQuery({
    queryKey: ['workspace', applicationId, selected?.system_revision_id, lang],
    queryFn: () => api.workspace(applicationId!, selected!.system_revision_id, lang),
    enabled: Boolean(applicationId && selected && activeResultTab === 'pcf' && application.data?.context.template_locked),
  });
  const pcfResolved = useQuery({
    queryKey: ['pcf-default-method', selected?.id],
    queryFn: () => api.pcfDefaultMethod(selected!.id),
    enabled: Boolean(selected && activeResultTab === 'pcf'),
  });
  const pcfMethodPackages = useMemo(() => (methodPackages.data ?? []).flatMap((item) => {
    const reference = `${item.package_id}@${item.version}`;
    if (item.package_kind !== 'product_carbon_footprint'
        || (!boundMethodPackageRefs.includes(reference) && pcfResolved.data?.reference !== reference)) return [];
    const formula = item.manifest.formula_graph as { lcia_method?: string; source_contract?: string } | undefined;
    const methodName = formula?.lcia_method || t('results.productClimate');
    const coverage = formula?.source_contract ? t('results.withBackground') : t('results.modelScope');
    return [{ reference, label: `${methodName} ${t('results.climateChange')} · ${coverage} · v${item.version}` }];
  }), [boundMethodPackageRefs, methodPackages.data, pcfResolved.data?.reference, t]);
  const pcfMethodRefs = useMemo(() => pcfMethodPackages.map((item) => item.reference), [pcfMethodPackages]);
  const explicitPcfMethod = searchParams.has('pcf-method');
  const pcfSelection = useUrlSelection('pcf-method', pcfMethodRefs, {
    ready: !application.isLoading && !snapshots.isLoading && !methodPackages.isLoading
      && (explicitPcfMethod || !pcfResolved.isLoading),
  });
  const pcfMethod = { ...pcfSelection, value: explicitPcfMethod ? pcfSelection.value : (pcfSelection.pending ? '' : pcfResolved.data?.reference ?? '') };
  const energyResults = useQuery({
    queryKey: ['energy-carrier-results', selected?.id],
    queryFn: () => api.energyCarrierResults(selected!.id),
    enabled: Boolean(selected),
  });
  const selectedEnergy = energyResults.data?.[energyResults.data.length - 1];
  const solvedMfa = useQuery({
    queryKey: ['solved-mfa', selected?.id],
    queryFn: () => api.solvedMfa(selected!.id),
    enabled: Boolean(selected),
  });
  const boundaries = useQuery({
    queryKey: ['boundaries', applicationId],
    queryFn: () => api.boundaries(applicationId!),
    enabled: Boolean(applicationId),
  });
  const parkBoundaries = useMemo(
    () => (boundaries.data ?? []).filter((item) => item.boundary_type === 'park' && item.status === 'frozen'),
    [boundaries.data],
  );
  const cbamTrialBoundaries = useMemo(
    () => (boundaries.data ?? []).filter((item) => item.boundary_type === 'cbam_trial' && item.status === 'frozen'),
    [boundaries.data],
  );
  const showCbamTrial = selectedPurpose === 'cbam' && cbamMethods.simple.length > 0;
  const cbamBoundaryRequiredFor = useMemo(() => (methodPackages.data ?? [])
    .filter((item) => outputsCbamTrialV2(item)
      && cbamMethods.simple.some((option) => option.reference === `${item.package_id}@${item.version}`))
    .map((item) => `${item.package_id}@${item.version}`), [cbamMethods.simple, methodPackages.data]);
  const spatialAggregate = useQuery({
    queryKey: ['spatial-aggregate', selected?.id, selectedSpatialBoundaryId],
    queryFn: () => api.spatialAggregate(selected!.id, selectedSpatialBoundaryId),
    enabled: Boolean(selected && selectedSpatialBoundaryId),
  });
  const spatialAggregateChart = useQuery({
    queryKey: ['spatial-aggregate-chart', selected?.id, selectedSpatialBoundaryId, selectedSpatialSeriesId],
    queryFn: () => api.spatialAggregateChart(selected!.id, selectedSpatialBoundaryId, selectedSpatialSeriesId),
    enabled: Boolean(selected && selectedSpatialBoundaryId && selectedSpatialSeriesId && spatialAggregate.data),
  });
  const spatialEnergy = useQuery({
    queryKey: ['spatial-energy', selected?.id, selectedSpatialBoundaryId, selectedEnergy?.id],
    queryFn: () => api.spatialEnergy(selected!.id, selectedSpatialBoundaryId, selectedEnergy!.id),
    enabled: Boolean(selected && selectedSpatialBoundaryId && selectedEnergy),
  });
  const spatialEnergyChart = useQuery({
    queryKey: ['spatial-energy-chart', selected?.id, selectedSpatialBoundaryId, selectedEnergy?.id, selectedSpatialEnergySeriesId],
    queryFn: () => api.spatialEnergyChart(selected!.id, selectedSpatialBoundaryId, selectedEnergy!.id, selectedSpatialEnergySeriesId),
    enabled: Boolean(selected && selectedSpatialBoundaryId && selectedEnergy && selectedSpatialEnergySeriesId && spatialEnergy.data),
  });
  const spatialDistribution = useQuery({
    queryKey: ['spatial-distribution', selected?.id, selectedDistributionMethodRef],
    queryFn: () => api.spatialDistribution(selected!.id, selectedDistributionMethodRef),
    enabled: Boolean(selected && selectedDistributionMethodRef),
  });
  const spatialDistributionChart = useQuery({
    queryKey: ['spatial-distribution-chart', selected?.id, selectedDistributionMethodRef, selectedDistributionScenarioId],
    queryFn: () => api.spatialDistributionMap(selected!.id, selectedDistributionMethodRef, selectedDistributionScenarioId),
    enabled: Boolean(selected && selectedDistributionMethodRef && selectedDistributionScenarioId && spatialDistribution.data),
  });
  const productCarbonFootprint = useQuery({
    queryKey: ['product-carbon-footprint', selected?.id, pcfMethod.value],
    queryFn: () => api.productCarbonFootprint(selected!.id, pcfMethod.value),
    enabled: Boolean(selected && activeResultTab === 'pcf' && pcfMethod.value),
  });
  const productCarbonFootprintChart = useQuery({
    queryKey: ['product-carbon-footprint-chart', selected?.id, pcfMethod.value],
    queryFn: () => api.productCarbonFootprintChart(selected!.id, pcfMethod.value),
    enabled: Boolean(selected && activeResultTab === 'pcf' && pcfMethod.value && productCarbonFootprint.data),
  });
  const carbonManagement = useQuery({
    queryKey: ['carbon-management', selected?.id, selectedCarbonMethodRef, selectedEnergy?.id],
    queryFn: () => api.carbonManagement(selected!.id, selectedCarbonMethodRef, selectedEnergy!.id),
    enabled: Boolean(selected && selectedCarbonMethodRef && selectedEnergy),
  });
  const carbonManagementChart = useQuery({
    queryKey: ['carbon-management-chart', selected?.id, selectedCarbonMethodRef, selectedEnergy?.id],
    queryFn: () => api.carbonManagementChart(selected!.id, selectedCarbonMethodRef, selectedEnergy!.id),
    enabled: Boolean(selected && selectedCarbonMethodRef && selectedEnergy && carbonManagement.data),
  });
  const lciaIndicators = useMemo(() => selected ? indicators(selected) : [], [selected]);
  const lineageComparisons = useMemo(() => selected ? (comparisonRuns.data ?? []).filter((run) => run.scenario_results.some((result) => result.solved_snapshot_id === selected.id)) : [], [comparisonRuns.data, selected]);

  useEffect(() => {
    if (!selected || requestedId === selected.id) return;
    const next = new URLSearchParams(searchParams);
    next.set('snapshot', selected.id);
    setSearchParams(next, { replace: true });
  }, [requestedId, searchParams, selected, setSearchParams]);

  useEffect(() => {
    const massSeries = (solvedMfa.data?.series ?? []).filter((item) => item.is_mass);
    if (!massSeries.length) {
      setSelectedMfaSeriesId('');
      return;
    }
    if (!massSeries.some((item) => item.series_id === selectedMfaSeriesId)) {
      setSelectedMfaSeriesId(massSeries[0].series_id);
    }
  }, [selectedMfaSeriesId, solvedMfa.data]);

  useEffect(() => {
    if (!carbonMethodPackages.length) {
      setSelectedCarbonMethodRef('');
      return;
    }
    if (!carbonMethodPackages.some((item) => item.reference === selectedCarbonMethodRef)) {
      setSelectedCarbonMethodRef(carbonMethodPackages[0].reference);
    }
  }, [carbonMethodPackages, selectedCarbonMethodRef]);

  useEffect(() => {
    if (!parkBoundaries.length) {
      setSelectedSpatialBoundaryId('');
      return;
    }
    if (!parkBoundaries.some((item) => item.id === selectedSpatialBoundaryId)) {
      setSelectedSpatialBoundaryId(parkBoundaries[0].id);
    }
  }, [parkBoundaries, selectedSpatialBoundaryId]);

  useEffect(() => {
    const series = spatialAggregate.data?.series ?? [];
    if (!series.length) {
      setSelectedSpatialSeriesId('');
      return;
    }
    if (!series.some((item) => item.series_id === selectedSpatialSeriesId)) {
      setSelectedSpatialSeriesId(series[0].series_id);
    }
  }, [selectedSpatialSeriesId, spatialAggregate.data]);

  useEffect(() => {
    const series = spatialEnergy.data?.series ?? [];
    if (!series.length) {
      setSelectedSpatialEnergySeriesId('');
      return;
    }
    if (!series.some((item) => item.series_id === selectedSpatialEnergySeriesId)) {
      setSelectedSpatialEnergySeriesId(series[0].series_id);
    }
  }, [selectedSpatialEnergySeriesId, spatialEnergy.data]);

  useEffect(() => {
    if (!distributionMethodPackages.length) {
      setSelectedDistributionMethodRef('');
      return;
    }
    if (!distributionMethodPackages.some((item) => item.reference === selectedDistributionMethodRef)) {
      setSelectedDistributionMethodRef(distributionMethodPackages[0].reference);
    }
  }, [distributionMethodPackages, selectedDistributionMethodRef]);

  useEffect(() => {
    const scenarios = spatialDistribution.data?.scenarios ?? [];
    if (!scenarios.length) {
      setSelectedDistributionScenarioId('');
      return;
    }
    if (!scenarios.some((item) => item.scenario_id === selectedDistributionScenarioId)) {
      setSelectedDistributionScenarioId(spatialDistribution.data?.baseline_scenario_id ?? scenarios[0].scenario_id);
    }
  }, [selectedDistributionScenarioId, spatialDistribution.data]);

  if (!applicationId) return <NotFoundState />;
  const error = application.error || snapshots.error;
  return (
    <main className="app-page">
      <header className="result-page-header">
        <div className="result-page-header__top">
          <h1>{application.data?.name ?? t('results.title')}</h1>
          <Button icon={<IconArrowLeft />} onClick={() => navigate(`/applications/${applicationId}/workbench${application.data?.context.template_locked && selected ? `?step=reports&revision=${selected.system_revision_id}` : ''}`)}>{t('analysis.backToProject')}</Button>
        </div>
        {selected && !invalidResultView && activeResultTab !== 'organization-ghg' ? <div className="result-page-header__records">
          <label htmlFor="snapshot-select">{t('analysis.recordSelectorAria')}</label>
          <Select id="snapshot-select" value={selected.id} onChange={(value) => {
            const next = new URLSearchParams(searchParams);
            next.set('snapshot', value);
            setSearchParams(next);
          }} options={taskRecords.map((item, index) => ({ label: t('results.record', { number: taskRecords.length - index, date: formatDate(item.created_at) }), value: item.id }))} />
          {selectedDemand?.length === 1 ? <span className="result-page-header__basis">{t('results.demand', { amount: formatNumber(selectedDemand[0].amount), unit: selectedDemand[0].unit })}</span> : null}
          <Button icon={<IconInfoCircle />} onClick={() => setAuditVisible(true)}>{t('analysis.calculationDetails')}</Button>
        </div> : null}
      </header>
      {application.isLoading || snapshots.isLoading ? <section className="section-panel"><LoadingState rows={7} /></section> : null}
      {error ? <ErrorState error={error} onRetry={() => { application.refetch(); snapshots.refetch(); }} /> : null}
      {!error && !snapshots.isLoading && !requestedMissing && !selected && !invalidResultView ? <section className="section-panel">{missingTaskBackground && requestedRecord ? <TaskBackgroundPrompt applicationId={applicationId!} revisionId={requestedRecord.system_revision_id} /> : <TaskComputePrompt applicationId={applicationId} revisionId={requestedRevision ?? undefined} label={activeResultTab === 'pcf' ? t('task.pcf') : activeResultTab === 'cbam' ? t('task.cbam') : activeResultTab === 'organization-lifecycle' ? t('task.organization') : t('task.mfa')} />}</section> : null}
      {!snapshots.isLoading && !error && requestedMissing ? <ErrorState error={new Error(t('results.unknownSnapshot'))} /> : null}
      {invalidResultView ? <section className="section-panel"><InvalidReferencesAlert
        references={[{ key: 'view', label: t('results.view'), requested: requestedResultTab }]}
        note={t('results.invalidView')}
      /></section> : null}
      {!invalidResultView && selected ? (
        <>
          {activeResultTab === 'organization-ghg' ? <div className="analysis-context">{t('results.orgContext')}</div> : null}
          <section className="section-panel result-workspace">
            <AnalysisTabs singleTask={declaredViews !== undefined} allowedKeys={allowedViews} activeTab={activeResultTab} onChange={(key) => {
              const next = new URLSearchParams(searchParams);
              next.set('view', key);
              setSearchParams(next, { replace: true });
            }}>
              <Tabs.TabPane key="mfa" title={t('task.mfa')}>
                {solvedMfa.isLoading ? <LoadingState rows={6} /> : null}
                {solvedMfa.isError ? <ErrorState error={solvedMfa.error} onRetry={() => solvedMfa.refetch()} /> : null}
                {!solvedMfa.isLoading && !solvedMfa.isError && selectedMfaSeriesId ? <>
                  {solvedMfa.data && solvedMfa.data.series.filter((item) => item.is_mass).length > 1 ? <div className="result-series-picker"><label htmlFor="mfa-series-select">{t('results.massSeries')}</label><Select id="mfa-series-select" value={selectedMfaSeriesId} onChange={setSelectedMfaSeriesId} options={solvedMfa.data.series.filter((item) => item.is_mass).map((item) => ({ label: `${item.unit_group_label} · ${item.unit}`, value: item.series_id }))} /></div> : null}
                  {solvedMfa.data ? <MfaResultPanel result={solvedMfa.data} seriesId={selectedMfaSeriesId} snapshotId={selected.id} /> : null}
                </> : null}
                {!solvedMfa.isLoading && !solvedMfa.isError && !selectedMfaSeriesId ? <EmptyState description={t('results.noMass')} /> : null}
              </Tabs.TabPane>
              <Tabs.TabPane key="lcia" title="LCIA">
                {lciaIndicators.length ? <Table rowKey="_row_key" pagination={false} data={lciaIndicators} columns={[
                  { title: '影响指标', render: (_, item) => item.indicator_en ?? item.canonical_indicator_key ?? '未命名指标' },
                  { title: '结果', align: 'right', render: (_, item) => <span className="tabular">{formatNumber(item.value, { maximumSignificantDigits: 6 })}</span> },
                  { title: '单位', render: (_, item) => item.indicator_unit ?? item.unit ?? '—' },
                  { title: '方法', render: (_, item) => item.method_en ?? item.method ?? '—' },
                ]} /> : <EmptyState description="该快照没有 LCIA 指标；运行时需显式选择算法层支持的方法。" />}
              </Tabs.TabPane>
              <Tabs.TabPane key="spatial" title="园区">
                <SpatialAggregatePanel
                  boundaries={parkBoundaries}
                  selectedBoundaryId={selectedSpatialBoundaryId}
                  onBoundaryChange={setSelectedSpatialBoundaryId}
                  selectedSeriesId={selectedSpatialSeriesId}
                  onSeriesChange={setSelectedSpatialSeriesId}
                  result={spatialAggregate.data}
                  isLoading={boundaries.isLoading || spatialAggregate.isLoading}
                  error={boundaries.error || spatialAggregate.error}
                  onRetry={() => { boundaries.refetch(); spatialAggregate.refetch(); }}
                  chart={spatialAggregateChart.data}
                  chartIsLoading={spatialAggregateChart.isLoading}
                  chartError={spatialAggregateChart.error}
                  onChartRetry={() => spatialAggregateChart.refetch()}
                />
              </Tabs.TabPane>
              <Tabs.TabPane key="spatial-energy" title="园区能源">
                <SpatialEnergyPanel
                  result={spatialEnergy.data}
                  isLoading={spatialEnergy.isLoading}
                  error={spatialEnergy.error}
                  onRetry={() => spatialEnergy.refetch()}
                  selectedSeriesId={selectedSpatialEnergySeriesId}
                  onSeriesChange={setSelectedSpatialEnergySeriesId}
                  chart={spatialEnergyChart.data}
                  chartIsLoading={spatialEnergyChart.isLoading}
                  chartError={spatialEnergyChart.error}
                  onChartRetry={() => spatialEnergyChart.refetch()}
                  ready={Boolean(selectedEnergy && selectedSpatialBoundaryId)}
                />
              </Tabs.TabPane>
              <Tabs.TabPane key="distribution" title="供应地图">
                <SpatialDistributionPanel
                  methodPackages={distributionMethodPackages}
                  selectedMethodPackageRef={selectedDistributionMethodRef}
                  onMethodPackageChange={setSelectedDistributionMethodRef}
                  selectedScenarioId={selectedDistributionScenarioId}
                  onScenarioChange={setSelectedDistributionScenarioId}
                  result={spatialDistribution.data}
                  isLoading={methodPackages.isLoading || spatialDistribution.isLoading}
                  error={methodPackages.error || spatialDistribution.error}
                  onRetry={() => { methodPackages.refetch(); spatialDistribution.refetch(); }}
                  chart={spatialDistributionChart.data}
                  chartIsLoading={spatialDistributionChart.isLoading}
                  chartError={spatialDistributionChart.error}
                  onChartRetry={() => spatialDistributionChart.refetch()}
                />
              </Tabs.TabPane>
              <Tabs.TabPane key="energy" title="能源">
                {energyResults.isLoading ? <LoadingState rows={6} /> : null}
                {energyResults.isError ? <ErrorState error={energyResults.error} onRetry={() => energyResults.refetch()} /> : null}
                {!energyResults.isLoading && !energyResults.isError && selectedEnergy ? <EnergyCarrierResultPanel record={selectedEnergy} /> : null}
                {!energyResults.isLoading && !energyResults.isError && !selectedEnergy ? <Alert type="info" title="尚未生成能源载体结果" content="能源分析必须绑定精确 MJ Flow 回执或物性换算回执；本页不会从质量 Flow、名称或单位字符串推断能源结果。" /> : null}
              </Tabs.TabPane>
              <Tabs.TabPane key="period-energy" title="跨期能源">
                <PeriodEnergyTrendPanel
                  applicationId={applicationId}
                  snapshots={snapshots.data ?? []}
                  enabled={activeResultTab === 'period-energy'}
                />
              </Tabs.TabPane>
              <Tabs.TabPane key="pcf" title={t('task.pcf')}>
                {pcfMethod.invalid ? <InvalidReferencesAlert references={[{ label: t('pcf.methodPackage'), requested: pcfMethod.requested, key: 'pcf-method' }]} note={t('results.pcfUnknownMethod')} /> : null}
                <ProductCarbonFootprintPanel
                  snapshotId={selected.id}
                  processNodes={processDisplayNodes({
                    workspaceNodes: resultWorkspace.data?.process_graph?.nodes ?? [],
                    exchanges: [...selected.scaled_elementary_exchanges, ...selected.scaled_technosphere_exchanges],
                    mfaNodes: solvedMfa.data?.series.flatMap((item) => item.nodes) ?? [],
                    backgroundReceipts: selected.provider_receipt.project_background_process_receipts,
                    backgroundLabel: t('pcf.backgroundProcess'),
                  })}
                  methodPackages={pcfMethodPackages}
                  selectedMethodPackageRef={pcfMethod.value}
                  onMethodPackageChange={pcfMethod.select}
                  result={productCarbonFootprint.data}
                  isLoading={methodPackages.isLoading || pcfMethod.pending || productCarbonFootprint.isLoading}
                  error={methodPackages.error || (!explicitPcfMethod && pcfResolved.error) || (pcfMethod.invalid ? null : productCarbonFootprint.error)}
                  onRetry={() => { methodPackages.refetch(); pcfResolved.refetch(); productCarbonFootprint.refetch(); }}
                  chart={productCarbonFootprintChart.data}
                  chartIsLoading={productCarbonFootprintChart.isLoading}
                  chartError={productCarbonFootprintChart.error}
                  onChartRetry={() => productCarbonFootprintChart.refetch()}
                />
              </Tabs.TabPane>
              <Tabs.TabPane key="climate" title="部分背景气候">
                {selected.native_background_climate ? <NativeClimatePanel envelope={selected.native_background_climate} snapshotId={selected.id} /> : <TaskComputePrompt applicationId={applicationId} revisionId={selected.system_revision_id} label="气候结果" />}
              </Tabs.TabPane>
              <Tabs.TabPane key="carbon" title="能源碳管理">
                <CarbonManagementPanel
                  methodPackages={carbonMethodPackages}
                  selectedMethodPackageRef={selectedCarbonMethodRef}
                  onMethodPackageChange={setSelectedCarbonMethodRef}
                  result={carbonManagement.data}
                  isLoading={methodPackages.isLoading || carbonManagement.isLoading}
                  error={methodPackages.error || carbonManagement.error}
                  onRetry={() => { methodPackages.refetch(); carbonManagement.refetch(); }}
                  chart={carbonManagementChart.data}
                  chartIsLoading={carbonManagementChart.isLoading}
                  chartError={carbonManagementChart.error}
                  onChartRetry={() => carbonManagementChart.refetch()}
                  hasEnergyResult={Boolean(selectedEnergy)}
                />
              </Tabs.TabPane>
              <Tabs.TabPane key="organization-ghg" title="组织清单">
                <OrganizationGhgInventoryPanel
                  applicationId={applicationId}
                  snapshots={snapshots.data ?? []}
                  organizationMethods={organizationGhgMethods}
                  formalOrganizationMethods={formalOrganizationGhgMethods}
                  pcfMethods={organizationPcfMethods}
                  carbonMethods={organizationCarbonMethods}
                  provinceMethods={provinceElectricityMethods}
                  enabled={activeResultTab === 'organization-ghg'}
                  packagesLoading={methodPackages.isLoading}
                  packagesError={methodPackages.error}
                  onPackagesRetry={() => methodPackages.refetch()}
                />
              </Tabs.TabPane>
              <Tabs.TabPane key="organization-period" title="组织期间清单">
                {!organizationPeriodMethod ? <EmptyState description="当前项目尚未绑定组织期间方法。" /> : !hasClimateAnswer(selected) ? <TaskComputePrompt applicationId={applicationId} revisionId={selected.system_revision_id} label="组织碳核算" /> : <OrganizationPeriodPanel applicationId={applicationId!} snapshot={selected} method={organizationPeriodMethod} />}
              </Tabs.TabPane>
              <Tabs.TabPane key="organization-lifecycle" title={t('org.title')}>
                {!organizationLifecycleMethod ? <EmptyState description={t('results.noOrgMethod')} /> : !hasClimateAnswer(selected) ? <TaskComputePrompt applicationId={applicationId} revisionId={selected.system_revision_id} label={t('task.organization')} /> : <OrganizationLifecyclePanel applicationId={applicationId!} snapshot={selected} method={organizationLifecycleMethod} methodPackages={methodPackages.data ?? []} />}
              </Tabs.TabPane>
              <Tabs.TabPane key="cbam" title={t('task.cbam')}>
                {!showCbamTrial && cbamPartialReviewMethod ? <CbamPartialReviewPanel applicationId={applicationId!} snapshot={selected} snapshots={snapshots.data ?? []} method={cbamPartialReviewMethod} boundaries={cbamTrialBoundaries} methodPackages={methodPackages.data ?? []} /> : null}
                {showCbamTrial || !cbamPartialReviewMethod ? <CbamRuleTrialPanel applicationId={applicationId} snapshot={selected} snapshots={snapshots.data ?? []} simpleMethods={cbamMethods.simple} complexMethods={cbamMethods.complex} boundaryRequiredFor={cbamBoundaryRequiredFor} cbamBoundaries={cbamTrialBoundaries} boundariesLoading={boundaries.isLoading} boundariesError={boundaries.error} onBoundariesRetry={() => boundaries.refetch()} enabled={activeResultTab === 'cbam'} packagesLoading={methodPackages.isLoading} packagesError={methodPackages.error} onPackagesRetry={() => methodPackages.refetch()} /> : null}
              </Tabs.TabPane>
              <Tabs.TabPane key="scenario" title="情景">
                {comparisonRuns.isError ? <ErrorState error={comparisonRuns.error} onRetry={() => comparisonRuns.refetch()} /> : lineageComparisons.length ? lineageComparisons.map((run) => (
                  <button type="button" className="analysis-result-row" key={run.id} onClick={() => navigate(`/comparison-runs/${run.id}`)}><IconFile aria-hidden="true" /><span><strong>情景比较结果</strong><small>{formatDate(run.created_at)} · {run.scenario_results.length} 个情景</small></span></button>
                )) : <EmptyState description="当前 snapshot 尚未进入情景比较；这里只显示精确引用该 snapshot 的比较运行。" />}
              </Tabs.TabPane>
            </AnalysisTabs>
          </section>
          <Drawer className="audit-drawer" width={560} visible={auditVisible} onCancel={() => setAuditVisible(false)} footer={null} title="求解与快照证据" unmountOnExit>
            <SnapshotContext snapshot={selected} />
            <Descriptions column={1} size="small" border data={[
              { label: 'Snapshot ID', value: <CopyableValue value={selected.id} compact={false} /> },
              { label: 'Revision ID', value: <CopyableValue value={selected.system_revision_id} compact={false} /> },
              { label: 'Solve hash', value: <CopyableValue value={selected.solve_hash} compact={false} /> },
              { label: 'Content hash', value: <CopyableValue value={selected.content_sha256} compact={false} /> },
              { label: '数据 release', value: selected.database_release },
              { label: '求解器', value: selected.solver_version },
              ...(selectedEnergy ? [
                { label: 'Energy result ID', value: <CopyableValue value={selectedEnergy.id} compact={false} /> },
                { label: 'Energy request hash', value: <CopyableValue value={selectedEnergy.request_sha256} compact={false} /> },
                { label: 'Energy content hash', value: <CopyableValue value={selectedEnergy.content_sha256} compact={false} /> },
              ] : []),
              ...(productCarbonFootprint.data ? [
                { label: 'PCF method package', value: <CopyableValue value={productCarbonFootprint.data.method_package.reference} compact={false} /> },
                { label: 'PCF method hash', value: <CopyableValue value={productCarbonFootprint.data.method_package.content_sha256} compact={false} /> },
                { label: 'PCF snapshot hash', value: <CopyableValue value={productCarbonFootprint.data.source_snapshot.content_sha256} compact={false} /> },
                { label: 'PCF content hash', value: <CopyableValue value={productCarbonFootprint.data.content_sha256} compact={false} /> },
              ] : []),
              ...(carbonManagement.data ? [
                { label: 'Carbon method package', value: <CopyableValue value={carbonManagement.data.method_package.reference} compact={false} /> },
                { label: 'Carbon method hash', value: <CopyableValue value={carbonManagement.data.method_package.content_sha256} compact={false} /> },
                { label: 'Carbon content hash', value: <CopyableValue value={carbonManagement.data.content_sha256} compact={false} /> },
              ] : []),
              ...(spatialAggregate.data ? [
                { label: 'Park boundary hash', value: <CopyableValue value={parkBoundaries.find((item) => item.id === selectedSpatialBoundaryId)?.content_sha256} compact={false} /> },
                { label: 'Spatial result hash', value: <CopyableValue value={spatialAggregate.data.content_sha256} compact={false} /> },
                { label: 'Park spatial hash', value: <CopyableValue value={spatialAggregate.data.park.spatial_unit.content_sha256} compact={false} /> },
              ] : []),
              ...(spatialEnergy.data ? [
                { label: 'Spatial energy hash', value: <CopyableValue value={spatialEnergy.data.content_sha256} compact={false} /> },
                { label: 'Spatial energy source hash', value: <CopyableValue value={spatialEnergy.data.source_energy_result.result_content_sha256} compact={false} /> },
              ] : []),
              ...(spatialDistribution.data ? [
                { label: 'Distribution method package', value: <CopyableValue value={spatialDistribution.data.method_package.ref} compact={false} /> },
                { label: 'Distribution method hash', value: <CopyableValue value={spatialDistribution.data.method_package.content_sha256} compact={false} /> },
                { label: 'Distribution result hash', value: <CopyableValue value={spatialDistribution.data.content_sha256} compact={false} /> },
                { label: 'Destination spatial hash', value: <CopyableValue value={spatialDistribution.data.destination.spatial_unit.content_sha256} compact={false} /> },
              ] : []),
            ]} />
            <h3 className="audit-heading">Provider receipt</h3>
            <pre className="audit-json">{JSON.stringify(selected.provider_receipt, null, 2)}</pre>
            {selectedEnergy ? <><h3 className="audit-heading">Energy issues</h3><pre className="audit-json">{JSON.stringify(selectedEnergy.result.issues, null, 2)}</pre></> : null}
            {productCarbonFootprint.data ? <>
              <h3 className="audit-heading">PCF audit</h3>
              <pre className="audit-json">{JSON.stringify(productCarbonFootprint.data.audit, null, 2)}</pre>
              <h3 className="audit-heading">PCF provenance</h3>
              <pre className="audit-json">{JSON.stringify(productCarbonFootprint.data.provenance, null, 2)}</pre>
              <h3 className="audit-heading">PCF contribution receipt</h3>
              <pre className="audit-json">{JSON.stringify(productCarbonFootprint.data.contribution_analysis, null, 2)}</pre>
            </> : null}
            {carbonManagement.data ? <><h3 className="audit-heading">Carbon management audit</h3><pre className="audit-json">{JSON.stringify(carbonManagement.data.audit, null, 2)}</pre></> : null}
            {spatialAggregate.data ? <><h3 className="audit-heading">Spatial aggregate audit</h3><pre className="audit-json">{JSON.stringify(spatialAggregate.data.audit, null, 2)}</pre></> : null}
            {spatialEnergy.data ? <><h3 className="audit-heading">Spatial energy audit</h3><pre className="audit-json">{JSON.stringify(spatialEnergy.data.audit, null, 2)}</pre></> : null}
            {spatialDistribution.data ? <><h3 className="audit-heading">Spatial distribution audit</h3><pre className="audit-json">{JSON.stringify(spatialDistribution.data.audit, null, 2)}</pre></> : null}
          </Drawer>
        </>
      ) : null}
    </main>
  );
}
