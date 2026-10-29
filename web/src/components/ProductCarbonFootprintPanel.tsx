import { Alert, Button, InputNumber, Radio, Select, Table } from '@arco-design/web-react';
import { IconExpand } from '@arco-design/web-react/icon';
import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { DimensionGrouping, MethodCoverageGap, PcfBasisRequest, ProductCarbonFootprint, ProjectWorkspace } from '../api/types';
import type { MessageKey } from '../i18n';
import { CalculationTarget } from './CalculationTarget';
import { useI18n } from '../i18n';
import { MetricCard } from './ui/MetricCard';
import { EmptyState, ErrorState, LoadingState } from './ui/States';
import { ResultHeaderActions, ResultExportMenu, ResultDetails } from './ResultHeaderActions';
import { ContributionChart, processName } from './ContributionChart';
import { UserScopeGrouping } from './UserScopeGrouping';
import { TagResultPanel } from './TagResultPanel';

interface MethodPackageOption {
  reference: string;
  label: string;
}

interface ProductCarbonFootprintPanelProps {
  workspace?: ProjectWorkspace;
  applicationId: string;
  revisionId: string;
  snapshotId: string;
  processNodes?: Array<Record<string, unknown>>;
  exchangeNames?: Record<string, string>;
  methodPackages: MethodPackageOption[];
  selectedMethodPackageRef: string;
  onMethodPackageChange: (reference: string) => void;
  basis: PcfBasisRequest;
  onBasisChange: (basis: PcfBasisRequest) => void;
  result: ProductCarbonFootprint | undefined;
  isLoading: boolean;
  error: unknown;
  onRetry: () => void;
  chart: Blob | undefined;
  chartIsLoading: boolean;
  chartError: unknown;
  onChartRetry: () => void;
}

type ArtifactAction = 'excel' | 'report' | 'print';

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

type Translate = ReturnType<typeof useI18n>['t'];

/** Engine-facing enum values that would otherwise reach a Chinese page verbatim. An unknown value
 * falls back to a generic label plus the raw token in the collapsible detail, never a guess. */
const EXECUTION_STATUS_KEYS: Record<string, MessageKey> = {
  executed_full: 'pcf.executionStatus.executed_full',
  executed_partial: 'pcf.executionStatus.executed_partial',
  no_weighted_contributions: 'pcf.executionStatus.no_weighted_contributions',
};

const GAP_CODE_KEYS: Record<string, MessageKey> = {
  METHOD_RULE_NO_WEIGHTED_CONTRIBUTION: 'pcf.gap.METHOD_RULE_NO_WEIGHTED_CONTRIBUTION',
  METHOD_RULE_TARGET_NOT_FOUND: 'pcf.gap.METHOD_RULE_TARGET_NOT_FOUND',
  METHOD_RULE_TARGET_AMBIGUOUS: 'pcf.gap.METHOD_RULE_TARGET_AMBIGUOUS',
  METHOD_RULE_IDENTITY_INCONSISTENT: 'pcf.gap.METHOD_RULE_IDENTITY_INCONSISTENT',
};

const INDICATOR_NAME_KEYS: Record<string, MessageKey> = {
  'climate change': 'pcf.indicatorName.climateChange',
  climate: 'pcf.indicatorName.climateChange',
  climate_change: 'pcf.indicatorName.climateChange',
  adp: 'pcf.indicatorName.adp',
};

/** Render a user method's own (non-Scope) category rollup from the frozen execution plan. A category
 * with no weighted value shows as a gap, never as zero, and the unattributed / excluded / pending
 * buckets are surfaced so the grouping reconciles against the total instead of implying completeness. */
