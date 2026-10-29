import { Button, Checkbox, Input, Modal, Select, Table } from '@arco-design/web-react';
import { useMemo, useState } from 'react';
import type { CalculationMethodRule, MethodCategory, MethodDimension, ProjectWorkspace } from '../../api/types';
import { useI18n } from '../../i18n';
import { EmptyState, ErrorState, LoadingState } from '../../components/ui/States';
import { useNarrowViewport } from '../../hooks/useNarrowViewport';
import { directionText, ruleIdentity } from './labels';
import { buildScopeRows, contributionDomainOf, exchangeIdOf, modelPorts, processEntries, type ScopeRow } from './flowRows';

/** The one category tree a caliber declares. A result-category caliber groups only through an
 * assigned leaf; a legacy tag scheme keeps its old presence reading and stays read-only. */
export const tagDimensionOf = (dimensions: MethodDimension[]): MethodDimension =>
  dimensions[0] ?? { id: 'result_category', name: '', categories: [] };

export const categoryName = (category: MethodCategory): string => category.name?.trim() || category.id;

const leafCategories = (dimension: MethodDimension): MethodCategory[] =>
  dimension.categories.filter(category => category.is_leaf !== false);

const nextCategoryId = (categories: MethodCategory[]): string => {
  const taken = new Set(categories.map(category => category.id));
  let index = 1;
  while (taken.has(`result_category_${index}`)) index += 1;
  return `result_category_${index}`;
};

const matchedRulesIn = (rules: CalculationMethodRule[], dimensionId: string, categoryId: string): CalculationMethodRule[] =>
  rules.filter(rule => (rule.categories ?? {})[dimensionId] === categoryId);

/** The dropdown's "no relation" value: the flow simply stays outside this caliber. */
const NONE_VALUE = '';

/** Author the scheme's single category tree. Category ids are the stable save keys and are never
 * editable; renaming changes only the label a rule rolls up under. */
function CategoryManager({ dimension, rules, editable, onChange, updateRule, removeRule }: {
  dimension: MethodDimension;
  rules: CalculationMethodRule[];
  editable: boolean;
  onChange: (next: MethodDimension) => void;
  updateRule: (identity: string, patch: Partial<CalculationMethodRule>) => void;
  removeRule: (identity: string) => void;
}) {
  const { t } = useI18n();
  const [deleting, setDeleting] = useState<MethodCategory | null>(null);
  const [deleteTarget, setDeleteTarget] = useState('');
  const categories = dimension.categories;
  const apply = (next: MethodCategory[]) => onChange({ ...dimension, categories: next });
  const hasChildren = (id: string) => categories.some(category => category.parent_id === id);
  const matchedCount = (id: string) => matchedRulesIn(rules, dimension.id, id).length;

  const addCategory = (parentId: string | null) => {
    const id = nextCategoryId(categories);
    apply([
      ...categories.map(category => category.id === parentId ? { ...category, is_leaf: false } : category),
      { id, name: '', parent_id: parentId, is_leaf: true },
    ]);
  };

  const patchCategory = (id: string, patch: Partial<MethodCategory>) => {
    const next = categories.map(category => category.id === id ? { ...category, ...patch } : category);
    const parents = new Set(next.map(category => category.parent_id).filter(Boolean));
    apply(next.map(category => ({ ...category, is_leaf: !parents.has(category.id) })));
  };

  const confirmDelete = () => {
    if (!deleting) return;
    const affected = matchedRulesIn(rules, dimension.id, deleting.id);
    for (const rule of affected) {
      if (deleteTarget) updateRule(ruleIdentity(rule), { categories: { ...rule.categories, [dimension.id]: deleteTarget } });
      else removeRule(ruleIdentity(rule));
    }
    const remaining = categories.filter(category => category.id !== deleting.id);
    const parents = new Set(remaining.map(category => category.parent_id).filter(Boolean));
    apply(remaining.map(category => ({ ...category, is_leaf: !parents.has(category.id) })));
    setDeleting(null);
    setDeleteTarget('');
  };
  return <section className="tag-scheme__category-inline" aria-label={t('cm.tagCategories')}>
    <div className="tag-scheme__cat-list">
      {categories.map(category => <div className="tag-scheme__cat-row" key={category.id}>
        <Input size="small" aria-label={t('cm.tagCategoryName')} value={category.name ?? ''}
          disabled={!editable} placeholder={t('cm.tagCategoryName')} onChange={value => patchCategory(category.id, { name: value })} />
        <small className="helper-text">{t('cm.tagMatchedCount', { count: matchedCount(category.id) })}</small>
        <Button size="mini" type="text" status="danger"
          disabled={!editable || hasChildren(category.id)} onClick={() => setDeleting(category)}>{t('cm.tagCategoryDelete')}</Button>
      </div>)}
    </div>
    {!categories.length ? <p className="helper-text">{t('cm.tagNoCategories')}</p> : null}
    {editable ? <Button type="outline" size="small" onClick={() => addCategory(null)}>{t('cm.tagAddCategory')}</Button> : null}

    <Modal className="draft-switch-modal" title={t('cm.tagDeleteTitle')} visible={!!deleting} style={{ maxWidth: 'calc(100vw - 32px)' }}
      onCancel={() => { setDeleting(null); setDeleteTarget(''); }}
      footer={<div className="form-actions">
        <Button onClick={() => { setDeleting(null); setDeleteTarget(''); }}>{t('cm.createCancel')}</Button>
        <Button type="primary" onClick={confirmDelete}>{t('cm.tagDeleteConfirm')}</Button>
      </div>}>
      <p>{t('cm.tagDeleteBody', { name: deleting ? categoryName(deleting) : '', count: deleting ? matchedCount(deleting.id) : 0 })}</p>
      <div className="project-field"><span>{t('cm.tagDeleteTarget')}</span>
        <Select value={deleteTarget} aria-label={t('cm.tagDeleteTarget')} onChange={setDeleteTarget}
          options={[{ value: '', label: t('cm.tagNone') }, ...leafCategories(dimension)
            .filter(category => category.id !== deleting?.id)
            .map(category => ({ value: category.id, label: categoryName(category) }))]} />
      </div>
    </Modal>
  </section>;
}

