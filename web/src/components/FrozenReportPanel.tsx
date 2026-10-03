import { Drawer, Table } from '@arco-design/web-react';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { api } from '../api/client';
import type { CbamTrialRequest, FrozenReport } from '../api/types';
import { useI18n } from '../i18n';
import { ErrorState, LoadingState } from './ui/States';
import { ResultExportMenu, ResultHeaderActions, ResultMenuActions } from './ResultHeaderActions';
import { FlowColumnTitle } from './FlowColumnTitle';
import { FrozenReportCharts } from './FrozenReportCharts';

type Source = { snapshotId: string; cbam: CbamTrialRequest } | { applicationId: string; recordId: string };

/** Both the screen and downloads read one server projection of this exact frozen record. */
export function FrozenReportPanel({ source, showSummary = false }: {source: Source; showSummary?: boolean}) {
  const { lang, t } = useI18n();
  const report = useQuery({ queryKey: ['frozen-report', source, lang], queryFn: () => 'cbam' in source
    ? api.cbamReportData(source.snapshotId, source.cbam) : api.organizationReportData(source.applicationId, source.recordId, lang) });
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>();
  const [detailsVisible, setDetailsVisible] = useState(false);
  const exportFile = async (kind: 'excel' | 'html' | 'print') => {
    if (pending) return;
    const printWindow = kind === 'print' ? window.open('about:blank', '_blank') : null;
    setPending(true); setError(undefined);
    try {
      if (kind === 'print' && !printWindow) throw new Error(t('pcf.popupBlocked'));
      const blob = 'cbam' in source
        ? kind === 'excel' ? await api.cbamReportExcel(source.snapshotId, source.cbam) : await api.cbamFullReport(source.snapshotId, source.cbam)
        : kind === 'excel' ? await api.organizationReportExcel(source.applicationId, source.recordId, lang) : await api.organizationFullReport(source.applicationId, source.recordId, lang);
      const url = URL.createObjectURL(blob);
      if (printWindow) {
        printWindow.opener = null;
        printWindow.addEventListener('load', () => printWindow.print(), { once: true });
        printWindow.location.href = url;
      } else {
        const a = document.createElement('a'); a.href = url;
        a.download = `${'cbam' in source ? 'cbam-' + source.snapshotId : 'organization-' + source.recordId}.${kind === 'excel' ? 'xlsx' : 'html'}`;
        document.body.appendChild(a); a.click(); a.remove();
      }
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (failure) { printWindow?.close(); setError(failure); }
    finally { setPending(false); }
  };
  if (report.isLoading) return <LoadingState rows={3} />;
  if (report.error) return <ErrorState error={report.error} onRetry={() => report.refetch()} />;
  if (!report.data) return null;
  return <><ResultHeaderActions><ResultExportMenu disabled={pending} actions={[
    {key:'excel',label:t('pcf.excel'),run:()=>void exportFile('excel')},
    {key:'html',label:t('report.downloadHtml'),run:()=>void exportFile('html')},
    {key:'print',label:t('pcf.print'),run:()=>void exportFile('print')},
  ]} /></ResultHeaderActions>{error ? <ErrorState error={error} /> : null}
    {'recordId' in source ? <><ResultMenuActions actions={[{ key: 'details', label: t('results.details'), run: () => setDetailsVisible(true) }]} />
      <Drawer visible={detailsVisible} onCancel={() => setDetailsVisible(false)} title={t('results.details')} footer={null}
        width="min(680px, 100vw)" unmountOnExit><pre className="audit-json">{JSON.stringify(report.data.sources, null, 2)}</pre></Drawer></> : null}
    <FrozenReportContent report={report.data} showSummary={showSummary} />
  </>;
}

export function FrozenReportContent({ report, showSummary }: {report: FrozenReport; showSummary: boolean}) {
  const { t, formatNumber } = useI18n();
  const value = (amount: number | string | null, unit?: string | null) => amount === null ? t('org.unknown') : `${formatNumber(Number(amount), {maximumSignificantDigits:9})}${unit ? ' ' + unit : ''}`;
  const status = (key: string) => report.status_labels[key] ?? t('report.statusUnavailable');
  const group = (key: string) => report.group_labels[key] ?? t('report.statusUnavailable');
  const sections = [
    { key: 'gaps', title: t('report.gaps'), rows: report.gaps },
    { key: 'outside', title: t('report.outside'), rows: report.outside_boundary },
  ];
  return <div className="frozen-report">
    {report.kind === 'organization' ? <FrozenReportCharts report={report} /> : null}
    {showSummary ? <><Table pagination={false} rowKey="group" data={report.summary} columns={[
      {title:t('org.group'),render:(_,row)=>group(row.group)},
      {title:t('org.emissions'),align:'right',render:(_,row)=>value(row.value,row.unit)},
      {title:t('org.status'),render:(_,row)=>status(row.status)},
    ]} /><p className="result-coverage-note">{report.complete_total === null ? t('report.incomplete') : t('report.boundaryTotal')}</p></> : null}
    <h3>{t('report.processContributions')}</h3>
    {report.kind === 'cbam' ? <FrozenReportCharts report={report} /> : null}
    {report.detail_status === 'frozen_process_contribution_evidence_unavailable' ? <p>{t('report.noBreakdown')}</p> : <Table pagination={false} rowKey={row=>`${row.group}:${row.process_id}`} data={report.process_contributions} columns={[
      {title:t('org.group'),render:(_,row)=>group(row.group)},
      {title:t('pcf.process'),render:(_,row)=>row.process_name ?? t('pcf.unnamedProcess')},
      {title:t('report.includedEmissions'),align:'right',render:(_,row)=>value(row.contribution_value,row.contribution_unit)},
    ]} />}
    <h3>{t('report.detail')}</h3>
    <Table pagination={false} scroll={{x:900}} rowKey={row=>`${row.group}:${row.exchange_id}`} data={report.details} columns={[
      {title:t('org.group'),width:130,render:(_,row)=>group(row.group)},
      {title:t('pcf.process'),width:210,render:(_,row)=>row.process_name ?? t('pcf.unnamedProcess')},
      {title:<FlowColumnTitle />,width:260,render:(_,row)=>row.flow_name ?? t('mfa.unnamedFlow')},
      {title:t('inventory.columnAmount'),width:150,align:'right',render:(_,row)=>value(row.quantity,row.quantity_unit)},
      {title:t('report.includedEmissions'),width:150,align:'right',render:(_,row)=>value(row.contribution_value,row.contribution_unit)},
      {title:t('org.status'),width:220,render:(_,row)=><>{status(row.status)}{row.basis ? <details><summary>{t('report.basis')}</summary>{row.basis}</details> : null}</>},
    ]} />
    {sections.map(section=><section key={section.key}><h3>{section.title}</h3>{section.rows.length ? <Table pagination={false} rowKey={row=>`${row.name}:${row.status}`} data={section.rows} columns={[
      {title:t('report.item'),render:(_,row)=>row.name ?? t('report.nameUnavailable')},
      {title:t('org.status'),render:(_,row)=>status(row.status)},
    ]} /> : <p>{t('org.none')}</p>}</section>)}
    {report.uncharacterized.length ? <section><h3>{t('report.uncharacterized')}</h3><p>{t('report.noCfNote')}</p><Table pagination={false} rowKey="exchange_id" data={report.uncharacterized} columns={[
      {title:t('pcf.process'),render:(_,row)=>row.process_name ?? t('pcf.unnamedProcess')},
      {title:<FlowColumnTitle />,render:(_,row)=>row.flow_name ?? t('mfa.unnamedFlow')},
      {title:t('inventory.columnAmount'),align:'right',render:(_,row)=>value(row.quantity,row.quantity_unit)},
    ]} /></section> : null}
    <p>{t('report.methodNote')}{report.method_name ? ` ${report.method_name} · ${report.method_version}` : ''}</p>
    <details><summary>{t('inventory.frozenIdentity')}</summary><pre className="audit-json">{JSON.stringify(report.sources,null,2)}</pre></details>
  </div>;
}
