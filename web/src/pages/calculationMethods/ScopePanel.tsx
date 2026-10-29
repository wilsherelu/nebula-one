import { Button, Checkbox, Input, Modal, Select, Table } from '@arco-design/web-react';
import { useMemo, useState } from 'react';
import type { CalculationMethodRule, MethodDimension, ProjectWorkspace } from '../../api/types';
import { useI18n } from '../../i18n';
import type { MessageKey } from '../../i18n';
import { EmptyState, ErrorState, LoadingState } from '../../components/ui/States';
import { useNarrowViewport } from '../../hooks/useNarrowViewport';
import { BOUNDARIES, DIRECTIONS, LOCATIONS, SCOPES, SCOPE_LOCATION, boundaryText, directionText, domainText, locationText, scopeText } from './labels';
import { DimensionsEditor } from './MethodPanels';
import { buildScopeRows, contributionDomainOf, exchangeIdOf, isContributionRow, modelPorts, processDefaultRows, processEntries, type ScopeRow } from './flowRows';

const SOURCE_KEYS: Record<ScopeRow['source'], MessageKey> = {
  override: 'cm.source.override',
  process_default: 'cm.source.processDefault',
  unset: 'cm.source.unset',
  process_default_rule: 'cm.source.processDefaultRule',
  port_missing: 'cm.source.portMissing',
};

/** Whether a row's chosen Scope contradicts its evidence-based location role. The location is a
 * source fact the reader sets on demand; the editor flags the mismatch instead of silently
 * fabricating a purchased-energy location just because Scope 2 was picked (plan §115). */
const locationConflict = (row: ScopeRow): boolean => {
  const scope = row.effective?.scope ?? null;
  if (!scope || (row.effective?.boundary_status ?? 'pending') === 'excluded') return false;
  const required = SCOPE_LOCATION[scope];
  return !!required && (row.effective?.location_role ?? 'other') !== required;
};

/**
 * The unified accounting editor: a process navigation on the left, every exchange of the selected
 * process on the right, each row carrying the single 是否计入 toggle and its result classification
 * (Scope 1–3 or a custom category) side by side.
 *
 * Rows exist for ports nobody has set a rule for yet, so the reader works from the real inventory.
 * A row without its own rule shows what it inherits; changing it creates exactly one per-flow
 * override. Location role, contribution domain, rule source and the derived CBAM relevance are not
 * persistent columns — they live in each row's on-demand detail so the first screen stays compact.
 */
