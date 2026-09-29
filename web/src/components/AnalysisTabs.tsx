import { Select } from '@arco-design/web-react';
import { Children, isValidElement, type ReactElement, type ReactNode } from 'react';

// The four release tasks are shown as peer tabs; the organisation variants belong to the same
// organisation task family, so they stay in the primary list rather than the overflow picker.
const coreOrder = ['mfa', 'pcf', 'climate', 'organization-lifecycle', 'organization-period', 'organization-ghg', 'cbam', 'scenario'];

/** Navigation keys only: labels remain owned by the existing domain panes. */
export function AnalysisTabs({ children, activeTab, onChange, allowedKeys, singleTask = false }: {
  children: ReactNode; activeTab: string; onChange: (key: string) => void; allowedKeys?: string[]; singleTask?: boolean;
}) {
  const panes: Array<ReactElement<{ title: string; children?: ReactNode }>> = [];
  Children.forEach(children, (child) => {
    if (isValidElement<{ title: string; children?: ReactNode }>(child) && (!allowedKeys || allowedKeys.includes(String(child.key)))) panes.push(child);
  });
  const extra = panes.filter((pane) => !coreOrder.includes(String(pane.key)));
  const ordered = coreOrder.flatMap((key) => panes.filter((pane) => pane.key === key));
  const selectedExtra = extra.find((pane) => pane.key === activeTab);
  const picker = <div className="result-extra-picker"><label htmlFor="extended-analysis">更多分析</label>
      <Select id="extended-analysis" aria-label="更多分析" placeholder="选择其他分析" value={selectedExtra ? activeTab : undefined}
        options={extra.map((pane) => ({ value: String(pane.key), label: pane.props.title }))} onChange={onChange} />
    </div>;
  const selected = panes.find((pane) => pane.key === activeTab);
  if (singleTask) return <div className="result-tabs__panel">{selected?.props.children}</div>;
  return <div className="result-tabs">
    <div className="result-tabs__navigation">
      <div className="result-tabs__list" role="tablist" aria-label="结果分析">
        {ordered.map((pane) => <button key={pane.key} type="button" role="tab"
          aria-selected={pane.key === activeTab} className={pane.key === activeTab ? 'is-active' : ''}
          onClick={() => onChange(String(pane.key))}>{pane.props.title}</button>)}
        {selectedExtra ? <button type="button" role="tab" aria-selected="true" className="is-active result-tabs__extra-tab">
          {selectedExtra.props.title}</button> : null}
      </div>
      {extra.length ? picker : null}
    </div>
    <div className="result-tabs__panel" role="tabpanel">{selected?.props.children}</div>
  </div>;
}