function DimensionGroupingSection({ grouping, formatNumber, t, flowLabel }: {
  grouping: DimensionGrouping;
  formatNumber: (value: number) => string;
  t: Translate;
  flowLabel: (id: string) => string;
}) {
  const agg = grouping.grouping;
  const dims = Object.entries(agg.dimensions);
  return <section className="pcf-result__dimension-grouping" aria-label={t('pcf.dimGroupTitle')}>
    <div className="section-heading"><h3>{t('pcf.dimGroupTitle')}</h3></div>
    <p className="result-coverage-note">{grouping.reconciled ? t('pcf.dimGroupReconciled') : t('pcf.dimGroupUnreconciled')}</p>
    {dims.map(([dimId, dim]) => <div className="pcf-result__dimension" key={dimId}>
      <h4>{dim.name || <span className="tech-id">{dimId}</span>}</h4>
      <Table rowKey="id" pagination={false} data={dim.categories}
        columns={[
          { title: t('pcf.dimGroupCategory'), render: (_: unknown, row) => row.name || row.id },
          { title: t('pcf.dimGroupValue'), align: 'right', width: 160, render: (_: unknown, row) => <span className="tabular">{row.subtotal === null ? '—' : `${formatNumber(row.subtotal)} ${agg.indicator_unit}`}</span> },
          { title: t('pcf.dimGroupTerms'), align: 'right', width: 100, render: (_: unknown, row) => row.term_count },
          { title: t('pcf.dimGroupMissing'), align: 'right', width: 100, render: (_: unknown, row) => row.missing_count },
        ]} />
      <dl className="pcf-result__facts">
        <div><dt>{t('pcf.dimGroupUnattributed')}</dt><dd className="tabular">{`${formatNumber(dim.unattributed.subtotal)} ${agg.indicator_unit}`} ({dim.unattributed.term_count})</dd></div>
      </dl>
    </div>)}
    <dl className="pcf-result__facts">
      <div><dt>{t('pcf.dimGroupExcluded')}</dt><dd className="tabular">{`${formatNumber(agg.excluded.value)} ${agg.excluded.unit}`} ({agg.excluded.term_count})</dd></div>
      <div><dt>{t('pcf.dimGroupTotal')}</dt><dd className="tabular">{`${formatNumber(agg.known_total)} ${agg.indicator_unit}`} ({agg.known_term_count})</dd></div>
      {agg.missing_value.count ? <div><dt>{t('pcf.dimGroupMissingPaths', { count: agg.missing_value.count })}</dt><dd>{(agg.missing_value.source_keys ?? []).map(flowLabel).join('、')}</dd></div> : null}
      {(grouping.uncovered_exchange_ids?.length ?? 0) > 0 ? <div><dt>{t('pcf.groupingUnattributed', { count: grouping.uncovered_exchange_ids.length })}</dt><dd>{grouping.uncovered_exchange_ids.map(flowLabel).join('、')}</dd></div> : null}
    </dl>
    <details className="frozen-input-identity"><summary>{t('pcf.dimGroupDetail')}</summary>
      <pre className="audit-json">{JSON.stringify(grouping, null, 2)}</pre>
    </details>
  </section>;
}

/** The 结果口径 toggle: a pure read-side re-expression of the frozen solve, never a re-calculation.
 * Only the total and per-reference-output bases are offered; per-product needs a supported mass
 * reference unit, so an incompatible reference output keeps the total and disables the toggle
 * with a reason rather than silently guessing a denominator. */
