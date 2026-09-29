import { Modal } from '@arco-design/web-react';
import type { ProjectWorkspace } from '../api/types';
import { ProjectBackgroundPanel } from './ProjectBackgroundPanel';

export function BackgroundEditDialog({ workspace, exchangeId, onClose, onSaved, onReload }: {
  workspace: ProjectWorkspace; exchangeId: string; onClose: () => void;
  onSaved: (workspace: ProjectWorkspace) => void; onReload: () => void;
}) {
  const port = workspace.background_ports?.find(p => p.exchange_id === exchangeId);
  return <Modal visible title={`背景数据 · ${port ? `${port.process} / ${port.label}` : exchangeId}`} onCancel={onClose} footer={null} unmountOnExit>
    <ProjectBackgroundPanel
      workspace={workspace}
      exchangeId={exchangeId}
      portFilter={p => p.exchange_id === exchangeId}
      onReload={onReload}
      onSaved={next => { onSaved(next); onClose(); }}
    />
  </Modal>;
}
