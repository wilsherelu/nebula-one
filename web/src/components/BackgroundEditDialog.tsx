import { Modal, Select } from '@arco-design/web-react';
import type { ProjectWorkspace } from '../api/types';
import { MappedBackgroundDialog } from './MappedBackgroundDialog';
import { UserProjectBackgroundDialog } from './UserProjectBackgroundDialog';
import { ProjectBackgroundPanel } from './ProjectBackgroundPanel';
import { useI18n } from '../i18n';
import { useState } from 'react';

export function BackgroundEditDialog({ workspace, exchangeId, onClose, onSaved, onReload }: {
  workspace: ProjectWorkspace; exchangeId: string; onClose: () => void;
  onSaved: (workspace: ProjectWorkspace) => void; onReload: () => void;
}) {
  const port = workspace.background_ports?.find(p => p.exchange_id === exchangeId);
  const { t } = useI18n();
  const [busy, setBusy] = useState(false);
  const [source, setSource] = useState(workspace.project_background_pins?.some(pin => pin.consumer_exchange_id === exchangeId) ? 'user' : workspace.background_process_pins?.some(pin => pin.consumer_exchange_id === exchangeId) ? 'exact' : 'local');
  const props = { workspace, consumerId: exchangeId, onClose, onSaved, onReload, embedded: true, onBusyChange: setBusy };
  return <Modal visible title={t('background.choose')} className="background-picker" style={{width:720,maxWidth:'calc(100vw - 32px)'}} onCancel={() => { if (!busy) onClose(); }} closable={!busy} maskClosable={!busy} escToExit={!busy} footer={null} unmountOnExit>
    <div className="background-picker-context"><strong title={port?.process}>{port?.process}</strong><span title={port?.label}>{port?.label}</span></div>
    <Select className="background-source-picker" aria-label={t('background.source')} value={source} disabled={busy} onChange={setSource} options={[
      {value:'local',label:t('background.localSource')}, {value:'user',label:t('background.userSource')}, {value:'exact',label:t('background.exactSource')},
    ]} />
    {source === 'local' ? <MappedBackgroundDialog {...props} /> : source === 'user' ? <UserProjectBackgroundDialog {...props} /> : <ProjectBackgroundPanel workspace={workspace} exchangeId={exchangeId} initialAction="external" portFilter={port => port.exchange_id === exchangeId} onSaved={next => { onSaved(next); onClose(); }} onReload={onReload} onClose={onClose} onBusyChange={setBusy} />}
  </Modal>;
}