function ResultBasisControl({ basis, onChange, referenceUnit, productName, t }: {
  basis: PcfBasisRequest;
  onChange: (basis: PcfBasisRequest) => void;
  referenceUnit: string;
  productName?: string;
  t: Translate;
}) {
  const supportedUnits = ['kg', 't'] as const;
  const intensitySupported = (supportedUnits as readonly string[]).includes(referenceUnit);
  const isIntensity = basis.result_basis === 'per_reference_output';
  const toIntensity = () => onChange({ result_basis: 'per_reference_output',
    base_amount: basis.base_amount ?? 1,
    base_unit: basis.base_unit ?? (intensitySupported ? referenceUnit as 'kg' | 't' : 'kg') });
  return <div className="pcf-result__basis" role="group" aria-label={t('pcf.resultBasis')}>
    <span className="pcf-result__basis-label">{t('pcf.resultBasis')}</span>
    <Radio.Group type="button" value={basis.result_basis}
      onChange={(next) => (next === 'per_reference_output' ? toIntensity() : onChange({ result_basis: 'total' }))}>
      <Radio value="total">{t('pcf.basisTotal')}</Radio>
      <Radio value="per_reference_output" disabled={!intensitySupported}>{t('pcf.basisIntensity')}</Radio>
    </Radio.Group>
    {isIntensity ? <span className="pcf-result__basis-base">
      {t('pcf.basisPer')}
      <InputNumber min={1} value={basis.base_amount} style={{ width: 120, margin: '0 8px' }}
        onChange={(value) => onChange({ result_basis: 'per_reference_output',
          base_amount: typeof value === 'number' && value > 0 ? value : 1,
          base_unit: basis.base_unit ?? referenceUnit as 'kg' | 't' })} />
      <Select value={basis.base_unit} style={{ width: 90 }}
        onChange={(value: 'kg' | 't') => onChange({ result_basis: 'per_reference_output',
          base_amount: basis.base_amount ?? 1, base_unit: value })}
        options={[{ label: 'kg', value: 'kg' }, { label: 't', value: 't' }]} />
    </span> : null}
    {isIntensity ? <p className="pcf-result__basis-denominator">{productName
      ? t('pcf.basisDenominator', { amount: basis.base_amount ?? 1, unit: basis.base_unit ?? referenceUnit, product: productName })
      : t('pcf.basisDenominatorUnnamed', { amount: basis.base_amount ?? 1, unit: basis.base_unit ?? referenceUnit })}</p> : null}
    {!intensitySupported ? <p className="helper-text">{t('pcf.basisDisabled')}</p> : null}
    <p className="result-coverage-note">{t('pcf.basisHint')}</p>
  </div>;
}

