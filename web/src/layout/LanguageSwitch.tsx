import { Button, Dropdown, Menu, Radio, Tooltip } from '@arco-design/web-react';
import { useI18n } from '../i18n';
import type { Lang } from '../i18n';

/** Language names stay in their own script. */
const LABELS: Record<Lang, string> = { zh: '中文', en: 'English' };

export function LanguageSwitch({ compact = false }: { compact?: boolean }) {
  const { lang, setLanguage, t } = useI18n();
  if (compact) return <Tooltip content={t('language.switchAria')}>
    <Dropdown trigger="click" droplist={<Menu selectedKeys={[lang]}
      onClickMenuItem={value => setLanguage(value as Lang)}>
      {(Object.keys(LABELS) as Lang[]).map(value => <Menu.Item key={value}>{LABELS[value]}</Menu.Item>)}
    </Menu>}>
      <Button className="language-switch" aria-label={t('language.switchAria')}>{lang === 'zh' ? '中' : 'EN'}</Button>
    </Dropdown>
  </Tooltip>;
  return <Radio.Group
    type="button"
    size="small"
    aria-label={t('language.switchAria')}
    className="language-switch"
    value={lang}
    onChange={value => setLanguage(value as Lang)}
    options={(Object.keys(LABELS) as Lang[]).map(value => ({ label: LABELS[value], value }))}
  />;
}
