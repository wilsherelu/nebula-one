import { Alert, Button, Modal, Radio } from '@arco-design/web-react';
import { useI18n } from '../i18n';

export type CalculationTask = 'pcf' | 'cbam' | 'organization' | 'mfa';

export interface CalculationChoice {
  task: CalculationTask;
  available: boolean;
  reason?: string;
  method?: string;
}

export function CalculationMethodDialog({ visible, choices, selected, onSelect, dirty, pending, error, onCancel, onStart }: {
  visible: boolean;
  choices: CalculationChoice[];
  selected: CalculationTask;
  onSelect: (task: CalculationTask) => void;
  dirty: boolean;
  pending: boolean;
  error?: unknown;
  onCancel: () => void;
  onStart: () => void;
}) {
  const { t } = useI18n();
  const labels = { pcf: t('task.pcf'), cbam: t('task.cbam'), organization: t('task.organization'), mfa: t('task.mfa') };
  const current = choices.find(choice => choice.task === selected);
  return <Modal visible={visible} title={t('workspace.chooseTask')} className="calculation-method-dialog"
    style={{ width: 560, maxWidth: 'calc(100vw - 32px)' }} footer={null} onCancel={onCancel}
    maskClosable={!pending} closable={!pending} escToExit={!pending} autoFocus>
    <Radio.Group className="calculation-method-choices" aria-label={t('workspace.chooseTask')} value={selected}
      onChange={value => onSelect(value as CalculationTask)} disabled={pending}>
      {choices.map(choice => <Radio key={choice.task} value={choice.task} disabled={!choice.available}>
        <strong>{labels[choice.task]}</strong>
        {choice.method ? <small>{choice.method}</small> : null}
        {!choice.available && choice.reason ? <small>{choice.reason}</small> : null}
      </Radio>)}
    </Radio.Group>
    {error ? <Alert type="error" content={error instanceof Error ? error.message : String(error)} /> : null}
    <div className="form-actions"><Button disabled={pending} onClick={onCancel}>{t('workspace.draftCancel')}</Button>
      <Button type="primary" loading={pending} disabled={!current?.available || pending} onClick={onStart}>
        {dirty ? t('workspace.saveAndCompute') : t('workspace.startCompute')}
      </Button></div>
  </Modal>;
}