/** The result-category workspace: the category definition sits above the flow table, and every
 * flow row carries one relation dropdown ("无" plus the declared leaves). "无" removes the rule, so
 * the flow simply stays outside this caliber and untouched by the default LCIA. A legacy scheme
 * with the same layout stays read-only: it shows its old presence/pending reading verbatim. */
export function TagSchemeEditor({ graph, workspace, loading, error, editable, legacy = false, rules, dimensions, onDimensions, addRule, updateRule, removeRule }: {
  graph?: Record<string, unknown>;
  workspace: ProjectWorkspace | undefined;
  loading: boolean;
  error: unknown;
  editable: boolean;
  legacy?: boolean;
  rules: CalculationMethodRule[];
  dimensions: MethodDimension[];
  onDimensions: (next: MethodDimension[]) => void;
  addRule: (rule: CalculationMethodRule) => void;
  updateRule: (identity: string, patch: Partial<CalculationMethodRule>) => void;
  removeRule: (identity: string) => void;
}) {
  const { t } = useI18n();
  const dimension = tagDimensionOf(dimensions);
  const leaves = leafCategories(dimension);
  const ports = useMemo(() => modelPorts(graph, workspace), [graph, workspace]);
  const processes = useMemo(() => processEntries(rules, ports), [rules, ports]);
  const [current, setCurrent] = useState<string | null>(null);
  const [processSearch, setProcessSearch] = useState('');
  const [keyword, setKeyword] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');
  const [selection, setSelection] = useState<string[]>([]);
  const [batchCategory, setBatchCategory] = useState(NONE_VALUE);
  const [firstCategory, setFirstCategory] = useState('');
  const [detailRow, setDetailRow] = useState<ScopeRow | null>(null);
  const narrow = useNarrowViewport();
  const compactNavigation = useNarrowViewport(1100);
  const needsCategories = editable && !leaves.length;

  const processId = current ?? processes[0]?.id ?? null;
  const processName = processes.find(item => item.id === processId)?.name ?? processId ?? '';
  const rows = useMemo(() => (processId ? buildScopeRows(processId, rules, ports) : []), [processId, rules, ports]);
  const isMatchable = (row: ScopeRow) =>
    row.direction === 'emission' || row.direction === 'resource' || (row.direction === 'input' && !row.internal);
  const categoryOf = (row: ScopeRow) => (row.rule?.categories ?? {})[dimension.id] ?? NONE_VALUE;
  const matched = (row: ScopeRow) => !!row.rule;
  const filtered = useMemo(() => {
    const needle = keyword.trim().toLowerCase();
    return rows.filter(row => (!needle || row.haystack.includes(needle))
      && (categoryFilter !== 'none' || (isMatchable(row) && !matched(row)))
      && (categoryFilter === '' || categoryFilter === 'none' || categoryOf(row) === categoryFilter));
  }, [rows, keyword, categoryFilter]);
  const selectedSet = new Set(selection);
  const selectedRows = filtered.filter(row => selectedSet.has(row.identity) && isMatchable(row));

  const applyRule = (row: ScopeRow, categoryId: string) => {
    if (!isMatchable(row) || !categoryId) return;
    const categories = { [dimension.id]: categoryId };
    if (row.rule) updateRule(row.identity, { boundary_status: 'selected', categories });
    else addRule({
      process_instance_id: row.processId,
      exchange_id: row.portId ? exchangeIdOf({ processId: row.processId, portId: row.portId }) : null,
      flow_uuid: row.flowUuid,
      direction: row.direction,
      boundary_status: 'selected',
      location_role: 'other',
      scope: null,
      cbam_relevant: false,
      classification_basis: 'user',
      schema_version: 1,
      contribution_target: contributionDomainOf(row),
      categories,
    });
  };
  const clearRule = (row: ScopeRow) => { if (row.rule) removeRule(row.identity); };
  const setRowCategory = (row: ScopeRow, value: string) =>
    value ? applyRule(row, value) : clearRule(row);
  const applyBatch = (categoryId: string) => {
    for (const row of selectedRows) {
      if (categoryId) applyRule(row, categoryId);
      else clearRule(row);
    }
    setSelection([]);
    setBatchCategory(NONE_VALUE);
  };
  const toggleSelection = (row: ScopeRow, checked: boolean) =>
    setSelection(previous => checked ? [...previous, row.identity] : previous.filter(item => item !== row.identity));
  const addFirstCategory = () => {
    const name = firstCategory.trim();
    if (!name) return;
    onDimensions([{ ...dimension, categories: [...dimension.categories, { id: nextCategoryId(dimension.categories), name, is_leaf: true }] }]);
    setFirstCategory('');
  };

  if (error) return <ErrorState error={error} />;
  if (loading) return <LoadingState />;
  const needle = processSearch.trim().toLowerCase();
  const visibleProcesses = processes.filter(item => !needle || `${item.name} ${item.id}`.toLowerCase().includes(needle));
  const leafOptions = leaves.map(category => ({ value: category.id, label: categoryName(category) }));
  const categoryTitle = (row: ScopeRow) => {
    const id = categoryOf(row);
    if (id) return leaves.find(category => category.id === id)?.name || id;
    if (legacy) return row.rule ? t('cm.tagMatchedNoCategory') : t('cm.tagUnmatched');
    return t('cm.tagNone');
  };
  const renderMatch = (row: ScopeRow) => {
    if (!isMatchable(row)) return '—';
    if (!editable) return categoryTitle(row);
    return <Select size="small" aria-label={t('cm.tagRowCategory')} value={categoryOf(row)} style={{ width: 160 }}
      onChange={value => setRowCategory(row, value)}
      options={[{ value: NONE_VALUE, label: t('cm.tagNone') }, ...leafOptions]} />;
  };
  const flowLabel = (row: ScopeRow) => <span>{row.flowLabel || row.identity}
    {ports.find(port => port.processId === row.processId && port.portId === row.portId)?.description ?
      <small className="tag-scheme__flow-source">{ports.find(port => port.processId === row.processId && port.portId === row.portId)?.description}</small> : null}
    <span className="method-scope__flow-meta">{row.unit ? <small>{row.unit}</small> : null}
      <small className="method-scope__kind">{directionText(t, row.direction)}</small>
      {legacy && row.rule?.boundary_status === 'pending' ? <small className="method-scope__kind method-scope__kind--gap">{t('cm.tagPending')}</small> : null}
    </span></span>;
  const renderDetailButton = (row: ScopeRow) => <Button size="mini" type="text" onClick={() => setDetailRow(row)}>{t('cm.tagRowDetail')}</Button>;

  return <div className="tag-scheme">
    <section className="tag-scheme__definition" aria-label={t('cm.tagCategories')}>
      <div className="tag-scheme__definition-head">
        <strong>{t('cm.tagCategories')}</strong>
        <div className="tag-scheme__chips">
          {leaves.map(category => <span className="tag-scheme__chip" key={category.id}>
            {categoryName(category)}
            <small>{matchedRulesIn(rules, dimension.id, category.id).length}</small>
          </span>)}
          {!leaves.length ? <span className="helper-text">{t('cm.tagNoCategoryHint')}</span> : null}
        </div>
      </div>
    </section>
    {editable && !needsCategories ? <CategoryManager dimension={dimension} rules={rules} editable={editable}
      onChange={next => onDimensions([next])} updateRule={updateRule} removeRule={removeRule} /> : null}

    {needsCategories ? <section className="tag-scheme__empty">
      <strong>{t('cm.tagFirstCategoryTitle')}</strong>
      <p className="helper-text">{t('cm.tagFirstCategoryBody')}</p>
      <div className="tag-scheme__quick-add">
        <Input autoFocus value={firstCategory} onChange={setFirstCategory} aria-label={t('cm.tagCategoryName')}
          placeholder={t('cm.tagCategoryName')} maxLength={120} onPressEnter={addFirstCategory} />
        <Button type="primary" disabled={!firstCategory.trim()} onClick={addFirstCategory}>{t('cm.tagAddCategory')}</Button>
      </div>
    </section> : <div className="method-scope">
      {compactNavigation ? <Select className="tag-scheme__process-select" aria-label={t('cm.currentProcess')} value={processId ?? undefined}
        showSearch options={processes.map(item => ({value: item.id, label: item.name}))}
        onChange={value => { setCurrent(value); setSelection([]); }} /> : <aside className="method-scope__nav">
        <div className="method-scope__nav-head">
          <Input allowClear size="small" aria-label={t('cm.processSearch')} placeholder={t('cm.processSearch')}
            value={processSearch} onChange={setProcessSearch} />
        </div>
        <ul className="method-scope__process-list">
          {visibleProcesses.map(item => <li key={item.id}>
            <button type="button" className={item.id === processId ? 'is-active' : ''}
              onClick={() => { setCurrent(item.id); setSelection([]); }}>
              <span className="method-scope__process-name">{item.name}</span>
              <small>{t('cm.processCounts', { ports: item.portCount, modified: item.modifiedCount })}</small>
            </button>
          </li>)}
          {!visibleProcesses.length ? <li className="helper-text">{t('cm.noProcessMatch')}</li> : null}
        </ul>
      </aside>}
      <div className="method-scope__detail">
        {!processId ? <EmptyState description={t('cm.noPorts')} /> : <>
          <div className="tag-scheme__toolbar">
            <h3>{processName}</h3>
            <Input allowClear size="small" aria-label={t('cm.tagFlowSearch')} placeholder={t('cm.tagFlowSearch')}
              value={keyword} onChange={setKeyword} className="tag-scheme__search" />
            <Select size="small" value={categoryFilter} onChange={setCategoryFilter} aria-label={t('cm.tagFilterCategory')}
              style={{ width: 150 }}
              options={[{ value: '', label: t('cm.tagFilterAll') }, { value: 'none', label: t('cm.tagNone') }, ...leafOptions]} />
            {editable ? <Button size="small" type="text" onClick={() => setSelection(filtered.filter(isMatchable).map(row => row.identity))}>
              {t('cm.tagSelectVisible')}</Button> : null}
          </div>
          {!editable ? <p className="helper-text">{legacy ? t('cm.tagLegacyReadOnlyHint') : t('cm.historyReadOnly')}</p> : null}
          {editable ? <div className="calculation-method-rules__batch tag-scheme__batch">
              <span className="helper-text">{t('cm.batchSelected', { count: selectedRows.length })}</span>
              {!selectedRows.length ? <span className="helper-text">{t('cm.tagBatchHint')}</span> : null}
              <Select size="small" value={batchCategory} aria-label={t('cm.tagBatchCategory')} style={{ width: 160 }}
                onChange={setBatchCategory}
                options={[{ value: NONE_VALUE, label: t('cm.tagNone') }, ...leafOptions]} />
              <Button size="small" type="primary" disabled={!selectedRows.length} onClick={() => applyBatch(batchCategory)}>{t('cm.tagBatchApply')}</Button>
              <Button size="small" type="text" onClick={() => setSelection([])}>{t('cm.clearSelection')}</Button>
          </div> : null}
          {!rows.length ? <EmptyState description={t('cm.noPorts')} /> : !filtered.length ? <EmptyState description={t('cm.noMatches')} /> : narrow ?
            <ul className="method-scope__cards">
              {filtered.map(row => <li className="method-scope__card" key={row.identity}>
                <div className="method-scope__card-head">
                  {editable && isMatchable(row) ? <Checkbox aria-label={`${t('cm.batchSelected', { count: 1 })} ${row.flowLabel}`}
                    checked={selectedSet.has(row.identity)} onChange={(checked: boolean) => toggleSelection(row, checked)} /> : null}
                  <span className="method-scope__card-flow">{flowLabel(row)}</span>
                </div>
                <div className="method-scope__card-field"><span>{t('cm.tagRowCategory')}</span>{renderMatch(row)}</div>
                <div className="method-scope__card-field">{renderDetailButton(row)}</div>
              </li>)}
            </ul> :
            <Table className="tag-scheme__table" rowKey="identity" pagination={false} scroll={{ x: 640, y: 'calc(100dvh - 390px)' }} data={filtered}
              columns={[
                ...(editable ? [{ title: '', width: 44, align: 'center' as const,
                  render: (_: unknown, row: ScopeRow) => isMatchable(row)
                    ? <Checkbox aria-label={`${t('cm.batchSelected', { count: 1 })} ${row.flowLabel}`}
                        checked={selectedSet.has(row.identity)} onChange={(checked: boolean) => toggleSelection(row, checked)} />
                    : null }] : []),
                { title: t('cm.tagColFlow'), render: (_: unknown, row: ScopeRow) => flowLabel(row) },
                { title: t('cm.tagRowCategory'), width: 200, render: (_: unknown, row: ScopeRow) => renderMatch(row) },
                { title: t('cm.tagColDetail'), width: 96, render: (_: unknown, row: ScopeRow) => renderDetailButton(row) },
              ]} />}
          <p className="calculation-method-rules__summary">{t('cm.tagSummary', {
            total: rows.length, shown: filtered.length, assigned: rows.filter(matched).length,
          })}</p>
        </>}
      </div>
    </div>}

    <Modal className="tag-scheme__detail-modal" title={t('cm.tagRowDetail')} visible={!!detailRow} style={{ width: 480, maxWidth: 'calc(100vw - 32px)' }}
      onCancel={() => setDetailRow(null)} footer={<Button onClick={() => setDetailRow(null)}>{t('cm.tagClose')}</Button>}>
      {detailRow ? <dl className="pcf-result__facts">
        <div><dt>{t('cm.ruleProcess')}</dt><dd>{detailRow.processName}</dd></div>
        <div><dt>{t('cm.tagColFlow')}</dt><dd>{detailRow.flowLabel || detailRow.identity}</dd></div>
        <div><dt>{t('cm.filterDirection')}</dt><dd>{directionText(t, detailRow.direction)}</dd></div>
        <div><dt>{t('cm.tagUnit')}</dt><dd>{detailRow.unit || '—'}</dd></div>
        <div><dt>{t('cm.tagRowCategory')}</dt><dd>{categoryTitle(detailRow)}</dd></div>
        <div><dt>{t('cm.detailSource')}</dt><dd>{legacy ? t('cm.tagSourcePresence') : t('cm.tagSourceCategory')}</dd></div>
      </dl> : null}
    </Modal>
  </div>;
}
