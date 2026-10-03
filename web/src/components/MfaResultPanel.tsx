import { Table, Tabs } from '@arco-design/web-react';
import type { SolvedMfaResult } from '../api/types';
import { useI18n } from '../i18n';
import { MetricCard } from './ui/MetricCard';
import { StatusBadge } from './ui/StatusBadge';
import { SankeyViewer } from './SankeyViewer';

export function MfaResultPanel({ result, seriesId, snapshotId }: {
  result: SolvedMfaResult; seriesId: string; snapshotId: string;
}) {
  const { t, formatNumber } = useI18n();
  const series = result.series.find((item) => item.series_id === seriesId);
  if (!series) return null;
  const number = (value: number) => formatNumber(value, { maximumSignificantDigits: 8 });
  return <div className="mfa-result">
    <div className="mfa-summary">
      <MetricCard label={t('mfa.boundaryInput')} value={number(series.totals.boundary_input)} unit={series.unit} />
      <MetricCard label={t('mfa.boundaryOutput')} value={number(series.totals.boundary_output)} unit={series.unit} />
      <div className="mfa-audit-state"><span>{t('mfa.conservation')}</span><StatusBadge status={series.conservation?.status ?? 'unknown'} /><small>{t('mfa.conservationScope')}</small></div>
    </div>
    <Tabs defaultActiveTab="flow">
      <Tabs.TabPane key="flow" title={t('mfa.chart')}>
        {/* The existing mass SVG uses 10px for its smallest labels. Scale only its viewport to 12px. */}
        <SankeyViewer defaultZoom="detail" readableScale={1.2} src={`/api/v1/solved-system-snapshots/${snapshotId}/mfa/sankey.svg?series_id=${encodeURIComponent(seriesId)}`} alt={t('mfa.chartAlt')} />
      </Tabs.TabPane>
      <Tabs.TabPane key="detail" title={t('mfa.details')}>
        <Table<Record<string, unknown> & { _row: number }> rowKey="_row" pagination={{ pageSize: 12 }} data={series.links.map((link, index) => ({ ...link, _row: index }))}
          columns={[
            { title: t('mfa.flowName'), render: (_, row) => <details><summary>{typeof row.flow_name === 'string' && row.flow_name !== row.flow_uuid ? row.flow_name : t('mfa.unnamedFlow')}</summary><pre className="audit-json">{JSON.stringify(row, null, 2)}</pre></details> },
            { title: t('mfa.amount'), align: 'right', render: (_, row) => typeof row.value === 'number' ? number(row.value) : '—' },
            { title: t('pcf.unit'), render: () => series.unit },
          ]} />
        <details className="mfa-trace"><summary>{t('mfa.trace')}</summary>
          {series.nodes.map(node => <details key={String(node.id)}><summary>{String(node.label)}</summary><pre className="audit-json">{JSON.stringify(node, null, 2)}</pre></details>)}
          <pre className="audit-json">{JSON.stringify({ audit: result.audit, links: series.links }, null, 2)}</pre>
        </details>
      </Tabs.TabPane>
    </Tabs>
  </div>;
}
