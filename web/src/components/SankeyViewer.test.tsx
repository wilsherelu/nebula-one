import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { SankeyViewer } from './SankeyViewer';
import { I18nProvider, LANGUAGE_STORAGE_KEY } from '../i18n';

afterEach(() => { cleanup(); window.localStorage.removeItem(LANGUAGE_STORAGE_KEY); });

function renderViewer(element: React.ReactElement) {
  return render(<I18nProvider>{element}</I18nProvider>);
}

describe('SankeyViewer', () => {
  it('zooms only the viewport without changing the source result', async () => {
    renderViewer(<SankeyViewer src="/api/exact.svg" alt="MFA" />);
    const image = screen.getByRole('img', { name: 'MFA' });
    fireEvent.load(image);
    await userEvent.click(screen.getByRole('radio', { name: '放大查看' }));
    expect(image).toHaveClass('is-enlarged');
    expect(image).toHaveAttribute('src', '/api/exact.svg');
    await userEvent.click(screen.getByRole('radio', { name: '适配宽度' }));
    expect(image).not.toHaveClass('is-enlarged');
  });
  it('shows a scrollable loading state and exposes the original SVG', () => {
    renderViewer(<SankeyViewer src="/api/mfa/sankey.svg" alt="基准情景 MFA 桑基图" />);

    expect(screen.getByLabelText('正在加载')).toBeInTheDocument();
    const image = screen.getByRole('img', { name: '基准情景 MFA 桑基图' });
    fireEvent.load(image);

    expect(screen.queryByLabelText('正在加载')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: /打开全图/ })).toHaveAttribute(
      'href',
      '/api/mfa/sankey.svg',
    );
    expect(screen.getByLabelText('桑基图滚动区域')).toHaveAttribute('tabindex', '0');
  });

  it('shows an actionable error and retries without changing the evidence URL', async () => {
    renderViewer(<SankeyViewer src="/api/mfa/sankey.svg" alt="资源效率 MFA 桑基图" />);
    fireEvent.error(screen.getByRole('img', { name: '资源效率 MFA 桑基图' }));

    expect(await screen.findByText('桑基图加载失败，请检查结果快照后重试。')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '重新加载' }));

    expect(screen.getByRole('img', { name: '资源效率 MFA 桑基图' })).toHaveAttribute(
      'src',
      '/api/mfa/sankey.svg?retry=1',
    );
    expect(screen.getByRole('link', { name: /打开全图/ })).toHaveAttribute(
      'href',
      '/api/mfa/sankey.svg',
    );
  });
  it('shows chart controls in English without changing the frozen SVG URL', async () => {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, 'en');
    renderViewer(<SankeyViewer src="/api/exact.svg" alt="Material flow" />);
    fireEvent.load(screen.getByRole('img', { name: 'Material flow' }));
    await userEvent.click(screen.getByRole('radio', { name: 'Zoom in' }));
    expect(screen.getByLabelText('Scrollable Sankey diagram')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open full chart' })).toHaveAttribute('href', '/api/exact.svg');
  });
});
