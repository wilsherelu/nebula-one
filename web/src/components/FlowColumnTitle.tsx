import { Button, Tooltip } from '@arco-design/web-react';
import { IconInfoCircle } from '@arco-design/web-react/icon';
import { useI18n } from '../i18n';
import { useState } from 'react';

export function FlowColumnTitle() {
  const { t } = useI18n();
  const [visible, setVisible] = useState(false);
  return <span>{t('inventory.columnFlow')} <Tooltip content={t('inventory.flowExplanation')}
    trigger={['hover', 'focus']} popupVisible={visible} onVisibleChange={setVisible} escToClose position="bottom">
    <Button type="text" size="mini" aria-label={t('inventory.flowExplanation')}
      onClick={() => setVisible(true)}
      icon={<IconInfoCircle />} />
  </Tooltip></span>;
}
