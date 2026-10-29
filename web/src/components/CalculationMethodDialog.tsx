import { Alert, Button, Modal, Radio, Select } from '@arco-design/web-react';
import { useI18n, type MessageKey } from '../i18n';
import type { CalculationMethod, CalculationMethodDetail, CalculationMethodRef, CalculationMethodValidation, ProjectWorkspace } from '../api/types';
import { CalculationTarget } from './CalculationTarget';

export type CalculationTask = 'pcf' | 'cbam' | 'organization' | 'mfa';

export interface CalculationChoice {
  task: CalculationTask;
  available: boolean;
  reason?: string;
  method?: string;
}

/** A version option for the exact-version selector. A draft has no frozen content hash yet, so it
 * is labelled as needing a check; a ready version can be used once checked. */
function versionLabel(version: { version: number; status: string }, t: (key: MessageKey) => string) {
  return `${t('cm.versionLabel')} ${version.version} · ${version.status === 'ready' ? t('cm.status.ready') : t('cm.status.draft')}`;
}

export function CalculationMethodDialog({ visible, choices, selected, onSelect, dirty, pending, error, onCancel, onStart, workspace, methodOptions, methodId, onMethodId, methodDetail, methodVersion, onMethodVersion, checkedRef, validation, checking, onCheckAndUse }: {
  workspace?: ProjectWorkspace;
  visible: boolean;
  choices: CalculationChoice[];
  selected: CalculationTask;
  onSelect: (task: CalculationTask) => void;
  dirty: boolean;
  pending: boolean;
  error?: unknown;
  onCancel: () => void;
  onStart: () => void;
  methodOptions?: CalculationMethod[];
  methodId?: string | null;
  onMethodId?: (id: string | null) => void;
  methodDetail?: CalculationMethodDetail | null;
  methodVersion?: number | null;
  onMethodVersion?: (version: number | null) => void;
  checkedRef?: CalculationMethodRef | null;
  validation?: CalculationMethodValidation | null;
  checking?: boolean;
  onCheckAndUse?: () => void;
}) {
  const { t } = useI18n();
  const labels = { pcf: t('task.pcf'), cbam: t('task.cbam'), organization: t('task.organization'), mfa: t('task.mfa') };
  const current = choices.find(choice => choice.task === selected);
  const backgroundCount = workspace?.background_ports?.length ?? 0;
  const versions = (methodDetail?.versions ?? []).slice().sort((a, b) => b.version - a.version);
  const usingOfficial = !methodId;
  // A user method may only be computed after its exact version has been checked and used; the
  // checked ref must still match the currently chosen method+version, so switching either clears it.
  const checkedMatches = Boolean(checkedRef && methodId && checkedRef.method_id === methodId
    && methodVersion != null && checkedRef.version === methodVersion);
  const canStart = (usingOfficial || checkedMatches) && Boolean(current?.available) && !pending;
  const problems = validation && !validation.valid ? validation.problems : [];
  return <Modal visible={visible} title={t('workspace.chooseTask')} className="calculation-method-dialog"
    style={{ width: 560, maxWidth: 'calc(100vw - 32px)' }} footer={null} onCancel={onCancel}
    maskClosable={!pending} closable={!pending} escToExit={!pending} autoFocus>
    <CalculationTarget workspace={workspace} />
    <dl className="calculation-method-dialog__facts">
      <div><dt>{t('calculation.backgroundLink')}</dt>
        <dd>{backgroundCount ? t('calculation.backgroundLinked', { count: backgroundCount }) : t('calculation.backgroundNone')}</dd></div>
      {current?.method ? <div><dt>{t('calculation.defaultIndicator')}</dt><dd>{current.method}</dd></div> : null}
    </dl>
    {dirty ? <p>{t('calculation.savedTarget')}</p> : null}
    <Radio.Group className="calculation-method-choices" aria-label={t('workspace.chooseTask')} value={selected}
      onChange={value => onSelect(value as CalculationTask)} disabled={pending}>
      {choices.map(choice => <Radio key={choice.task} value={choice.task} disabled={!choice.available}>
        <span className="calculation-method-copy"><strong>{labels[choice.task]}</strong>
          {choice.method ? <small>{choice.method}</small> : null}
          {!choice.available && choice.reason ? <small>{choice.reason}</small> : null}</span>
      </Radio>)}
    </Radio.Group>
    {methodOptions?.length ? <div className="calculation-method-dialog__method">
      <label htmlFor="calc-user-method">{t('workspace.calcUseMethod')}</label>
      <Select id="calc-user-method" aria-label={t('workspace.calcUseMethod')} value={methodId ?? ''} disabled={pending}
        onChange={value => onMethodId?.(value ? String(value) : null)}
        options={[{ value: '', label: t('workspace.calcOfficial') }, ...methodOptions.map(item => ({ value: item.id, label: item.name }))]} />
    </div> : null}
    {methodId ? <div className="calculation-method-dialog__check">
      <label htmlFor="calc-method-version">{t('workspace.calcMethodVersion')}</label>
      <div className="calculation-method-dialog__check-row">
        <Select id="calc-method-version" aria-label={t('workspace.calcMethodVersion')} value={methodVersion ?? ''}
          disabled={pending || checking || !versions.length} onChange={value => onMethodVersion?.(value === '' ? null : Number(value))}
          options={versions.map(item => ({ value: item.version, label: versionLabel(item, t) }))} />
        <Button type="outline" loading={checking} disabled={pending || checking || methodVersion == null} onClick={onCheckAndUse}>
          {t('workspace.calcCheckAndUse')}
        </Button>
      </div>
      {checkedMatches ? <Alert type="success" className="calculation-method-dialog__effective"
        content={`${t('workspace.calcEffectiveScheme')}：${methodDetail?.method.name ?? ''} · ${t('cm.versionLabel')} ${checkedRef?.version}`} /> : null}
      {validation && !validation.valid ? <Alert type="error" content={t('workspace.calcCheckFailed')} /> : null}
      {problems.length ? <ul className="calculation-method-dialog__problems">
        {problems.map((problem, index) => <li key={index}>
          {problem.message}{problem.process_instance_id ? ` · ${t('workspace.calcProblemProcess')} ${problem.process_instance_id}` : ''}
          {problem.exchange_id ? ` · ${t('workspace.calcProblemFlow')} ${problem.exchange_id}` : ''}
        </li>)}
      </ul> : null}
      {!usingOfficial && !checkedMatches ? <p className="calculation-method-dialog__hint">{t('workspace.calcCheckHint')}</p> : null}
    </div> : null}
    {error ? <Alert type="error" content={error instanceof Error ? error.message : String(error)} /> : null}
    <div className="form-actions"><Button disabled={pending} onClick={onCancel}>{t('workspace.draftCancel')}</Button>
      <Button type="primary" loading={pending} disabled={!canStart} onClick={onStart}>
        {dirty ? t('workspace.saveAndCompute') : t('workspace.startCompute')}
      </Button></div>
  </Modal>;
}
