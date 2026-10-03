import { Button, Modal } from '@arco-design/web-react';
import { useQuery } from '@tanstack/react-query';
import { useRef } from 'react';
import { api } from '../api/client';
import type { SolvedSystemSnapshot } from '../api/types';
import { useI18n } from '../i18n';
import { ReadOnlyProjectInventory } from './ReadOnlyProjectInventory';
import { ErrorState, LoadingState } from './ui/States';

/** Query identity follows the selected immutable revision, including when an older request finishes late. */
export function CalculationInputsDialog({ applicationId, snapshot, visible, onClose, afterClose }: {
  applicationId: string; snapshot: SolvedSystemSnapshot; visible: boolean; onClose: () => void; afterClose: () => void;
}) {
  const { t, lang, formatDate } = useI18n();
  const content = useRef<HTMLDivElement>(null);
  const workspace = useQuery({ queryKey: ['workspace', applicationId, snapshot.system_revision_id, lang],
    queryFn: () => api.workspace(applicationId, snapshot.system_revision_id, lang), enabled: visible });
  return <Modal title={t('inventory.calculationInputs')} visible={visible} onCancel={onClose} afterClose={afterClose}
    footer={<Button type="outline" onClick={onClose}>{t('common.close')}</Button>} escToExit focusLock autoFocus={false}
    afterOpen={() => { if (content.current) { content.current.scrollTop = 0; content.current.focus({ preventScroll: true }); } }}
    unmountOnExit style={{ width: 'min(1100px, calc(100vw - 32px))' }}
    className="calculation-inputs-dialog">
    <div ref={content} tabIndex={-1} style={{ maxHeight: '70vh', overflow: 'auto', overflowWrap: 'anywhere' }}>
      <p>{t('analysis.recordSelectorAria')} · {formatDate(snapshot.created_at)}</p>
      {workspace.error ? <ErrorState error={workspace.error} onRetry={() => workspace.refetch()} />
        : workspace.isPending ? <LoadingState />
        : workspace.data ? <ReadOnlyProjectInventory workspace={workspace.data} snapshot={snapshot} /> : null}
    </div>
  </Modal>;
}
