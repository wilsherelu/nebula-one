import { Alert, Button, Descriptions, Drawer, Select, Tabs } from '@arco-design/web-react';
import { IconExpand, IconInfoCircle } from '@arco-design/web-react/icon';
import { useQuery } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import { useI18n } from '../i18n';
import { useUrlSelection, type InvalidReference } from '../hooks/useUrlSelection';
import type {
  BoundaryDefinition,
  CbamComplexTrialRequest,
  CbamComplexTrialResult,
  CbamTrialRequest,
  CbamTrialResult,
  SolvedSystemSnapshot,
} from '../api/types';
import { CopyableValue } from './ui/CopyableValue';
import { referenceUnit } from './SnapshotContext';
import { MetricCard } from './ui/MetricCard';
import { EmptyState, ErrorState, LoadingState } from './ui/States';
import { InvalidReferencesAlert } from './ui/InvalidReferencesAlert';
import { CbamBoundaryDetails } from './CbamBoundaryDetails';
import { ResultHeaderActions } from './ResultHeaderActions';
import { FrozenReportPanel } from './FrozenReportPanel';

export interface RulePackageOption {
  reference: string;
  label: string;
}

interface Props {
  applicationId: string;
  snapshot: SolvedSystemSnapshot;
  snapshots: SolvedSystemSnapshot[];
  simpleMethods: RulePackageOption[];
  complexMethods: RulePackageOption[];
  /** References of packages whose manifest routes to cbam.trial.v2, which names a frozen boundary. */
  boundaryRequiredFor: string[];
  /** This application's frozen `cbam_trial` boundaries — the only ids a v2 trial may reference. */
  cbamBoundaries: BoundaryDefinition[];
  boundariesLoading: boolean;
  boundariesError: unknown;
  onBoundariesRetry: () => void;
  enabled: boolean;
  packagesLoading: boolean;
  packagesError: unknown;
  onPackagesRetry: () => void;
}

