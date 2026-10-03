import { Table } from '@arco-design/web-react';
import type { ProjectWorkspace, SolvedSystemSnapshot } from '../api/types';
import { useI18n } from '../i18n';
import { CalculationTarget } from './CalculationTarget';
import { ProcessGraph } from './ProcessGraph';

/** Quantities come only from this immutable revision; solve inputs come from its frozen receipt. */
export function ReadOnlyProjectInventory({ workspace, snapshot }: {
  workspace: ProjectWorkspace; snapshot?: SolvedSystemSnapshot;
}) {
  const { t, formatNumber } = useI18n();
  const basis = snapshot?.provider_receipt.calculation_basis as { demand?: ProjectWorkspace['demand'] } | undefined;
  const pins = [...(workspace.background_process_pins ?? []), ...(workspace.mapped_background_process_pins ?? []), ...(workspace.project_background_pins ?? [])];
  return <section className="section-panel calculation-inputs">
    <p className="helper-text">{t('inventory.readOnly')}</p>
    <CalculationTarget workspace={workspace} demand={basis?.demand ?? workspace.demand} />
    {workspace.process_graph ? <ProcessGraph graph={workspace.process_graph} /> : null}
    <Table rowKey="key" pagination={false} scroll={{ x: 720 }} data={workspace.fields} columns={[
      { title: t('pcf.process'), dataIndex: 'process', width: 230 },
      { title: t('inventory.columnFlow'), dataIndex: 'label', width: 290 },
      { title: t('inventory.columnDirection'), width: 90, render: (_, row) => row.flow_type === 'biosphere' ? t(row.group === 'inputs' ? 'inventory.intake' : 'inventory.emission') : t(row.group === 'inputs' ? 'inventory.input' : 'inventory.output') },
      { title: t('inventory.columnAmount'), align: 'right', width: 120, render: (_, row) => <span className="tabular">{formatNumber(row.value, { maximumSignificantDigits: 12 })}</span> },
      { title: t('inventory.columnUnit'), dataIndex: 'unit', width: 80 },
    ]} />
    <h3>{t('inventory.columnBackground')}</h3>
    {pins.length ? pins.map(pin => <details key={pin.consumer_exchange_id} className="frozen-background">
      <summary>{workspace.background_ports?.find(port => port.exchange_id === pin.consumer_exchange_id)?.process ?? t('pcf.unnamedProcess')}
        {' · '}{workspace.background_ports?.find(port => port.exchange_id === pin.consumer_exchange_id)?.label ?? t('mfa.unnamedFlow')}</summary>
      <pre className="audit-json">{JSON.stringify(pin, null, 2)}</pre>
    </details>) : <p className="helper-text">{t('inventory.noLinkedBackground')}</p>}
    <details className="frozen-input-identity"><summary>{t('inventory.frozenIdentity')}</summary>
      <pre className="audit-json">{JSON.stringify({ revision_id: workspace.revision_id, revision_content_sha256: workspace.content_sha256,
        model_processing_rules_ref: workspace.model_processing_rules_ref, demand: basis?.demand ?? workspace.demand,
        project_identity: workspace.frozen_identity,
        snapshot_id: snapshot?.id, snapshot_content_sha256: snapshot?.content_sha256,
        provider_receipt: snapshot?.provider_receipt }, null, 2)}</pre>
    </details>
  </section>;
}
