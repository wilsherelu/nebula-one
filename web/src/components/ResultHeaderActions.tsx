import { createContext, useContext, useEffect, useId, useMemo, useRef, useState, useCallback, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { Button, Dropdown, Menu } from '@arco-design/web-react';
import { IconDown } from '@arco-design/web-react/icon';
import { useI18n } from '../i18n';

type Action = { key: string; label: string; run: () => void; disabled?: boolean; export?: boolean };
type Entry = { owner: string; scope: string; actions: Action[] };
const MoreContext = createContext<{ scope: string; entries: Entry[]; register: (entry: Entry) => () => void } | null>(null);
export function ResultMenuProvider({ scope, children }: { scope: string; children: ReactNode }) {
  const [entries, setEntries] = useState<Entry[]>([]);
  const register = useCallback((entry: Entry) => {
    setEntries(previous => [...previous.filter(item => item.owner !== entry.owner), entry]);
    return () => setEntries(previous => previous.filter(item => item !== entry));
  }, []);
  const value = useMemo(() => ({ scope, entries, register }), [scope, entries, register]);
  return <MoreContext.Provider value={value}>{children}</MoreContext.Provider>;
}
export function ResultMenuActions({ actions, fallback }: { actions: Action[]; fallback?: ReactNode }) {
  const context = useContext(MoreContext);
  const owner = useId();
  const current = useRef(actions);
  current.current = actions;
  const signature = JSON.stringify(actions.map(({ run: _run, ...metadata }) => metadata));
  const scope = context?.scope;
  const register = context?.register;
  useEffect(() => {
    if (!register || scope === undefined) return;
    return register({ owner, scope, actions: current.current.map(action => ({ ...action,
      run: () => current.current.find(item => item.key === action.key)?.run() })) });
  }, [owner, scope, register, signature]);
  return context ? null : <>{fallback}</>;
}
export function ResultMoreMenu({ actions, triggerRef }: { actions: Action[]; triggerRef: React.RefObject<HTMLButtonElement> }) {
  const context = useContext(MoreContext);
  const { t } = useI18n();
  const [visible, setVisible] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const keyboardOpening = useRef(false);
  useEffect(() => {
    if (!visible || !keyboardOpening.current) return;
    const timer = window.setTimeout(() => menuRef.current?.querySelector<HTMLElement>('[role="menuitem"][tabindex="0"]')?.focus(), 0);
    keyboardOpening.current = false;
    return () => window.clearTimeout(timer);
  }, [visible]);
  const all = [...actions, ...(context?.entries.filter(entry => entry.scope === context.scope)
    .flatMap(entry => entry.actions.map(action => ({ ...action, key: `${entry.owner}:${action.key}` }))) ?? [])];
  return <Dropdown trigger="click" position="br" disabled={!all.length} popupVisible={visible} onVisibleChange={setVisible}
    droplist={<div ref={menuRef} onKeyDownCapture={event => {
      if (event.key === 'Enter' || event.key === ' ') {
        const item = (event.target as HTMLElement).closest<HTMLElement>('[role="menuitem"]');
        if (item && item.tabIndex !== -1) { event.preventDefault(); event.stopPropagation(); item.click(); }
      }
      if (event.key === 'Escape') { event.preventDefault(); setVisible(false); triggerRef.current?.focus({ preventScroll: true }); }
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        const items = Array.from(menuRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"][tabindex="0"]') ?? []);
        const index = items.indexOf(document.activeElement as HTMLElement);
        items[(index + (event.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length]?.focus();
      }
    }}><Menu onClickMenuItem={key => { setVisible(false); all.find(action => action.key === key)?.run(); }}>
      {all.filter(action => !action.export).map(action => <Menu.Item key={action.key} disabled={action.disabled}>{action.label}</Menu.Item>)}
      {all.some(action => action.export) ? <Menu.ItemGroup title={t('results.export')}>
        {all.filter(action => action.export).map(action => <Menu.Item key={action.key} disabled={action.disabled}>{action.label}</Menu.Item>)}
      </Menu.ItemGroup> : null}
    </Menu></div>}><Button ref={triggerRef} disabled={!all.length} type="outline" size="small" aria-haspopup="menu" aria-expanded={visible}
      onKeyDown={event => {
        if (event.key === 'Escape') { event.preventDefault(); setVisible(false); }
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
          event.preventDefault();
          if (visible) menuRef.current?.querySelector<HTMLElement>('[role="menuitem"][tabindex="0"]')?.focus({ preventScroll: true });
          else { keyboardOpening.current = true; setVisible(true); }
        }
      }}>{t('common.more')} <IconDown /></Button></Dropdown>;
}

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
  return <ResultMenuActions actions={actions.map(action => ({ ...action, disabled, export: true }))} fallback={<Dropdown trigger="click" droplist={<Menu onClickMenuItem={key => actions.find(action => action.key === key)?.run()}>
    {actions.map(action => <Menu.Item key={action.key}>{action.label}</Menu.Item>)}
  </Menu>}><Button type="outline" size="small" disabled={disabled}>{t('results.export')} <IconDown /></Button></Dropdown>} />;
}
