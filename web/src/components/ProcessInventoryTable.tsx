import { Alert, Button, InputNumber, Select, Table } from '@arco-design/web-react';
import { useSearchParams } from 'react-router-dom';
import type { ProjectWorkspace } from '../api/types';
import { useI18n } from '../i18n';
import { FlowColumnTitle } from './FlowColumnTitle';

type Field = ProjectWorkspace['fields'][number];
export function ProcessInventoryTable({fields, values, disabled, onChange, workspace, onEditBackground, hasGraph = false}: {
  fields: Field[]; values: Record<string, number>; disabled: boolean; onChange: (key: string, value: number) => void;
  workspace: ProjectWorkspace; onEditBackground?: (exchangeId: string) => void; hasGraph?: boolean;
}) {
  const { t, formatNumber } = useI18n();
  const [params, setParams] = useSearchParams();
  const processes = Array.from(new Map(fields.map(f => [f.process_id!, f.process])).entries());
  const selected = params.get('process') ?? processes[0]?.[0];
  const rows = fields.filter(f => f.process_id === selected);
  // A row can carry background data only when the revision lists it as an external technosphere input.
  const backgroundFor = (f: Field) => workspace.background_ports?.find(p => p.exchange_id === `${f.process_id}::${f.port_id}`);
  const hasPin = (exchangeId: string) => (workspace.background_process_pins ?? []).some(p => p.consumer_exchange_id === exchangeId)
    || (workspace.mapped_background_process_pins ?? []).some(p => p.consumer_exchange_id === exchangeId)
    || (workspace.project_background_pins ?? []).some(p => p.consumer_exchange_id === exchangeId);
  const basis = rows.filter(f => f.reference_product);
  return <section className={`process-inventory${hasGraph ? ' process-inventory--with-graph' : ''}`}>
    <div className="section-heading"><div><h3>{t('inventory.title')}</h3><small className="helper-text">{t('inventory.summary', { processes: processes.length, rows: rows.length })}</small></div><Select aria-label={t('inventory.selectProcess')} value={selected} options={processes.map(([value, label]) => ({value, label}))} onChange={value => setParams(prev => {const p = new URLSearchParams(prev); p.set('process', value); return p;})} /></div>
    {!rows.length ? <Alert type="error" content={t('inventory.unknownProcess')} /> : <Table rowKey={f => `${f.process_id}/${f.port_id}`} data={rows} pagination={false} scroll={{x: 640}} columns={[
      {title: <FlowColumnTitle />, dataIndex: 'label', render: (_, f: Field) => <span>{f.label}{rows.filter(row => row.label === f.label).length > 1 ? <small className="inventory-linked">{f.port_id}</small> : null}{f.linked ? <small className="inventory-linked">{t('inventory.internalLink')}</small> : null}</span>},
      {title: t('inventory.columnDirection'), width: 84, render: (_, f: Field) => f.flow_type === 'biosphere' ? (f.group === 'inputs' ? t('inventory.intake') : t('inventory.emission')) : f.group === 'inputs' ? t('inventory.input') : t('inventory.output')},
      {title: t('inventory.columnAmount'), width: 180, render: (_, f: Field) => <InputNumber aria-label={`${f.process} / ${f.label}`} value={values[f.key]} min={f.reference_product ? Number.EPSILON : 0} disabled={disabled} onChange={value => onChange(f.key, value)} />},
      {title: t('inventory.columnUnit'), dataIndex: 'unit', width: 80},
      ...(onEditBackground ? [{title: t('inventory.columnBackground'), width: 150, render: (_: unknown, f: Field) => {const port = backgroundFor(f); if (!port) return <span className="helper-text">—</span>; return <Button size="small" type="text" disabled={disabled} onClick={() => onEditBackground(port.exchange_id)}>{hasPin(port.exchange_id) ? t('inventory.changeBackground') : t('inventory.chooseBackground')}</Button>;}}] : []),
    ]} />}
    {/* The basis a batch is reported against is the entered product output itself, so it is shown as
        a quantity rather than re-explained as a rule. */}
    {basis.length ? <p className="inventory-basis">{basis.map(f =>
      `${t('form.productOutput', { amount: formatNumber(values[f.key]), unit: f.unit })} ${f.label}`).join('、')}</p> : null}
  </section>;
}
