import { ConfigProvider } from '@arco-design/web-react';
import enUS from '@arco-design/web-react/es/locale/en-US';
import zhCN from '@arco-design/web-react/es/locale/zh-CN';
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { LANGUAGES, ERROR_MESSAGES, MESSAGES, type Lang, type MessageKey } from './messages';

export type { Lang, MessageKey };
export const LANGUAGE_STORAGE_KEY = 'nebula-one:ui-language';
const ARCO_LOCALE = { zh: zhCN, en: enUS };
const LOCALE_TAG: Record<Lang, string> = { zh: 'zh-CN', en: 'en-US' };

function normalize(value: string | null | undefined): Lang | null {
  const lower = (value ?? '').trim().toLowerCase();
  return (LANGUAGES as readonly string[]).includes(lower) ? (lower as Lang) : null;
}

/** A handoff link may carry the language; otherwise the saved choice wins, then Chinese. */
function initialLanguage(): Lang {
  return normalize(new URLSearchParams(window.location.search).get('lang'))
    ?? normalize(window.localStorage.getItem(LANGUAGE_STORAGE_KEY))
    ?? 'zh';
}

type I18n = {
  lang: Lang;
  setLanguage: (language: Lang) => void;
  t: (key: MessageKey, vars?: Record<string, string | number>) => string;
  errorText: (code: string | null | undefined) => string | null;
  formatNumber: (value: number | null | undefined, options?: Intl.NumberFormatOptions) => string;
  formatDate: (value: string | null | undefined) => string;
};

const I18nContext = createContext<I18n | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLanguage] = useState<Lang>(initialLanguage);
  useEffect(() => {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, lang);
    document.documentElement.lang = LOCALE_TAG[lang];
  }, [lang]);
  const t = useCallback((key: MessageKey, vars: Record<string, string | number> = {}) => {
    const pair = MESSAGES[key];
    return pair[lang === 'zh' ? 0 : 1].replace(/\{(\w+)\}/g, (whole, name: string) =>
      name in vars ? String(vars[name]) : whole);
  }, [lang]);
  const value = useMemo<I18n>(() => ({
    lang,
    setLanguage,
    t,
    errorText: (code) => {
      const pair = code ? ERROR_MESSAGES[code] : undefined;
      return pair ? (lang === 'zh' ? pair[0] : pair[1]) : null;
    },
    formatNumber: (amount, options) => amount === null || amount === undefined || !Number.isFinite(amount)
      ? '—' : new Intl.NumberFormat(LOCALE_TAG[lang], { maximumSignificantDigits: 10, ...options }).format(amount),
    formatDate: (iso) => {
      if (!iso) return t('state.notRecorded');
      const date = new Date(iso);
      return Number.isNaN(date.getTime()) ? t('state.notRecorded')
        : new Intl.DateTimeFormat(LOCALE_TAG[lang], { dateStyle: 'medium', timeStyle: 'short' }).format(date);
    },
  }), [lang, t]);
  return <I18nContext.Provider value={value}>
    <ConfigProvider locale={ARCO_LOCALE[lang]}>{children}</ConfigProvider>
  </I18nContext.Provider>;
}

export function useI18n(): I18n {
  const current = useContext(I18nContext);
  if (!current) throw new Error('useI18n needs an I18nProvider');
  return current;
}

/** The language the next screen should start in, as an explicit parameter rather than shared storage. */
export function languageParam(lang: Lang): string {
  return `lang=${lang}`;
}
