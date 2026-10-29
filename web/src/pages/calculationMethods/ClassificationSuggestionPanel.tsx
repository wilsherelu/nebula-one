import { Alert, Button, Checkbox, Modal, Table, Tag } from '@arco-design/web-react';
import { useQuery } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { api } from '../../api/client';
import { useI18n } from '../../i18n';
import { ErrorState, LoadingState } from '../../components/ui/States';
import type { ClassificationSuggestion } from '../../api/types';
import { directionText, scopeText } from './labels';
import { basisText, businessScopeText, confidenceText, rationaleText, suggestStatusText } from './suggestionLabels';

/** A suggestion the reader can actually apply: the backend proposed a concrete rule for it. Ports kept
 * pending, marked not applicable, or already decided by hand carry no `suggested` rule and cannot be
 * applied, so they are never silently written into the draft. */
const isActionable = (item: ClassificationSuggestion) => item.status === 'suggested' && !!item.suggested;

const shortHash = (value: string) => (value.length > 12 ? `${value.slice(0, 12)}…` : value);

/**
 * The "generate suggestions -> preview the basis -> choose what to apply" flow.
 *
 * Read-only against the server: it fetches the derived preview for one exact version and shows each
 * suggestion with its rationale, its evidence basis and the versioned package that declared any energy
 * path. Nothing is written until the reader confirms a selection; applying hands the chosen suggestions
 * back to the editor, which folds them into the local draft without overriding a rule set by hand.
 */
export function ClassificationSuggestionPanel({ methodId, version, visible, onClose, onApply }: {
  methodId: string;
  version: number;
  visible: boolean;
  onClose: () => void;
  onApply: (selected: ClassificationSuggestion[]) => void;
}) {
  const { t } = useI18n();
  const query = useQuery({
    queryKey: ['classification-suggestions', methodId, version],
    queryFn: () => api.classificationSuggestions(methodId, version),
    enabled: visible,
  });
  const suggestions = useMemo(() => query.data?.suggestions ?? [], [query.data]);
  const [selection, setSelection] = useState<string[]>([]);

  // Default-select every actionable suggestion when a fresh preview lands; the reader still has to press
  // apply, so this is a convenience default, never an auto-write.
  useEffect(() => {
    if (query.data) setSelection(query.data.suggestions.filter(isActionable).map(item => item.exchange_id));
  }, [query.data]);

  const selectedSet = new Set(selection);
  const selectedRows = suggestions.filter(item => selectedSet.has(item.exchange_id) && isActionable(item));
  const actionableIds = suggestions.filter(isActionable).map(item => item.exchange_id);
  const allSelected = actionableIds.length > 0 && actionableIds.every(id => selectedSet.has(id));

  const toggle = (exchangeId: string, checked: boolean) =>
    setSelection(previous => (checked ? [...previous, exchangeId] : previous.filter(id => id !== exchangeId)));

  const footer = <div className="form-actions">
    <span className="helper-text">{t('cm.suggest.selected', { count: selectedRows.length })}</span>
    <Button onClick={onClose}>{t('cm.suggest.close')}</Button>
    <Button type="primary" disabled={!selectedRows.length}
      onClick={() => onApply(selectedRows)}>{t('cm.suggest.apply')}</Button>
  </div>;

  return <Modal className="classification-suggestion-modal" title={t('cm.suggest.title')} visible={visible}
    onCancel={onClose} footer={footer} style={{ width: 960, maxWidth: 'calc(100vw - 32px)' }} alignCenter>
    <p className="helper-text">{t('cm.suggest.hint')}</p>
    {query.isLoading ? <LoadingState rows={4} /> : null}
    {query.error ? <ErrorState error={query.error} onRetry={() => query.refetch()} /> : null}
    {query.data ? <div className="classification-suggestion-modal__evidence">
      <h4>{t('cm.suggest.evidence')}</h4>
      <p className="helper-text">{t('cm.suggest.evidenceGraph', { hash: shortHash(query.data.graph_content_sha256) })}</p>
      {query.data.energy_packages.length
        ? <ul>{query.data.energy_packages.map(pkg => <li key={`${pkg.package_id}@${pkg.version}`}>
          {t('cm.suggest.evidencePackage', {
            id: pkg.package_id, version: pkg.version, sha: shortHash(pkg.content_sha256),
            ids: pkg.declared_energy_exchange_ids.join(', '),
          })}
        </li>)}</ul>
        : <Alert type="info" content={t('cm.suggest.noPackage')} />}
    </div> : null}
    {query.data && !suggestions.length ? <Alert type="info" content={t('cm.suggest.empty')} /> : null}
    {suggestions.length ? <Table rowKey="exchange_id" pagination={false} scroll={{ y: 360 }} data={suggestions}
      columns={[
        { title: <Checkbox aria-label={t('cm.suggest.selectAll')} checked={allSelected}
          onChange={(checked: boolean) => setSelection(checked ? actionableIds : [])} />, width: 44, align: 'center' as const,
          render: (_: unknown, row: ClassificationSuggestion) => <Checkbox aria-label={`${t('cm.suggest.selectRow')} ${row.flow_name ?? row.exchange_id}`}
            disabled={!isActionable(row)} checked={selectedSet.has(row.exchange_id)}
            onChange={(checked: boolean) => toggle(row.exchange_id, checked)} /> },
        { title: t('cm.suggest.colProcess'), width: 140, render: (_: unknown, row: ClassificationSuggestion) => row.process_name ?? row.process_id ?? '—' },
        { title: t('cm.suggest.colFlow'), width: 180, render: (_: unknown, row: ClassificationSuggestion) =>
          <span>{row.flow_name ?? row.exchange_id}{row.unit ? <small className="inventory-linked"> {row.unit}</small> : null}</span> },
        { title: t('cm.suggest.colDirection'), width: 90, render: (_: unknown, row: ClassificationSuggestion) => directionText(t, row.direction) },
        { title: t('cm.suggest.colStatus'), width: 130, render: (_: unknown, row: ClassificationSuggestion) =>
          <Tag color={row.status === 'suggested' ? 'green' : row.status === 'pending_evidence' ? 'orange' : 'gray'}>{suggestStatusText(t, row.status)}</Tag> },
        { title: t('cm.suggest.colConfidence'), width: 90, render: (_: unknown, row: ClassificationSuggestion) => confidenceText(t, row.confidence) },
        { title: t('cm.suggest.colRationale'), width: 260, render: (_: unknown, row: ClassificationSuggestion) =>
          <div className="classification-suggestion-modal__rationale">
            <span>{rationaleText(t, row.rationale)}</span>
            <div className="classification-suggestion-modal__basis">{row.basis.map(code => <Tag key={code} size="small">{basisText(t, code)}</Tag>)}</div>
          </div> },
        { title: t('cm.suggest.colCurrent'), width: 120, render: (_: unknown, row: ClassificationSuggestion) =>
          row.current ? <span>{scopeText(t, row.current.scope)}{businessScopeText(t, row.current.scope) ? <small className="classification-suggestion-modal__business">{businessScopeText(t, row.current.scope)}</small> : null}</span> : <span className="helper-text">{t('cm.boundary.pending')}</span> },
        { title: t('cm.suggest.colSuggested'), width: 140, render: (_: unknown, row: ClassificationSuggestion) =>
          row.suggested ? <span>{scopeText(t, row.suggested.scope)}{businessScopeText(t, row.suggested.scope) ? <small className="classification-suggestion-modal__business">{businessScopeText(t, row.suggested.scope)}</small> : null}</span> : <span className="helper-text">—</span> },
      ]} /> : null}
  </Modal>;
}
