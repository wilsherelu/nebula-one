import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { SankeyViewer } from './SankeyViewer';
import { I18nProvider, LANGUAGE_STORAGE_KEY } from '../i18n';

afterEach(() => { cleanup(); window.localStorage.removeItem(LANGUAGE_STORAGE_KEY); });

function renderViewer(element: React.ReactElement) {
  return render(<I18nProvider>{element}</I18nProvider>);
}

describe('SankeyViewer', () => {
  it('opens the complete original SVG at a readable scale and resets when the record changes', () => {
    const { rerender } = renderViewer(<SankeyViewer src="/api/first.svg" alt="MFA" defaultZoom="detail" readableScale={1.2} />);
    const image = screen.getByRole('img', { name: 'MFA' });
    Object.defineProperty(image, 'naturalWidth', { value: 3024 });
    fireEvent.load(image);
    expect(image).toHaveStyle({ width: '3629px' });
    expect(screen.getByRole('radio', { name: '可读比例' })).toBeChecked();
    rerender(<I18nProvider><SankeyViewer src="/api/second.svg" alt="MFA" defaultZoom="detail" readableScale={1.2} /></I18nProvider>);
    expect(screen.getByRole('img')).toHaveAttribute('src', '/api/second.svg');
    expect(screen.getByLabelText('正在加载')).toBeInTheDocument();
  });
  it('zooms only the viewport without changing the source result', async () => {
    renderViewer(<SankeyViewer src="/api/exact.svg" alt="MFA" />);
    const image = screen.getByRole('img', { name: 'MFA' });
    fireEvent.load(image);
    await userEvent.click(screen.getByRole('radio', { name: '可读比例' }));
    expect(image).toHaveClass('is-enlarged');
    expect(image).toHaveAttribute('src', '/api/exact.svg');
    await userEvent.click(screen.getByRole('radio', { name: '全图概览' }));
    expect(image).not.toHaveClass('is-enlarged');
  });
  it('shows a scrollable loading state and exposes the original SVG', () => {
    renderViewer(<SankeyViewer src="/api/mfa/sankey.svg" alt="基准情景 MFA 桑基图" />);

    expect(screen.getByLabelText('正在加载')).toBeInTheDocument();
    const image = screen.getByRole('img', { name: '基准情景 MFA 桑基图' });
    fireEvent.load(image);

    expect(screen.queryByLabelText('正在加载')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /打开全图/ })).toBeInTheDocument();
    expect(screen.getByLabelText('桑基图滚动区域')).toHaveAttribute('tabindex', '0');
  });

  it('exits the in-page full chart with the floating button and Escape', async () => {
    renderViewer(<SankeyViewer src="/api/exact.svg" alt="MFA" />);
    await userEvent.click(screen.getByRole('button', { name: '打开全图' }));
    await userEvent.click(screen.getByRole('button', { name: '退出全屏' }));
    await waitFor(() => expect(screen.queryByRole('button', { name: '退出全屏' })).not.toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: '打开全图' }));
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('button', { name: '退出全屏' })).not.toBeInTheDocument());
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
    expect(screen.getByRole('button', { name: /打开全图/ })).toBeInTheDocument();
  });
  it('shows chart controls in English without changing the frozen SVG URL', async () => {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, 'en');
    renderViewer(<SankeyViewer src="/api/exact.svg" alt="Material flow" />);
    fireEvent.load(screen.getByRole('img', { name: 'Material flow' }));
    await userEvent.click(screen.getByRole('radio', { name: 'Readable scale' }));
    expect(screen.getByLabelText('Scrollable Sankey diagram')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Open full chart' })).toBeInTheDocument();
  });
});
