import { Alert, Button, Select, Table } from '@arco-design/web-react';
import { IconDownload, IconExpand, IconFile, IconPrinter } from '@arco-design/web-react/icon';
import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { ProductCarbonFootprint } from '../api/types';
import { useI18n } from '../i18n';
import { MetricCard } from './ui/MetricCard';
import { EmptyState, ErrorState, LoadingState } from './ui/States';
import { StatusBadge } from './ui/StatusBadge';
import { ContributionChart, processName } from './ContributionChart';

interface MethodPackageOption {
  reference: string;
  label: string;
}

interface ProductCarbonFootprintPanelProps {
  snapshotId: string;
  processNodes?: Array<Record<string, unknown>>;
  methodPackages: MethodPackageOption[];
  selectedMethodPackageRef: string;
  onMethodPackageChange: (reference: string) => void;
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

export function ProductCarbonFootprintPanel({
  snapshotId,
  processNodes = [],
  methodPackages,
  selectedMethodPackageRef,
  onMethodPackageChange,
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
        ? await api.productCarbonFootprintExport(snapshotId, selectedMethodPackageRef)
        : await api.productCarbonFootprintReport(snapshotId, selectedMethodPackageRef);
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

  const functionalUnit = `${formatNumber(result.functional_unit.amount)} ${result.functional_unit.unit}`;
  const resultLabel = result.boundary_claim.coverage === 'foreground_only'
    ? t('pcf.foreground')
    : result.boundary_claim.complete_product_declaration ? t('task.pcf') : t('pcf.covered');
  return (
    <div className="pcf-result">
      <div className="pcf-result__head">
        <div>
          <h3>{resultLabel}</h3>
          <p>{t('pcf.summary')}</p>
        </div>
        {methodSelector}
      </div>

      <div className="pcf-result__actions" aria-label={t('pcf.exportAria')}>
        <Button icon={<IconDownload />} loading={artifactAction === 'excel'} disabled={Boolean(artifactAction)} onClick={() => runArtifactAction('excel')}>{t('pcf.excel')}</Button>
        <Button icon={<IconFile />} loading={artifactAction === 'report'} disabled={Boolean(artifactAction)} onClick={() => runArtifactAction('report')}>{t('pcf.report')}</Button>
        <Button icon={<IconPrinter />} loading={artifactAction === 'print'} disabled={Boolean(artifactAction)} onClick={() => runArtifactAction('print')}>{t('pcf.print')}</Button>
      </div>
      {artifactError ? <ErrorState error={artifactError} onRetry={failedAction ? () => runArtifactAction(failedAction) : undefined} /> : null}

      <div className="pcf-result__summary">
        <MetricCard
          label={resultLabel}
          value={formatNumber(result.total_footprint.value)}
          unit={result.total_footprint.unit}
        />
        <dl className="pcf-result__facts">
          <div><dt>{t('pcf.functionalUnit')}</dt><dd>{functionalUnit}</dd></div>
          <div><dt>{t('pcf.method')}</dt><dd>{result.method_package.lcia_method}</dd></div>
          <div><dt>{t('pcf.auditStatus')}</dt><dd><StatusBadge status={result.audit.status} /></dd></div>
        </dl>
      </div>

      {!result.boundary_claim.complete_product_declaration ? (
        <Alert
          type="warning"
          title={t('pcf.boundaryTitle')}
          content={t('pcf.boundaryNote')}
        />
      ) : null}


      <section className="pcf-result__hotspots" aria-labelledby="pcf-hotspots-title">
        <div className="section-heading">
          <h3 id="pcf-hotspots-title">{t('pcf.hotspots')}</h3>
          <StatusBadge status={result.contribution_analysis.status} />
        </div>
        {result.contribution_analysis.status === 'unavailable' ? (
          <Alert type="info" title={t('pcf.noHotspots')} content={result.contribution_analysis.coverage === 'total_only'
            ? t('pcf.totalOnly')
            : t('pcf.footprintOnly')} />
        ) : result.contribution_analysis.hotspots.length ? (
          <>
          <ContributionChart result={result} nodes={processNodes} />
          <p className="helper-text">{t('pcf.hotspotHint')}</p>
          <Table
            rowKey="_row_key"
            pagination={false}
            scroll={{ x: 560 }}
            data={result.contribution_analysis.hotspots.slice(0, 3).map((item) => ({ ...item, _row_key: `${item.rank}:${item.process_id}:${item.exchange_id}` }))}
            columns={[
              { title: t('pcf.rank'), dataIndex: 'rank', width: 72 },
              { title: t('pcf.process'), width: 190, render: (_, item) => processName(item.process_id, processNodes, t('pcf.unnamedProcess')) },
              { title: t('pcf.contribution'), align: 'right', width: 180, render: (_, item) => <span className="tabular">{formatNumber(item.contribution_value)} {item.contribution_unit}</span> },
              { title: t('pcf.share'), align: 'right', width: 120, render: (_, item) => <span className="tabular">{item.share_of_total === null ? '—' : `${formatNumber(item.share_of_total * 100)}%`}</span> },
            ]}
          />
          </>
        ) : <EmptyState description={t('pcf.noRows')} />}
      </section>
      <details className="result-details"><summary>{t('pcf.components')}</summary>
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
            { title: t('pcf.indicator'), dataIndex: 'indicator_key' },
            { title: t('pcf.result'), align: 'right', render: (_, item) => <span className="tabular">{formatNumber(item.value)}</span> },
            { title: t('pcf.unit'), dataIndex: 'unit' },
          ]}
        />
      ) : <EmptyState description={t('pcf.noComponents')} />}
      </details>
    </div>
  );
}
