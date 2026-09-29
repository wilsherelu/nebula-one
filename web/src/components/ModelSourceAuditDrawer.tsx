import { Descriptions, Drawer, Empty, Tabs } from '@arco-design/web-react';
import type { ModelSource, ModelSourcePreview } from '../api/types';
import { CopyableValue } from './ui/CopyableValue';
import { StatusBadge } from './ui/StatusBadge';

export function ModelSourceAuditDrawer({ value, visible, onClose }: {
  value: ModelSource | ModelSourcePreview;
  visible: boolean;
  onClose: () => void;
}) {
  const persisted = 'id' in value;
  const dependencies = value.external_dependencies;
  const issues = value.issues;
  return (
    <Drawer className="audit-drawer" width={560} visible={visible} onCancel={onClose} footer={null} unmountOnExit title="模型来源审计">
      <Tabs defaultActiveTab="identity">
        <Tabs.TabPane key="identity" title="身份">
          <Descriptions column={1} size="small" border data={[
            { label: '状态', value: <StatusBadge status={value.status} /> },
            { label: '来源类型', value: value.source_type },
            { label: '文件 SHA-256', value: <CopyableValue value={value.file_sha256} compact={false} /> },
            { label: persisted ? '内容 SHA-256' : '预览 SHA-256', value: <CopyableValue value={persisted ? value.content_sha256 : value.preview_sha256} compact={false} /> },
            ...(persisted ? [
              { label: 'Provider', value: `${value.provider} · ${value.provider_base_url}` },
              { label: '上游项目', value: <CopyableValue value={value.upstream_project_id} compact={false} /> },
              { label: '上游版本', value: value.upstream_version ?? '尚未选择' },
              { label: '图哈希', value: <CopyableValue value={value.graph_sha256} compact={false} /> },
            ] : []),
          ]} />
        </Tabs.TabPane>
        <Tabs.TabPane key="receipt" title="回执">
          <pre className="audit-json">{JSON.stringify(persisted ? value.import_receipt : value.summary, null, 2)}</pre>
        </Tabs.TabPane>
        <Tabs.TabPane key="issues" title={`问题 ${issues.length}`}>
          {issues.length || dependencies.length ? <pre className="audit-json">{JSON.stringify({ issues, external_dependencies: dependencies }, null, 2)}</pre> : <Empty description="没有问题或外部依赖" />}
        </Tabs.TabPane>
      </Tabs>
    </Drawer>
  );
}
