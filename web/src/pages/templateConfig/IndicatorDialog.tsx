import { Modal } from '@arco-design/web-react';
import type { TemplateAccountingMethod } from '../../api/templateMethods';
import { useI18n } from '../../i18n';

/** Display the exact bound characterization, without opening a rule editor. */
export function IndicatorDialog({ scheme, onClose, onCreate }: {
  scheme: TemplateAccountingMethod; onClose: () => void; onCreate: () => void;
}) {
  const { t } = useI18n();
  const formula = scheme.package_detail?.formula_graph;
  const method = typeof formula?.lcia_method === 'string' ? formula.lcia_method : null;
  const unit = typeof formula?.result_unit === 'string' ? formula.result_unit : null;
  return <Modal visible title={t('tm.task.setIndicator')} onCancel={onClose}
    onOk={onCreate} okText={t('templates.newProject')} cancelText={t('common.close')}>
    <p>{t('tm.task.completeModelHint')}</p>
    <dl className="template-facts">
      <dt>{t('tm.indicator.method')}</dt><dd>{method ?? t('tm.indicator.unavailable')}</dd>
      <dt>{t('tm.indicator.unit')}</dt><dd>{unit ?? t('tm.indicator.unavailable')}</dd>
    </dl>
    <p className="helper-text">{t('tm.indicator.bound')}</p>
  </Modal>;
}
