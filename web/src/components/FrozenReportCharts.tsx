import ReactECharts from 'echarts-for-react';
import type { FrozenReport } from '../api/types';
import { useI18n } from '../i18n';
import { ContributionBars } from './ContributionChart';

export function organizationChartData(report: FrozenReport) {
  const rows = report.summary.filter(row => row.value !== null && row.unit && String(row.value).trim()
    && Number.isFinite(Number(row.value))).map(row => ({
      label: report.group_labels[row.group] ?? row.group, value: Number(row.value), unit: row.unit!,
    }));
  const denominator = rows.reduce((sum, row) => sum + row.value, 0);
  return { rows, denominator,
    donut: rows.length > 0 && Number.isFinite(denominator) && denominator > 0
      && rows.every(row => row.value >= 0 && row.unit === rows[0].unit),
    partial: report.complete_total === null || rows.length !== report.summary.length
      || report.gaps.length > 0 || report.uncharacterized.length > 0,
  };
}

export function FrozenReportCharts({ report }: {report: FrozenReport}) {
  const { t, formatNumber } = useI18n();
  if (report.kind === 'cbam') {
    return <ContributionBars description={t('report.processContributions')} rows={report.process_contributions
      .filter(row => row.contribution_value !== null && String(row.contribution_value).trim()
        && Number.isFinite(Number(row.contribution_value)))
      .map(row => ({ label: `${row.process_name ?? t('pcf.unnamedProcess')} · ${report.group_labels[row.group] ?? t('report.statusUnavailable')}`,
        value: Number(row.contribution_value), unit: row.contribution_unit }))} />;
  }
  const data = organizationChartData(report);
  const title = t(data.partial ? 'report.calculatedComposition' : 'report.completeComposition');
  if (!data.rows.length) return null;
  return <section aria-label={title}><h3>{title}</h3>{data.donut ? <>
    <p>{t('report.chartDenominator')}: {formatNumber(data.denominator, { maximumSignificantDigits: 9 })} {data.rows[0].unit}</p>
    <ReactECharts opts={{renderer: 'svg'}} style={{height: 320}} option={{
      animation: false, aria: {enabled: true, description: title},
      tooltip: {trigger: 'item', renderMode: 'richText'},
      legend: {bottom: 0, type: 'scroll'},
      series: [{type: 'pie', radius: ['42%', '65%'], center: ['50%', '43%'],
        label: {show: false}, data: data.rows.map(row => ({name: row.label, value: row.value}))}],
    }} />
  </> : <ContributionBars rows={data.rows} description={title} />}</section>;
}