function useObjectUrl(blob: Blob | undefined): string | undefined {
  const [url, setUrl] = useState<string>();
  useEffect(() => {
    if (!blob || typeof URL.createObjectURL !== 'function') {
      setUrl(undefined);
      return undefined;
    }
    const next = URL.createObjectURL(blob);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [blob]);
  return url;
}

export function CbamRuleTrialPanel(props: Props) {
  const { t, formatDate, formatNumber } = useI18n();
  const formatDecimal = (value: string | null | undefined): string =>
    value == null || value.trim() === '' ? '—' : formatNumber(Number(value), { maximumSignificantDigits: 8 });
  const [auditVisible, setAuditVisible] = useState(false);

  const periods = useQuery({
    queryKey: ['periods', props.applicationId],
    queryFn: () => api.periods(props.applicationId),
    enabled: props.enabled,
  });

  const packagesReady = !props.packagesLoading;
  const periodIds = useMemo(() => (periods.data ?? []).map((item) => item.id), [periods.data]);
  const simpleRefs = useMemo(() => props.simpleMethods.map((item) => item.reference), [props.simpleMethods]);
  const complexRefs = useMemo(() => props.complexMethods.map((item) => item.reference), [props.complexMethods]);
  const precursorCandidates = useMemo(() => props.snapshots.filter((item) => item.id !== props.snapshot.id), [props.snapshot.id, props.snapshots]);
  const precursorCandidateIds = useMemo(() => precursorCandidates.map((item) => item.id), [precursorCandidates]);
  const modeOptions = useMemo(() => [
    ...(props.complexMethods.length ? ['complex'] : []),
    ...(props.simpleMethods.length ? ['simple'] : []),
  ], [props.complexMethods.length, props.simpleMethods.length]);

  const mode = useUrlSelection('cbam-tab', modeOptions, { ready: packagesReady });
  const simpleMethod = useUrlSelection('cbam-simple-method', simpleRefs, { ready: packagesReady });
  const complexMethod = useUrlSelection('cbam-complex-method', complexRefs, { ready: packagesReady });
  const precursorMethod = useUrlSelection('cbam-precursor-method', simpleRefs, { ready: packagesReady });
  const period = useUrlSelection('cbam-period', periodIds, { ready: Boolean(periods.data) || Boolean(periods.error) });
  const precursorSnapshot = useUrlSelection('cbam-precursor-snapshot', precursorCandidateIds);

  const isComplex = mode.value !== 'simple';
  const activeMethod = isComplex ? complexMethod : simpleMethod;
  const needsFrozenBoundary = !isComplex && Boolean(activeMethod.value) && props.boundaryRequiredFor.includes(activeMethod.value);
  const snapshotGraphHash = (props.snapshot.provider_receipt?.snapshot_ref as {graph_hash?: string} | undefined)?.graph_hash;
  // a frozen boundary that names a period or a package is only a candidate for that same choice;
  // the request would otherwise be refused for reading one year's dispositions under another name.
  const boundaryCandidates = useMemo(() => props.cbamBoundaries.filter((item) => (
    (!item.period_id || item.period_id === period.value)
    && (!item.method_package_ref || item.method_package_ref === activeMethod.value)
    && (!item.geographic_scope?.graph_sha256 || item.geographic_scope.graph_sha256 === snapshotGraphHash)
  )), [activeMethod.value, period.value, props.cbamBoundaries, snapshotGraphHash]);
  const boundaryCandidateIds = useMemo(() => boundaryCandidates.map((item) => item.id), [boundaryCandidates]);
  const boundary = useUrlSelection('cbam-boundary', boundaryCandidateIds, { ready: !props.boundariesLoading });
  const selectedBoundary = boundaryCandidates.find((item) => item.id === boundary.value);

  const precursorReferencesItself = precursorSnapshot.invalid && precursorSnapshot.requested === props.snapshot.id;
  const invalidReferences = useMemo(() => [
    mode.invalid ? { label: t('cbam.goodsType'), requested: mode.requested, key: 'cbam-tab' } : null,
    simpleMethod.invalid ? { label: t('cbam.simpleMethod'), requested: simpleMethod.requested, key: 'cbam-simple-method' } : null,
    complexMethod.invalid ? { label: t('cbam.complexMethod'), requested: complexMethod.requested, key: 'cbam-complex-method' } : null,
    precursorMethod.invalid ? { label: t('cbam.precursorMethod'), requested: precursorMethod.requested, key: 'cbam-precursor-method' } : null,
    period.invalid ? { label: t('cbam.period'), requested: period.requested, key: 'cbam-period' } : null,
    precursorSnapshot.invalid ? { label: t('cbam.precursorSnapshot'), requested: precursorSnapshot.requested, key: 'cbam-precursor-snapshot' } : null,
    boundary.invalid ? { label: t('cbam.frozenAccountingBoundary'), requested: boundary.requested, key: 'cbam-boundary' } : null,
  ].filter((item): item is InvalidReference => Boolean(item)), [boundary, complexMethod, mode, period, precursorMethod, precursorSnapshot, simpleMethod, t]);

  const selectionsUsable = !invalidReferences.length && !mode.pending;

  const simplePayload = useMemo<CbamTrialRequest>(() => ({
    method_package_ref: simpleMethod.value,
    reporting_period_id: period.value,
    ...(needsFrozenBoundary && boundary.value ? { boundary_definition_id: boundary.value } : {}),
  }), [boundary.value, needsFrozenBoundary, period.value, simpleMethod.value]);
  const complexPayload = useMemo<CbamComplexTrialRequest>(() => ({
    method_package_ref: complexMethod.value,
    reporting_period_id: period.value,
    precursors: [{ solved_snapshot_id: precursorSnapshot.value, method_package_ref: precursorMethod.value }],
  }), [complexMethod.value, period.value, precursorMethod.value, precursorSnapshot.value]);

  const boundaryResolved = !needsFrozenBoundary || Boolean(boundary.value);
  const simpleTrialEnabled = props.enabled && selectionsUsable && !isComplex && boundaryResolved
    && Boolean(simpleMethod.value && period.value);
  const complexTrialEnabled = props.enabled && selectionsUsable && isComplex && Boolean(complexMethod.value && precursorMethod.value && precursorSnapshot.value && period.value);
  const simpleResult = useQuery({
    queryKey: ['cbam-trial', props.snapshot.id, simplePayload],
    queryFn: () => api.cbamTrial(props.snapshot.id, simplePayload),
    enabled: simpleTrialEnabled,
  });
  const complexResult = useQuery({
    queryKey: ['cbam-complex-trial', props.snapshot.id, complexPayload],
    queryFn: () => api.cbamComplexTrial(props.snapshot.id, complexPayload),
    enabled: complexTrialEnabled,
  });
  const result = isComplex ? complexResult.data : simpleResult.data;
  const activeResult = isComplex ? complexResult : simpleResult;
  const activeTrialEnabled = isComplex ? complexTrialEnabled : simpleTrialEnabled;
  const simpleChart = useQuery({
    queryKey: ['cbam-trial-chart', props.snapshot.id, simplePayload],
    queryFn: () => api.cbamTrialChart(props.snapshot.id, simplePayload),
    // the v1 chart renderer refuses a multi-process boundary result, so the request is never made
    enabled: simpleTrialEnabled && !needsFrozenBoundary && Boolean(simpleResult.data),
  });
  const complexChart = useQuery({
    queryKey: ['cbam-complex-trial-chart', props.snapshot.id, complexPayload],
    queryFn: () => api.cbamComplexTrialChart(props.snapshot.id, complexPayload),
    enabled: complexTrialEnabled && Boolean(complexResult.data),
  });
  const activeChart = isComplex ? complexChart : simpleChart;
  const chartUrl = useObjectUrl(activeChart.data);

  if (props.packagesLoading || props.boundariesLoading || periods.isLoading) return <LoadingState rows={7} />;
  if (props.packagesError || props.boundariesError || periods.error) {
    return <ErrorState
      error={props.packagesError || props.boundariesError || periods.error}
      onRetry={() => { props.onPackagesRetry(); props.onBoundariesRetry(); periods.refetch(); }}
    />;
  }
  if (!props.simpleMethods.length && !props.complexMethods.length) {
    return <EmptyState description={t('cbam.noPackage')} />;
  }
  if (!periods.data?.length) {
    return <EmptyState description={t('cbam.noPeriod')} />;
  }
  if (invalidReferences.length) {
    return <>
      <InvalidReferencesAlert references={invalidReferences} />
      {precursorReferencesItself ? <Alert type="info" title={t('cbam.selfPrecursor')} content={t('cbam.selfPrecursorNote')} /> : null}
      <EmptyState description={t('cbam.invalidReference')} />
    </>;
  }

  // Keep the result layout pending while the selected frozen trial is fetched.
  if (mode.pending || period.pending || boundary.pending || activeResult.isLoading) return <LoadingState rows={7} />;

  const complex = result?.schema_version === 'nebula_one.cbam.complex-trial.v1' ? result : undefined;
  const simple = result && result.schema_version !== 'nebula_one.cbam.complex-trial.v1' ? result : undefined;
  const direct = complex?.attributed_emissions.total_direct_component ?? simple?.attributed_emissions.direct;
  const partial = simple?.specific_embedded_emissions.partial_result === true;
  const includedValue = partial ? (simple?.specific_embedded_emissions.partial_value ?? result?.specific_embedded_emissions.value) : result?.specific_embedded_emissions.value;
  const counted = (value: string | null | undefined): string | null =>
    value != null && value.trim() !== '' ? formatDecimal(value) : null;
  // The indirect line is a real business state, never a fabricated zero: a method that only returns
  // direct emissions says so, and a simple trial still waiting on a versioned factor stays "待补".
  const indirectStatus: { value: string; unit?: string } = complex
    ? { value: t('cbam.notIncluded'), unit: t('cbam.directOnly') }
    : simple?.attributed_emissions.indirect == null
      ? { value: t('cbam.notCounted'), unit: t('cbam.noEligibleFactor') }
      : simple.attributed_emissions.indirect.value == null
        ? { value: t('cbam.pendingFactor'), unit: t('cbam.unquantified') }
        : { value: formatDecimal(simple.attributed_emissions.indirect.value), unit: simple.attributed_emissions.indirect.unit ?? undefined };
  const openItemCount = simple?.coverage?.open_items.length ?? 0;

  return (
    <div className="pcf-result cbam-result">
      {!result ? <div className="pcf-result__head">
        <Tabs activeTab={mode.value} onChange={(key) => mode.select(key)} type="capsule">
          {props.simpleMethods.length ? <Tabs.TabPane key="simple" title={t('cbam.simpleMode')} /> : null}
          {props.complexMethods.length ? <Tabs.TabPane key="complex" title={t('cbam.complexMode')} /> : null}
        </Tabs>
      </div> : null}

      {!result ? <div className="cbam-result__selectors">
        <div><label htmlFor="cbam-method">{t('cbam.method')}</label><Select id="cbam-method" value={activeMethod.value} onChange={activeMethod.select} options={(isComplex ? props.complexMethods : props.simpleMethods).map((item) => ({ label: `${t(isComplex ? 'cbam.complexMode' : 'cbam.simpleMode')} · v${item.reference.split('@').at(-1)}`, value: item.reference }))} /></div>
        <div><label htmlFor="cbam-period">{t('cbam.period')}</label><Select id="cbam-period" value={period.value} onChange={period.select} options={periods.data.map((item) => ({ label: `${item.name} · ${item.start_date}—${item.end_date}`, value: item.id }))} /></div>
        {needsFrozenBoundary ? <div><label htmlFor="cbam-boundary">{t('cbam.frozenAccountingBoundary')}</label><Select id="cbam-boundary" value={boundary.value} onChange={boundary.select} options={boundaryCandidates.map((item) => ({ label: `${t('cbam.frozenAccountingBoundary')} · ${formatDate(item.frozen_at ?? item.created_at)}`, value: item.id }))} /></div> : null}
        {isComplex ? <>
          <div><label htmlFor="cbam-precursor-method">{t('cbam.precursorMethod')}</label><Select id="cbam-precursor-method" value={precursorMethod.value} onChange={precursorMethod.select} options={props.simpleMethods.map((item) => ({ label: item.label, value: item.reference }))} /></div>
          <div><label htmlFor="cbam-precursor-snapshot">{t('cbam.precursorSnapshot')}</label><Select id="cbam-precursor-snapshot" value={precursorSnapshot.value} onChange={precursorSnapshot.select} options={precursorCandidates.map((item) => ({ label: `${referenceUnit(item.functional_unit)} · ${formatDate(item.created_at)}`, value: item.id }))} /></div>
        </> : null}
      </div> : null}
      {result ? <div className="result-frozen-summary"><span>{result.goods.aggregated_goods_category}</span><span>{periods.data.find(item => item.id === period.value)?.name}</span><span>{t(isComplex ? 'cbam.complexMode' : 'cbam.simpleMode')} · v{activeMethod.value.split('@').at(-1)}</span></div> : null}

      {isComplex && !props.simpleMethods.length ? <Alert type="warning" title={t('cbam.noPrecursorMethod')} content={t('cbam.noPrecursorMethodNote')} /> : null}
      {isComplex && !precursorSnapshot.value && !precursorReferencesItself ? <Alert type="warning" title={t('cbam.noPrecursorSnapshot')} content={t('cbam.noPrecursorSnapshotNote')} /> : null}
      {needsFrozenBoundary && !boundary.pending && !boundary.value ? <Alert
        type="warning"
        title={t('cbam.noFrozenBoundary')}
        content={<>
          <p>{t('cbam.noFrozenBoundaryNote')}</p>
          <p>{t('cbam.installBoundary')}</p>
        </>}
      /> : null}
      {activeResult.isLoading ? <LoadingState rows={6} /> : null}
      {activeResult.error ? <ErrorState error={activeResult.error} onRetry={() => activeResult.refetch()} /> : null}
      {activeTrialEnabled && !activeResult.isLoading && !activeResult.error && !result ? <Alert
        type="warning"
        title={t('cbam.requestIncomplete')}
        content={activeResult.isPaused ? t('cbam.requestPaused') : t('cbam.requestEmpty')}
        action={<Button size="small" onClick={() => activeResult.refetch()}>{t('cbam.reload')}</Button>}
      /> : null}
      {!activeResult.isLoading && !activeResult.error && result ? <>
        <div className="pcf-result__summary">
          <div className="cbam-headline">
            <MetricCard label={partial ? t('cbam.partialEmbedded') : simple?.attributed_emissions.indirect?.value == null ? t('cbam.directIntensity') : t('cbam.specificEmbedded')}
              value={counted(includedValue) ?? t('cbam.notCalculated')}
              unit={counted(includedValue) ? result.specific_embedded_emissions.unit : undefined} />
            <MetricCard label={t('cbam.directIncluded')}
              value={counted(direct?.value) ?? t('cbam.notCalculated')}
              unit={counted(direct?.value) ? direct?.unit : undefined} />
            <MetricCard label={t('cbam.indirectStatus')} value={indirectStatus.value} unit={indirectStatus.unit} />
          </div>
        </div>
        <p className="result-coverage-note">{partial ? t('cbam.incompleteSubtotal') : t('cbam.notDeclaration')}</p>
        {simple?.schema_version === 'nebula_one.cbam.trial.v2' ? <FrozenReportPanel source={{snapshotId:props.snapshot.id,cbam:simplePayload}} /> : null}
        {activeChart.isLoading ? <div className="pcf-result__chart-state"><LoadingState rows={5} /></div> : null}
        {activeChart.error ? <div className="pcf-result__chart-state"><ErrorState error={activeChart.error} onRetry={() => activeChart.refetch()} /></div> : null}
        {chartUrl ? <div className="pcf-result__chart" role="region" aria-label={t('cbam.chart')}>
          <div className="pcf-result__chart-toolbar"><strong>{complex ? t('cbam.precursorContribution') : t('cbam.directChart')}</strong><Button type="text" size="small" icon={<IconExpand />} href={chartUrl} target="_blank" rel="noreferrer">{t('cbam.openChart')}</Button></div>
          <img src={chartUrl} alt={complex ? t('cbam.complexChartAlt') : t('cbam.simpleChartAlt')} />
        </div> : null}
        <ResultHeaderActions>
          <Button type="text" size="small" icon={<IconInfoCircle />} onClick={() => setAuditVisible(true)}>{t('results.details')}</Button>
        </ResultHeaderActions>
      </> : null}

      <Drawer className="audit-drawer" width="min(680px, 100vw)" visible={auditVisible} onCancel={() => setAuditVisible(false)} footer={null} title={t('results.details')} unmountOnExit>
        {result ? <>
          {openItemCount ? <>
            <h3 className="audit-heading">{t('cbam.openItems')}</h3>
            <ul className="audit-open-items">
              {simple?.coverage?.open_items.map((item) => <li key={`${item.clause}:${item.item}`}>
                <strong>{item.clause}</strong>（{item.state}）：{item.item}——{item.effect}
                {item.gap_ref ? <span className="cbam-result__coverage-ref"> {t('cbam.gapReference', { ref: item.gap_ref })}</span> : null}
              </li>)}
            </ul>
          </> : null}
          {simple?.schema_version === 'nebula_one.cbam.trial.v2' ? <CbamBoundaryDetails result={simple} /> : null}
          <Descriptions column={1} size="small" border data={[
            { label: t('cbam.cnCode'), value: <CopyableValue value={result.goods.cn_code} compact={false} /> },
            { label: t('cbam.auditStatus'), value: result.status },
            { label: t('cbam.activityLevel'), value: `${formatDecimal(result.activity_level.value)} ${result.activity_level.unit}` },
            ...(simple?.coverage ? [{ label: t('cbam.portCount'), value: String(simple.coverage.totals.ports) }] : []),
            ...(complex ? [{ label: t('cbam.precursorContributionLabel'), value: `${formatDecimal(complex.attributed_emissions.precursor_embedded_direct.value)} ${complex.attributed_emissions.precursor_embedded_direct.unit}` }] : []),
            { label: 'Method package', value: <CopyableValue value={result.method_package.ref} compact={false} /> },
            { label: 'Method hash', value: <CopyableValue value={result.method_package.content_sha256} compact={false} /> },
            { label: 'Rule source hash', value: <CopyableValue value={result.method_package.rule_source_sha256} compact={false} /> },
            { label: 'Snapshot hash', value: <CopyableValue value={result.source_snapshot.content_sha256} compact={false} /> },
            ...(selectedBoundary ? [
              { label: t('cbam.frozenAccountingBoundary'), value: selectedBoundary.name },
              { label: 'Boundary definition', value: <CopyableValue value={selectedBoundary.id} compact={false} /> },
              { label: 'Boundary hash', value: <CopyableValue value={selectedBoundary.content_sha256 ?? ''} compact={false} /> },
            ] : []),
            { label: 'Result hash', value: <CopyableValue value={result.content_sha256} compact={false} /> },
          ]} />
          <h3 className="audit-heading">{t('cbam.ruleAudit')}</h3><pre className="audit-json">{JSON.stringify(result.audit, null, 2)}</pre>
          <h3 className="audit-heading">{t('cbam.claimBoundary')}</h3><pre className="audit-json">{JSON.stringify(result.claim_boundary, null, 2)}</pre>
          {complex ? <><h3 className="audit-heading">{t('cbam.precursorEvidence')}</h3><pre className="audit-json">{JSON.stringify(complex.precursors, null, 2)}</pre></> : null}
        </> : <EmptyState description={t('cbam.noAudit')} />}
      </Drawer>
    </div>
  );
}
