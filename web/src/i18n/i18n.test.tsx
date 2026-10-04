import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { I18nProvider, LANGUAGE_STORAGE_KEY, useI18n } from './index';
import { LanguageSwitch } from '../layout/LanguageSwitch';
import { templateName } from '../api/seedProjects';

// The provider is mounted by the test harness for every other suite; this file drives the provider
// directly to pin the language contract: a fresh load, a click, a reload and an explicit handoff link.
function Probe() {
  const { lang, t } = useI18n();
  return <div><span data-testid="lang">{lang}</span><span>{t('nav.projects')}</span></div>;
}

afterEach(() => { cleanup(); localStorage.removeItem(LANGUAGE_STORAGE_KEY); window.history.pushState({}, '', '/'); });

describe('interface language', () => {
  it('starts in Chinese and switches the whole screen on a click', async () => {
    render(<I18nProvider><LanguageSwitch /><Probe /></I18nProvider>);
    expect(screen.getByTestId('lang')).toHaveTextContent('zh');
    expect(screen.getByText('我的项目')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('radio', { name: 'English' }));
    await waitFor(() => expect(screen.getByTestId('lang')).toHaveTextContent('en'));
    expect(screen.getByText('My projects')).toBeInTheDocument();
  });
  it('keeps the chosen language across a reload', async () => {
    const first = render(<I18nProvider><LanguageSwitch /><Probe /></I18nProvider>);
    await userEvent.click(screen.getByRole('radio', { name: 'English' }));
    await waitFor(() => expect(screen.getByTestId('lang')).toHaveTextContent('en'));
    first.unmount();
    render(<I18nProvider><Probe /></I18nProvider>);
    expect(screen.getByTestId('lang')).toHaveTextContent('en');
    expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe('en');
  });
  it('honours an explicit handoff parameter over the saved choice', () => {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, 'zh');
    window.history.pushState({}, '', '/?lang=en');
    render(<I18nProvider><Probe /></I18nProvider>);
    expect(screen.getByTestId('lang')).toHaveTextContent('en');
  });
});

describe('template display names', () => {
  const item = { title: 'Blast furnace – BOF steel', display_name: { zh: '高炉—转炉钢铁', en: 'Blast furnace – BOF steel' } };
  // Both names are pinned projections from the template's own display metadata; the reader only chooses.
  it('reads the declared name for the language and falls back to the canonical title', () => {
    expect(templateName(item, 'zh')).toBe('高炉—转炉钢铁');
    expect(templateName(item, 'en')).toBe('Blast furnace – BOF steel');
    expect(templateName(item, 'fr')).toBe('Blast furnace – BOF steel');
    expect(templateName({ title: 'Untitled pack' }, 'zh')).toBe('Untitled pack');
    expect(templateName({ title: 'Untitled pack', display_name: { zh: '  ', en: 'x' } }, 'zh')).toBe('Untitled pack');
  });
});
