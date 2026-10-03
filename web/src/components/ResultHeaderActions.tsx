import { createContext, useContext, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { Button, Dropdown, Menu } from '@arco-design/web-react';
import { IconDown } from '@arco-design/web-react/icon';
import { useI18n } from '../i18n';

export const ResultActionsTarget = createContext<HTMLElement | null>(null);
export const ResultDetailsTarget = createContext<HTMLElement | null>(null);
export function ResultDetails({ children }: { children: ReactNode }) {
  const target = useContext(ResultDetailsTarget);
  return target ? createPortal(children, target) : null;
}

export function ResultHeaderActions({ children }: { children: ReactNode }) {
  const target = useContext(ResultActionsTarget);
  return target ? createPortal(children, target) : <div className="result-inline-actions">{children}</div>;
}

export function ResultExportMenu({ actions, disabled = false }: {
  actions: Array<{ key: string; label: string; run: () => void }>; disabled?: boolean;
}) {
  const { t } = useI18n();
  return <Dropdown trigger="click" droplist={<Menu onClickMenuItem={key => actions.find(action => action.key === key)?.run()}>
    {actions.map(action => <Menu.Item key={action.key}>{action.label}</Menu.Item>)}
  </Menu>}><Button type="outline" size="small" disabled={disabled}>{t('results.export')} <IconDown /></Button></Dropdown>;
}
