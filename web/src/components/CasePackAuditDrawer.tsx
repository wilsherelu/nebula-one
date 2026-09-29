import { Descriptions, Drawer, Tabs } from '@arco-design/web-react';
import type { ReactNode } from 'react';
import type { CasePackApplication, CasePackCatalogItem } from '../api/types';
import { CopyableValue } from './ui/CopyableValue';
import { StatusBadge } from './ui/StatusBadge';

interface Props {
  casepack: CasePackCatalogItem;
  applicationCase: CasePackApplication;
  visible: boolean;
  onClose: () => void;
  details?: ReactNode;
  initialTab?: string;
  action?: ReactNode;
  summary?: ReactNode;
}

export function CasePackAuditDrawer({ casepack, applicationCase, visible, onClose, details, initialTab = 'case', action, summary }: Props) {
  return (
    <Drawer
      className="audit-drawer"
      width={560}
      visible={visible}
      onCancel={onClose}
      footer={initialTab === 'application' ? action ?? null : null}
      unmountOnExit
      title={<span>{initialTab === 'application' ? '案例详情' : '案例审计'} <span className="helper-text">{applicationCase.title}</span></span>}
    >
      <Tabs key={`${applicationCase.id}-${initialTab}`} defaultActiveTab={initialTab}>
        {details ? <Tabs.TabPane key="details" title="模型与能力">{details}</Tabs.TabPane> : null}
        <Tabs.TabPane key="case" title="案例包">
          {casepack.showcase ? <p className="helper-text">{casepack.showcase.description}</p> : null}
          <Descriptions column={1} size="small" border data={[
            { label: '状态', value: <StatusBadge status={casepack.lifecycle_status} /> },
            { label: 'CasePack', value: <CopyableValue value={`${casepack.id}@${casepack.version}`} compact={false} /> },
            { label: '内容哈希', value: <CopyableValue value={casepack.case_pack_sha256} compact={false} /> },
            { label: '模型图哈希', value: <CopyableValue value={casepack.expected_graph_sha256} compact={false} /> },
            { label: 'Provider', value: casepack.provider && casepack.provider_contract ? `${casepack.provider} · ${casepack.provider_contract}` : '未绑定' },
            { label: '许可审计', value: `${casepack.license_audit_status} · ${casepack.publication_gate}` },
          ]} />
        </Tabs.TabPane>
        <Tabs.TabPane key="application" title="案例详情">
          {summary}
          <details className="result-details"><summary>技术身份与版本</summary><Descriptions column={1} size="small" border data={[
            { label: 'ApplicationCase', value: <CopyableValue value={`${applicationCase.id}@${applicationCase.version}`} compact={false} /> },
            { label: 'Resolved hash', value: <CopyableValue value={applicationCase.resolved_case_sha256} compact={false} /> },
            { label: 'StudyFrame', value: <CopyableValue value={applicationCase.study_frame_id} compact={false} /> },
            { label: '研究框架状态', value: <StatusBadge status={applicationCase.study_frame_status} /> },
          ]} /></details>
          {applicationCase.blocked_capabilities.length ? <><h3 className="audit-heading">受限分析</h3><ul className="catalog-limitations">{applicationCase.blocked_capabilities.map((item) => <li key={item.capability}>{item.reason}</li>)}</ul></> : null}
        </Tabs.TabPane>
      </Tabs>
    </Drawer>
  );
}
