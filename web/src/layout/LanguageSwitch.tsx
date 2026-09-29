import { Radio } from '@arco-design/web-react';
import { useI18n } from '../i18n';
import type { Lang } from '../i18n';

/** Language names stay in their own script: 中 and EN are not strings to translate. */
const LABELS: Record<Lang, string> = { zh: '中', en: 'EN' };

export function LanguageSwitch() {
  const { lang, setLanguage, t } = useI18n();
  return <Radio.Group
    type="button"
    size="mini"
    aria-label={t('language.switchAria')}
    className="language-switch"
    value={lang}
    onChange={value => setLanguage(value as Lang)}
    options={(Object.keys(LABELS) as Lang[]).map(value => ({ label: LABELS[value], value }))}
  />;
}