export function ScopePanel({ graph, workspace, loading, error, editable, rules, dimensions, onDimensions, onEdit, onRemove }: {
  graph?: Record<string, unknown>;
  workspace: ProjectWorkspace | undefined;
  loading: boolean;
  error: unknown;
  editable: boolean;
  rules: CalculationMethodRule[];
  dimensions: MethodDimension[];
  onDimensions: (next: MethodDimension[]) => void;
  onEdit: (row: ScopeRow, patch: Partial<CalculationMethodRule>) => void;
  onRemove: (row: ScopeRow) => void;
}) {
  const { t } = useI18n();
  const ports = useMemo(() => modelPorts(graph, workspace), [graph, workspace]);
  // A purchased input only carries an upstream contribution once the data version mapped a
  // background provider onto that exact port; the row says which of the two it is instead of
  // implying every external input is already linked.
  const backgroundPorts = useMemo(
    () => new Map((workspace?.background_ports ?? []).map(port => [port.exchange_id, port.label])),
    [workspace],
  );
  const processes = useMemo(() => processEntries(rules, ports), [rules, ports]);
  const [current, setCurrent] = useState<string | null>(null);
  const [navOpen, setNavOpen] = useState(true);
  const [processSearch, setProcessSearch] = useState('');
  const [keyword, setKeyword] = useState('');
  const [direction, setDirection] = useState('');
  const [boundary, setBoundary] = useState('');
  const [scope, setScope] = useState('');
  const [onlyModified, setOnlyModified] = useState(false);
  const [selection, setSelection] = useState<string[]>([]);
  const [batchBoundary, setBatchBoundary] = useState('');
  const [batchConfirm, setBatchConfirm] = useState(false);
  // Below this width the per-flow table cannot show its pinned columns without sideways scrolling,
  // so the same cells render as a stacked card per flow instead (directive: no core operation may
  // require horizontal scrolling).
  const narrow = useNarrowViewport();

  const processId = current ?? processes[0]?.id ?? null;
  const processName = processes.find(item => item.id === processId)?.name ?? processId ?? '';
  const rows = useMemo(() => (processId ? buildScopeRows(processId, rules, ports) : []), [processId, rules, ports]);
  const filtered = useMemo(() => {
    const needle = keyword.trim().toLowerCase();
    return rows.filter(row =>
      (!needle || row.haystack.includes(needle))
      && (!direction || row.direction === direction)
      && (!onlyModified || row.modified)
      && (!boundary || (row.effective?.boundary_status ?? 'pending') === boundary)
      && (!scope || (scope === 'none' ? (row.effective?.scope ?? null) === null : row.effective?.scope === scope)));
  }, [rows, keyword, direction, boundary, scope, onlyModified]);

  const customDims = dimensions.filter(dim => dim.id !== 'lc_scope');
  // Historical process defaults are resolved server-side into `effective`; the editor only lists
  // them read-only below the table and never authors a new implicit default (§2.2).
  const processDefaults = useMemo(
    () => (processId ? processDefaultRows(processId, rules) : []),
    [processId, rules],
  );
  const appliesTo = (row: ScopeRow) => processDefaults.some(item => item.direction === row.direction
    && (item.rule?.contribution_target ?? 'direct') === contributionDomainOf(row));
  const selectedSet = new Set(selection);
  const selectedRows = filtered.filter(row => isContributionRow(row) && selectedSet.has(row.identity));

  if (error) return <ErrorState error={error} />;
  if (loading) return <LoadingState />;

  const needle = processSearch.trim().toLowerCase();
  const visibleProcesses = processes.filter(item => !needle || `${item.name} ${item.id}`.toLowerCase().includes(needle));

  const setCategory = (row: ScopeRow, dimId: string, value: string) => {
    const categories = { ...(row.effective?.categories ?? {}) };
    if (value) categories[dimId] = value; else delete categories[dimId];
    onEdit(row, { categories });
  };

  const applyBatch = () => {
    const patch: Partial<CalculationMethodRule> = { boundary_status: batchBoundary as CalculationMethodRule['boundary_status'] };
    selectedRows.forEach(row => onEdit(row, patch));
    setBatchConfirm(false);
    setSelection([]);
    setBatchBoundary('');
  };

  const selectProcess = (id: string) => { setCurrent(id); setSelection([]); };
  const selectWholeProcess = () => setSelection(filtered.filter(row => editable && isContributionRow(row)).map(row => row.identity));
  const flowKind = (row: ScopeRow): MessageKey => row.direction === 'emission' || row.direction === 'resource'
    ? 'cm.flow.elementary' : row.internal ? 'cm.flow.internal' : row.direction === 'input' ? 'cm.flow.background' : 'cm.flow.product';
  const linkState = (row: ScopeRow) => {
    if (row.direction !== 'input' || row.internal || !row.portId) return null;
    const provider = backgroundPorts.get(exchangeIdOf({ processId: row.processId, portId: row.portId }));
    return provider === undefined
      ? { key: 'cm.flow.unlinked' as MessageKey, provider: '' }
      : { key: 'cm.flow.linked' as MessageKey, provider };
  };

  const detail = (row: ScopeRow) => <div className="method-scope__detail-panel">
    <div className="method-scope__detail-item">
      <span className="method-scope__detail-label">{t('cm.detailSource')}</span>
      <span>{t(SOURCE_KEYS[row.source])}</span>
    </div>
    <div className="method-scope__detail-item">
      <span className="method-scope__detail-label">{t('cm.detailDomain')}</span>
      <span>{domainText(t, contributionDomainOf(row))}</span>
    </div>
    <div className="method-scope__detail-item">
      <span className="method-scope__detail-label">{t('cm.detailLocation')}</span>
      {editable && isContributionRow(row)
        ? <Select size="small" aria-label={t('cm.ruleLocation')} style={{ width: 200 }}
          value={row.effective?.location_role ?? 'other'}
          onChange={(value: CalculationMethodRule['location_role']) => onEdit(row, { location_role: value })}
          options={LOCATIONS.map(item => ({ value: item, label: locationText(t, item) }))} />
        : <span>{locationText(t, row.effective?.location_role ?? 'other')}</span>}
    </div>
    <div className="method-scope__detail-item">
      <span className="method-scope__detail-label">{t('cm.detailCbam')}</span>
      <span>{row.effective?.cbam_relevant ? t('cm.boundary.selected') : '—'}
        <small className="helper-text"> · {t('cm.detailCbamDerived')}</small></span>
    </div>
    {locationConflict(row) ? <p className="method-scope__conflict helper-text">{t('cm.locationConflict')}</p> : null}
  </div>;

  // Every cell renderer is shared by the wide table and the narrow card list, so the two layouts can
  // never drift into offering different operations.
  const cellWidth = (wide: number) => (narrow ? { width: '100%' } : { width: wide });
  const renderCheckbox = (row: ScopeRow) => <Checkbox aria-label={`${t('cm.batchSelected', { count: 1 })} ${row.flowLabel}`}
    disabled={!isContributionRow(row)}
    checked={selectedSet.has(row.identity)}
    onChange={(checked: boolean) => setSelection(previous => checked ? [...previous, row.identity] : previous.filter(item => item !== row.identity))} />;
  const renderFlow = (row: ScopeRow) => {
    const link = linkState(row);
    return <span>{row.flowLabel || row.identity}
      <span className="method-scope__flow-meta">{row.unit ? <small>{row.unit}</small> : null}
      <small className="method-scope__kind" title={t(flowKind(row))}>{t(`${flowKind(row)}.short` as MessageKey)}</small>
      {link ? <small className={link.key === 'cm.flow.linked' ? 'method-scope__kind method-scope__kind--linked' : 'method-scope__kind method-scope__kind--gap'}>
        <span title={`${t(link.key)}${link.provider ? ` (${link.provider})` : ''}`}>{t(`${link.key}.short` as MessageKey)}</span></small> : null}</span></span>;
  };
  const renderBoundary = (row: ScopeRow) => !isContributionRow(row) ? '—' : editable
    ? <Select size="small" value={row.effective?.boundary_status ?? 'pending'} aria-label={t('cm.ruleBoundary')} style={cellWidth(110)}
      onChange={(value: CalculationMethodRule['boundary_status']) => onEdit(row, { boundary_status: value })}
      options={BOUNDARIES.map(item => ({ value: item, label: boundaryText(t, item) }))} />
    : boundaryText(t, row.effective?.boundary_status ?? 'pending');
  const renderScope = (row: ScopeRow) => !isContributionRow(row) ? '—' : editable
    ? <Select size="small" value={row.effective?.scope ?? ''} aria-label={t('cm.ruleScope')} style={cellWidth(130)}
      onChange={(value: string) => onEdit(row, { scope: (value || null) as CalculationMethodRule['scope'] })}
      options={[{ value: '', label: t('cm.scope.none') }, ...SCOPES.map(item => ({ value: item, label: scopeText(t, item) }))]} />
    : scopeText(t, row.effective?.scope ?? null);
  const renderDimension = (dim: MethodDimension, row: ScopeRow) => {
    const leaves = dim.categories.filter(cat => cat.is_leaf !== false);
    const value = row.effective?.categories?.[dim.id] ?? '';
    if (!isContributionRow(row)) return '—';
    if (!editable) return value ? (leaves.find(cat => cat.id === value)?.name || value) : t('cm.category.none');
    return <Select size="small" value={value} aria-label={dim.name || dim.id} style={cellWidth(140)}
      onChange={(next: string) => setCategory(row, dim.id, next)}
      options={[{ value: '', label: t('cm.category.none') }, ...leaves.map(cat => ({ value: cat.id, label: cat.name || cat.id }))]} />;
  };
  const renderActions = (row: ScopeRow) => row.rule
    ? <Button type="text" size="mini" onClick={() => onRemove(row)}>
      {t(row.source === 'override' && appliesTo(row) ? 'cm.restoreDefault' : 'cm.removeRule')}
    </Button>
    : null;

  return <div className="method-scope">
    <aside className={navOpen ? 'method-scope__nav' : 'method-scope__nav method-scope__nav--collapsed'}>
      <div className="method-scope__nav-head">
        <Input allowClear size="small" aria-label={t('cm.processSearch')} placeholder={t('cm.processSearch')}
          value={processSearch} onChange={setProcessSearch} />
        <Button type="text" size="mini" onClick={() => setNavOpen(value => !value)}>
          {t(navOpen ? 'cm.collapseProcesses' : 'cm.expandProcesses')}
        </Button>
      </div>
      {navOpen ? <ul className="method-scope__process-list">
        {visibleProcesses.map(item => <li key={item.id}>
          <button type="button" className={item.id === processId ? 'is-active' : ''} onClick={() => selectProcess(item.id)}>
            <span className="method-scope__process-name">{item.name}</span>
            <small>{t('cm.processCounts', { ports: item.portCount, modified: item.modifiedCount })}</small>
          </button>
        </li>)}
        {!visibleProcesses.length ? <li className="helper-text">{t('cm.noProcessMatch')}</li> : null}
      </ul> : null}
    </aside>
    <div className="method-scope__detail">
      {!processId ? <EmptyState description={t('cm.noPorts')} /> : <>
        <div className="method-scope__head">
          <h3>{t('cm.currentProcess')}: {processName}</h3>
          {!editable ? <p className="helper-text">{t('cm.historyReadOnly')}</p> : <p className="helper-text">{t('cm.editHint')}</p>}
        </div>
        <div className="calculation-method-rules__filters">
          <Input allowClear placeholder={t('cm.filterKeyword')} value={keyword} onChange={setKeyword} style={{ minWidth: 200 }} />
          <Select value={direction} onChange={setDirection} aria-label={t('cm.filterDirection')} style={{ width: 130 }}
            options={[{ value: '', label: `${t('cm.filterDirection')} · ${t('cm.all')}` }, ...DIRECTIONS.map(item => ({ value: item, label: directionText(t, item) }))]} />
          <Select value={boundary} onChange={setBoundary} aria-label={t('cm.filterStatus')} style={{ width: 160 }}
            options={[{ value: '', label: `${t('cm.filterStatus')} · ${t('cm.all')}` }, ...BOUNDARIES.map(item => ({ value: item, label: boundaryText(t, item) }))]} />
          <Select value={scope} onChange={setScope} aria-label={t('cm.filterScope')} style={{ width: 170 }}
            options={[{ value: '', label: `${t('cm.filterScope')} · ${t('cm.all')}` }, { value: 'none', label: t('cm.scope.none') }, ...SCOPES.map(item => ({ value: item, label: scopeText(t, item) }))]} />
          <Checkbox checked={onlyModified} onChange={setOnlyModified}>{t('cm.onlyModified')}</Checkbox>
        </div>
        {editable ? <div className="calculation-method-rules__batch">
          <Button size="small" type="text" onClick={selectWholeProcess}>{t('cm.selectAllProcess')}</Button>
          {selection.length ? <>
            <span className="helper-text">{t('cm.batchSelected', { count: selection.length })}</span>
            <Select value={batchBoundary} onChange={setBatchBoundary} aria-label={t('cm.batchBoundary')} size="small" style={{ width: 160 }}
              placeholder={t('cm.batchBoundary')} options={BOUNDARIES.map(item => ({ value: item, label: boundaryText(t, item) }))} />
            <Button size="small" type="primary" disabled={!batchBoundary} onClick={() => setBatchConfirm(true)}>{t('cm.batchApply')}</Button>
            <Button size="small" type="text" onClick={() => setSelection([])}>{t('cm.clearSelection')}</Button>
          </> : null}
        </div> : null}
        {!rows.length ? <EmptyState description={t('cm.noPorts')} /> : !filtered.length ? <EmptyState description={t('cm.noMatches')} /> : narrow ?
          <ul className="method-scope__cards">
            {filtered.map(row => <li className="method-scope__card" key={row.identity}>
              <div className="method-scope__card-head">
                {editable ? renderCheckbox(row) : null}
                <span className="method-scope__card-flow">{renderFlow(row)}</span>
              </div>
              <div className="method-scope__card-field"><span>{t('cm.ruleBoundary')}</span>{renderBoundary(row)}</div>
              <div className="method-scope__card-field"><span>{t('cm.ruleScope')}</span>{renderScope(row)}</div>
              {customDims.map(dim => <div className="method-scope__card-field" key={dim.id}>
                <span>{dim.name || dim.id}</span>{renderDimension(dim, row)}</div>)}
              <details className="method-scope__row-detail">
                <summary>{t('cm.ruleDetail')}</summary>
                {detail(row)}
              </details>
              {editable && row.rule ? <div className="method-scope__card-field">{renderActions(row)}</div> : null}
            </li>)}
          </ul> :
          <Table rowKey="identity" pagination={false} scroll={{ x: 900, y: 420 }} data={filtered}
            columns={[
              ...(editable ? [{ title: '', width: 44, align: 'center' as const, fixed: 'left' as const,
                render: (_: unknown, row: ScopeRow) => renderCheckbox(row) }] : []),
              { title: t('cm.ruleFlow'), dataIndex: 'flowLabel', width: 220, fixed: 'left' as const,
                render: (_: unknown, row: ScopeRow) => renderFlow(row) },
              { title: t('cm.ruleBoundary'), width: 130, fixed: 'left' as const,
                render: (_: unknown, row: ScopeRow) => renderBoundary(row) },
              { title: t('cm.ruleScope'), width: 150, fixed: 'left' as const,
                render: (_: unknown, row: ScopeRow) => renderScope(row) },
              ...customDims.map(dim => ({ title: dim.name || dim.id, width: 160,
                render: (_: unknown, row: ScopeRow) => renderDimension(dim, row) })),
              { title: t('cm.ruleDetail'), width: 130, render: (_: unknown, row: ScopeRow) =>
                <details className="method-scope__row-detail">
                  <summary>{t('cm.ruleDetail')}</summary>
                  {detail(row)}
                </details> },
              ...(editable ? [{ title: '', width: 120,
                render: (_: unknown, row: ScopeRow) => renderActions(row) }] : []),
            ]} />}
        <p className="calculation-method-rules__summary">{t('cm.scopeSummary', { total: rows.length, shown: filtered.length })}</p>
        {processDefaults.length ? <section className="method-scope__defaults method-scope__defaults--readonly">
          <h4>{t('cm.processDefaultTitle')}</h4>
          <p className="helper-text">{t('cm.processDefaultReadOnly')}</p>
          <ul>{processDefaults.map(row => <li key={row.identity}>
            <span>{directionText(t, row.direction)}</span>
            <span className="method-scope__default-domain">{domainText(t, row.rule?.contribution_target)}</span>
            <span>{boundaryText(t, row.rule?.boundary_status ?? 'pending')}</span>
            {editable ? <Button type="text" size="mini" onClick={() => onRemove(row)}>{t('cm.removeRule')}</Button> : null}
          </li>)}</ul>
        </section> : null}
        <section className="method-scope__dimensions">
          <h4>{t('cm.dimTitle')}</h4>
          <DimensionsEditor dimensions={dimensions} editable={editable} onChange={onDimensions} />
        </section>
      </>}
    </div>
    <Modal className="draft-switch-modal" title={t('cm.batchConfirmTitle')} visible={batchConfirm}
      onCancel={() => setBatchConfirm(false)}
      footer={<div className="form-actions">
        <Button onClick={() => setBatchConfirm(false)}>{t('cm.createCancel')}</Button>
        <Button type="primary" onClick={applyBatch}>{t('cm.batchConfirm')}</Button>
      </div>}>
      <p>{t('cm.batchConfirmBody', { process: processName, count: selectedRows.length, value: boundaryText(t, batchBoundary) })}</p>
      <p className="helper-text">{t('cm.batchImpact', { count: selectedRows.length })}</p>
    </Modal>
  </div>;
}
