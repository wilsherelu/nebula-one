import { Descriptions, Drawer, Empty, Tabs } from '@arco-design/web-react';
import type { ComparisonRun } from '../api/types';
import { CopyableValue } from './ui/CopyableValue';
import { StatusBadge } from './ui/StatusBadge';

interface Props {
  run: ComparisonRun;
  visible: boolean;
  onClose: () => void;
}

export function AuditDrawer({ run, visible, onClose }: Props) {
  return (
    <Drawer
      className="audit-drawer"
      width={560}
      visible={visible}
      onCancel={onClose}
      footer={null}
      title={<span>审计证据 <span className="helper-text">哈希、求解回执与 MFA 校验</span></span>}
      unmountOnExit
    >
      <Tabs defaultActiveTab="summary">
        <Tabs.TabPane key="summary" title="运行">
          <Descriptions column={1} size="small" border data={[
            { label: '状态', value: <StatusBadge status={run.audit.status ?? run.status} /> },
            { label: '运行 ID', value: <CopyableValue value={run.id} compact={false} /> },
            { label: '结果哈希', value: <CopyableValue value={run.content_sha256} compact={false} /> },
            { label: '基准情景', value: <CopyableValue value={run.baseline_scenario_id} compact={false} /> },
          ]} />
          <h3 className="audit-heading">审计记录</h3>
          <pre className="audit-json">{JSON.stringify(run.audit, null, 2)}</pre>
        </Tabs.TabPane>
        <Tabs.TabPane key="scenarios" title={`情景 ${run.scenario_results.length}`}>
          {run.scenario_results.length ? run.scenario_results.map((result) => (
            <section className="audit-scenario" key={result.scenario_id}>
              <div className="section-heading"><h3>{result.scenario_name}</h3><StatusBadge status={result.mfa_audit.status ?? 'unknown'} /></div>
              <Descriptions column={1} size="small" border data={[
                { label: 'Revision', value: <CopyableValue value={result.system_revision_id} compact={false} /> },
                { label: 'Solve hash', value: <CopyableValue value={result.solve_hash} compact={false} /> },
                { label: 'Snapshot hash', value: <CopyableValue value={result.solved_snapshot_hash} compact={false} /> },
              ]} />
              <pre className="audit-json">{JSON.stringify(result.provider_receipt, null, 2)}</pre>
            </section>
          )) : <Empty description="本次运行没有生成情景结果" />}
        </Tabs.TabPane>
      </Tabs>
    </Drawer>
  );
}