export function ProductCarbonFootprintPanel({
  workspace,
  applicationId,
  revisionId,
  snapshotId,
  processNodes = [],
  exchangeNames = {},
  methodPackages,
  selectedMethodPackageRef,
  onMethodPackageChange,
  basis,
  onBasisChange,
  result,
  isLoading,
  error,
  onRetry,
  chart,
  chartIsLoading,
  chartError,
  onChartRetry,
}: ProductCarbonFootprintPanelProps) {
  const { t, formatNumber: formatLocaleNumber } = useI18n();
  const formatNumber = (value: number) => formatLocaleNumber(value, { maximumSignificantDigits: 8 });
  // Gap and coverage lists name the flow the reader set the rule on; the raw exchange id stays in
  // the collapsible identity detail instead of occupying the Chinese reading surface.
  const flowLabel = (id: string) => exchangeNames[id] || id;
  const referenceProductName = (() => {
    const uuid = result?.functional_unit.reference_flow_uuid;
    if (!uuid || !workspace) return undefined;
    const names = [...new Set(workspace.fields.filter(field => field.reference_product
      && field.flow_uuid === uuid).map(field => field.label))];
    return names.length === 1 ? names[0] : undefined;
  })();
  const chartUrl = useObjectUrl(chart);
  const [artifactAction, setArtifactAction] = useState<ArtifactAction | null>(null);
  const [artifactError, setArtifactError] = useState<Error | null>(null);
  const [failedAction, setFailedAction] = useState<ArtifactAction | null>(null);

  const runArtifactAction = async (action: ArtifactAction) => {
    if (artifactAction) return;
    setArtifactError(null);
    setFailedAction(null);
    let reportWindow: Window | null = null;
    if (action !== 'excel') {
      reportWindow = window.open('about:blank', '_blank');
      if (!reportWindow) {
        setArtifactError(new Error(t('pcf.popupBlocked')));
        setFailedAction(action);
        return;
      }
      reportWindow.opener = null;
    }
    setArtifactAction(action);
    try {
      const blob = action === 'excel'
        ? await api.productCarbonFootprintExport(snapshotId, selectedMethodPackageRef, basis)
        : await api.productCarbonFootprintReport(snapshotId, selectedMethodPackageRef, basis);
      if (typeof URL.createObjectURL !== 'function') throw new Error(t('pcf.fileOpenFailed'));
      const url = URL.createObjectURL(blob);
      if (action === 'excel') {
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = `product-carbon-footprint-${snapshotId}.xlsx`;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        URL.revokeObjectURL(url);
      } else if (reportWindow) {
        if (action === 'print') {
          reportWindow.addEventListener('load', () => reportWindow?.print(), { once: true });
        }
        reportWindow.location.href = url;
        window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
      }
    } catch (requestError) {
      reportWindow?.close();
      setArtifactError(requestError instanceof Error ? requestError : new Error(t('pcf.fileFailed')));
      setFailedAction(action);
    } finally {
      setArtifactAction(null);
    }
  };

  const methodSelector = (
    <div className="pcf-result__method">
      <label htmlFor="pcf-method-package">{t('pcf.methodPackage')}</label>
      <Select id="pcf-method-package" aria-label={t('pcf.methodPackage')} value={selectedMethodPackageRef || undefined}
        placeholder={t('pcf.selectMethod')} onChange={onMethodPackageChange}
        disabled={Boolean(artifactAction)} options={methodPackages.map(item => ({ label: item.label, value: item.reference }))} />
    </div>
  );
  if (isLoading) return <>{methodSelector}<LoadingState rows={7} /></>;
  if (error) return <>{methodSelector}<ErrorState error={error} onRetry={onRetry} /></>;
  if (!methodPackages.length) {
    return <EmptyState description={t('pcf.noMethod')} />;
  }
  if (!result) return <>{methodSelector}<EmptyState description={t('pcf.selectPrompt')} /></>;

  const characterization = result.data_quality.characterization_coverage;
  const resultLabel = characterization?.status === 'partial' ? t('pcf.factorGapTitle') : result.boundary_claim.coverage === 'foreground_only'
    ? t('pcf.foreground')
    : result.boundary_claim.complete_product_declaration ? t('task.pcf') : t('pcf.covered');
  return (
    <div className="pcf-result">
      <ResultHeaderActions><ResultExportMenu disabled={Boolean(artifactAction)} actions={[
        { key: 'excel', label: t('pcf.excel'), run: () => runArtifactAction('excel') },
        { key: 'report', label: t('pcf.report'), run: () => runArtifactAction('report') },
        { key: 'print', label: t('pcf.print'), run: () => runArtifactAction('print') },
      ]} /></ResultHeaderActions>
      {artifactError ? <ErrorState error={artifactError} onRetry={failedAction ? () => runArtifactAction(failedAction) : undefined} /> : null}
      {characterization?.status === 'partial' ? <section className="pcf-result__factor-gaps">
        <Alert type="warning" title={t('pcf.factorGapTitle')} content={t('pcf.factorGapNotice')} />
        <ul>{characterization.uncharacterized_exchanges.map(item => <li key={item.exchange_id}>
          {exchangeNames[item.exchange_id] || item.flow_name || t('pcf.flowUnavailable')} · {formatNumber(item.amount)} {item.amount_unit}
        </li>)}</ul>
      </section> : null}

      <div className="pcf-result__summary pcf-product-summary">
        <CalculationTarget workspace={workspace} demand={result.functional_unit.reference_flow_uuid
          ? [{ ...result.functional_unit, reference_flow_uuid: result.functional_unit.reference_flow_uuid }] : undefined} />
        <ResultBasisControl basis={basis} onChange={onBasisChange}
          referenceUnit={result.functional_unit.unit} productName={referenceProductName} t={t} />
        <div className="pcf-product-summary__value"><MetricCard
          label={resultLabel}
          value={formatNumber(result.total_footprint.value)}
          unit={result.total_footprint.unit}
        />
        {!result.boundary_claim.complete_product_declaration ? <p className="result-coverage-note">{t(result.boundary_claim.coverage === 'foreground_only' ? 'pcf.coverageForeground' : 'pcf.coverageBackground')}</p> : null}
        </div>
        <dl className="pcf-result__facts">
          <div><dt>{t('pcf.method')}</dt><dd>{result.method_package.lcia_method}</dd></div>
          <div><dt>{t('pcf.boundaryTitle')}</dt><dd>{result.boundary_claim.coverage === 'foreground_only' ? t('pcf.foreground') : t('results.withBackground')}</dd></div>
        </dl>
      </div>



      <section className="pcf-result__hotspots" aria-labelledby="pcf-hotspots-title">
        <div className="section-heading">
          <h3 id="pcf-hotspots-title">{t('pcf.hotspots')}</h3>
        </div>
        {result.contribution_analysis.status === 'unavailable' ? (
          <Alert type="info" title={t('pcf.noHotspots')} content={result.contribution_analysis.coverage === 'total_only'
            ? t('pcf.totalOnly')
            : t('pcf.footprintOnly')} />
        ) : result.contribution_analysis.hotspots.length ? (
          <>
          <ContributionChart result={result} nodes={processNodes} exchangeNames={exchangeNames} />
          <p className="helper-text">{t('pcf.hotspotHint')}</p>
          <Table
            rowKey="_row_key"
            pagination={false}
            scroll={{ x: 560 }}
            data={result.contribution_analysis.hotspots.map((item) => ({ ...item, _row_key: `${item.rank}:${item.process_id}:${item.exchange_id}` }))}
            columns={[
              { title: t('pcf.rank'), dataIndex: 'rank', width: 72 },
              { title: t('pcf.process'), width: 280, render: (_, item) => <div title={exchangeNames[item.exchange_id]}>{processName(item.process_id, processNodes, t('pcf.unnamedProcess'))}{exchangeNames[item.exchange_id] ? <small className="contribution-flow-name">{exchangeNames[item.exchange_id]}</small> : null}</div> },
              { title: t('inventory.columnAmount'), align: 'right', width: 150, render: (_, item) => <span className="tabular">{formatNumber(item.amount)} {item.amount_unit}</span> },
              { title: t('pcf.contribution'), align: 'right', width: 180, render: (_, item) => <span className="tabular">{formatNumber(item.contribution_value)} {item.contribution_unit}</span> },
              { title: t('pcf.share'), align: 'right', width: 120, render: (_, item) => <span className="tabular">{item.share_of_total === null ? '—' : `${formatNumber(item.share_of_total * 100)}%`}</span> },
            ]}
          />
          </>
        ) : <EmptyState description={t('pcf.noRows')} />}
      </section>
      {(() => {
        const grouping = result.contribution_analysis.user_method_grouping;
        if (!grouping) return null;
        const coverage = grouping.coverage;
        // Four distinct reasons, never collapsed into one "not set" bucket: no factor at all, no
        // background link, a true zero factor, and a flow the reader has not classified yet.
        const gapReasons: Array<[MessageKey, string[] | undefined]> = [
          ['pcf.groupingUncharacterized', coverage?.uncharacterized_exchange_ids],
          ['pcf.groupingEngineGap', coverage?.engine_gap_exchange_ids],
          ['pcf.groupingZeroCf', coverage?.zero_cf_exchange_ids],
          ['pcf.groupingUnattributed', coverage?.unattributed_exchange_ids],
        ];
        return <section className="pcf-result__grouping" aria-label={t('pcf.groupingTitle')}>
          <div className="section-heading"><h3>{t('pcf.groupingTitle')}</h3></div>
          {grouping.counts_as_complete_pcf === false ? <Alert type="warning" content={t('pcf.groupingNotComplete')} /> : null}
          <dl className="pcf-result__facts">
            <div><dt>{t('pcf.groupingMode')}</dt><dd>{grouping.grouping_mode === 'path_weighted' ? t('pcf.groupingModePath') : t('pcf.groupingModeExchange')}</dd></div>
            <div><dt>{t('pcf.groupingStatus')}</dt><dd>{t(EXECUTION_STATUS_KEYS[grouping.execution_status] ?? 'pcf.executionStatus.unknown')}
              {EXECUTION_STATUS_KEYS[grouping.execution_status] ? null : <span className="tech-id"> · {grouping.execution_status}</span>}</dd></div>
            {coverage?.attribution_coverage != null ? <div><dt>{t('pcf.groupingCoverage')}</dt><dd>{typeof coverage.attribution_coverage === 'number'
              ? `${formatNumber(coverage.attribution_coverage * 100)}%`
              : t(`pcf.groupingCoverage.${coverage.attribution_coverage}`)}</dd></div> : null}
            {(coverage?.coverage_gaps?.length ?? 0) > 0 ? <div><dt>{t('pcf.groupingCoverageGaps', { count: coverage?.coverage_gaps?.length ?? 0 })}</dt>
              <dd><ul className="pcf-result__gap-list">{coverage?.coverage_gaps?.map((gap: MethodCoverageGap, index: number) => <li key={`${gap.code}:${gap.exchange_id ?? index}`}>
                {t(GAP_CODE_KEYS[gap.code] ?? 'pcf.gap.unknown')}
                {gap.exchange_id ? <span className="pcf-result__gap-flow"> · {flowLabel(gap.exchange_id)}</span> : null}
              </li>)}</ul></dd></div> : null}
            {gapReasons.map(([key, ids]) => ids?.length ? <div key={key}><dt>{t(key, { count: ids.length })}</dt>
              <dd>{ids.map(flowLabel).join('、')}</dd></div> : null)}
          </dl>
          <UserScopeGrouping grouping={grouping.grouping} />
          <details className="frozen-input-identity"><summary>{t('pcf.groupingMethodIdentity')}</summary>
            <pre className="audit-json">{JSON.stringify(grouping.method, null, 2)}</pre>
          </details>
        </section>;
      })()}
      {(() => {
        const dimensionGrouping = result.contribution_analysis.user_method_grouping?.dimension_grouping;
        if (!dimensionGrouping) return null;
        return <DimensionGroupingSection grouping={dimensionGrouping} formatNumber={formatNumber} t={t} flowLabel={flowLabel} />;
      })()}
      <TagResultPanel applicationId={applicationId} revisionId={revisionId} snapshotId={result.source_snapshot.id}
        indicatorKey={result.total_footprint.indicator_key} />
      <ResultDetails><h3>{t('pcf.components')}</h3>
      <div className="pcf-result__chart" role="region" aria-label={t('pcf.chartAria')}>
        <div className="pcf-result__chart-toolbar">
          <strong>{t('pcf.componentTitle')}</strong>
          {chartUrl ? <Button type="text" size="small" icon={<IconExpand />} href={chartUrl} target="_blank" rel="noreferrer">{t('pcf.openChart')}</Button> : null}
        </div>
        {chartIsLoading ? <div className="pcf-result__chart-state"><LoadingState rows={5} /></div> : null}
        {chartError ? <div className="pcf-result__chart-state"><ErrorState error={chartError} onRetry={onChartRetry} /></div> : null}
        {!chartIsLoading && !chartError && chartUrl ? <img src={chartUrl} alt={t('pcf.chartAlt')} /> : null}
      </div>

      {result.component_results.length ? (
        <Table
          rowKey="indicator_key"
          pagination={false}
          data={result.component_results}
          columns={[
            { title: t('pcf.indicator'), render: (_, item) => <span>{t(INDICATOR_NAME_KEYS[item.indicator_key] ?? 'pcf.indicatorRaw')}
              {INDICATOR_NAME_KEYS[item.indicator_key] ? null : <span className="tech-id"> · {item.indicator_key}</span>}</span> },
            { title: t('pcf.result'), align: 'right', render: (_, item) => <span className="tabular">{formatNumber(item.value)}</span> },
            { title: t('pcf.unit'), dataIndex: 'unit' },
          ]}
        />
      ) : <EmptyState description={t('pcf.noComponents')} />}
      </ResultDetails>
    </div>
  );
}
