import { Alert, Button, Checkbox, Select, Table } from '@arco-design/web-react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import type { TagSchemeGrouping } from '../api/types';
import { useI18n } from '../i18n';
import type { MessageKey } from '../i18n';
import { ErrorState, LoadingState } from './ui/States';

const REASON_KEYS: Record<string, MessageKey> = {
  PATH_WEIGHTED_RECEIPT_MISSING: 'pcf.tagResultNoReceipt',
};
const LEGACY_REASON_KEYS: Record<string, MessageKey> = {
  PATH_WEIGHTED_RECEIPT_MISSING: 'pcf.tagNoReceipt',
};

/** Both calibers replay the same frozen pool: `result_category.v1` is the current one, and a
 * legacy `flow_tag.v1` scheme stays readable so its historical results remain viewable. */
const isCaliber = (method: { semantics?: string | null }) =>
  method.semantics === 'result_category.v1' || method.semantics === 'flow_tag.v1';

/** Re-bucket one solved snapshot's frozen contributions by exact tag schemes. This is a read over
 * the result the engine already produced: it never re-solves, never rescales the model, and keeps
 * unmatched, pending, missing and true-zero outcomes separate instead of folding them into zero. */
export function TagResultPanel(props: {
  applicationId: string;
  revisionId: string;
  snapshotId: string;
  indicatorKey: string;
}) {
  return <TagResultWorkspace key={`${props.applicationId}:${props.revisionId}:${props.snapshotId}:${props.indicatorKey}`} {...props} />;
}

function TagResultWorkspace({ applicationId, revisionId, snapshotId, indicatorKey }: {
  applicationId: string; revisionId: string; snapshotId: string; indicatorKey: string;
}) {
  const { t, formatNumber: formatLocaleNumber } = useI18n();
  const queryClient = useQueryClient();
  const formatNumber = (value: number) => formatLocaleNumber(value, { maximumSignificantDigits: 8 });
  const [mode, setMode] = useState<'separate' | 'intersection' | 'union'>('separate');
  const [selected, setSelected] = useState<string[]>([]);
  const [historyId, setHistoryId] = useState('');
  const [exportError, setExportError] = useState<unknown>(null);
  const [exporting, setExporting] = useState(false);
  const history = useQuery({ queryKey: ['tag-grouping-history', applicationId, snapshotId],
    queryFn: () => api.tagGroupingHistory(applicationId, snapshotId) });
  const historical = useQuery({ queryKey: ['tag-grouping-result', applicationId, historyId],
    queryFn: () => api.tagGroupingResult(applicationId, historyId), enabled: !!historyId });

  const methods = useQuery({
    queryKey: ['calculation-methods', applicationId, revisionId],
    queryFn: () => api.calculationMethods(applicationId, revisionId),
  });
  const schemes = useMemo(() => (methods.data ?? []).filter(method =>
    isCaliber(method) && method.latest_version && method.latest_content_sha256
    && method.latest_status === 'ready' && method.status !== 'retired'), [methods.data]);
  const drafts = (methods.data ?? []).filter(method => isCaliber(method)
    && method.status !== 'retired' && method.latest_status !== 'ready');
  const savedResults = (history.data ?? []).filter(item => item.result_id && item.indicator_key === indicatorKey);
  const schemeKey = schemes.map(method => `${method.id}@${method.latest_version}@${method.latest_content_sha256}`).join(',');

  useEffect(() => {
    setSelected(schemes.length ? [schemes[0].id] : []);
  }, [schemeKey]);

  const refs = schemes.filter(method => selected.includes(method.id)).map(method => ({
    method_id: method.id,
    version: method.latest_version as number,
    content_sha256: method.latest_content_sha256 as string,
  }));
  const refKey = refs.map(ref => `${ref.method_id}@${ref.version}@${ref.content_sha256}`).join(',');

  const grouping = useQuery({
    queryKey: ['tag-grouping', applicationId, snapshotId, indicatorKey, mode, refKey],
    queryFn: () => api.tagGrouping(applicationId, {
      snapshot_id: snapshotId, indicator_key: indicatorKey, schemes: refs, mode,
    }),
    enabled: !historyId && !!indicatorKey && refs.length > 0,
  });
  useEffect(() => {
    if (grouping.data?.result_id) void queryClient.invalidateQueries({ queryKey: ['tag-grouping-history', applicationId, snapshotId] });
  }, [grouping.data?.result_id, queryClient, applicationId, snapshotId]);
  const displayed = historyId ? historical : grouping;
  // A frozen result or a set of old schemes still reads as tag grouping, so history keeps its
  // wording. A result frozen before this field existed is legacy by construction.
  const semantics = displayed.data?.semantics;
  const legacyView = displayed.data
    ? semantics === 'flow_tag.v1' || !semantics
    : schemes.length > 0 && schemes.every(method => method.semantics === 'flow_tag.v1');
  const download = async (format: 'html' | 'json') => {
    const resultId = displayed.data?.result_id;
    if (!resultId) return;
    setExportError(null); setExporting(true);
    try {
      const blob = await api.tagGroupingExport(applicationId, resultId, format);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url; link.download = `tag-result-${resultId}.${format}`;
      document.body.appendChild(link); link.click(); link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) { setExportError(error); }
    finally { setExporting(false); }
  };

  if (methods.isLoading) return <LoadingState rows={2} />;
  if (methods.error) return <ErrorState error={methods.error} onRetry={() => methods.refetch()} />;
  if (!schemes.length && !drafts.length && !savedResults.length && !history.error) return null;
  return <section className="pcf-result__tag-grouping" aria-label={t(legacyView ? 'pcf.tagTitle' : 'pcf.tagResultTitle')}>
    <div className="section-heading"><h3>{t(legacyView ? 'pcf.tagTitle' : 'pcf.tagResultTitle')}</h3></div>
    <p className="helper-text">{t(legacyView ? 'pcf.tagHint' : 'pcf.tagResultHint')}</p>
    {drafts.length ? <Alert type="info" content={<>
      <p>{t(legacyView ? 'pcf.tagDrafts' : 'pcf.tagResultDrafts')}</p>
      <div className="form-actions">{drafts.map(method => <Link key={method.id}
        to={`/applications/${applicationId}/calculation-methods?revision=${encodeURIComponent(revisionId)}&method=${encodeURIComponent(method.id)}`}>
        {t('pcf.tagCheckScheme', { name: method.name })}
      </Link>)}</div>
    </>} /> : null}
    {schemes.length || savedResults.length ? <>
    <div className="tag-result__toolbar">
      <Select aria-label={t('pcf.tagHistory')} value={historyId} onChange={setHistoryId} style={{ minWidth: 260, maxWidth: '100%' }}
        options={[{ value: '', label: t('pcf.tagCurrent') }, ...savedResults.map(item => ({
          value: item.result_id!, label: `${item.created_at ? new Date(item.created_at).toLocaleString() : ''} · ${t(item.mode === 'union' ? 'pcf.tagModeUnion' : item.mode === 'intersection' ? 'pcf.tagModeIntersection' : 'pcf.tagModeSeparate')} · ${item.schemes.map(scheme => `${scheme.scheme.name} v${scheme.scheme.version}`).join(' / ')}`,
        }))]} />
      <div className="form-actions">
        <Button size="small" disabled={!displayed.data?.result_id || exporting} onClick={() => void download('html')}>{t('pcf.tagExportReport')}</Button>
        <Button size="small" disabled={!displayed.data?.result_id || exporting} onClick={() => void download('json')}>{t('pcf.tagExportData')}</Button>
      </div>
    </div>
    </> : null}
    {history.error ? <ErrorState error={history.error} onRetry={() => history.refetch()} /> : null}
    {exportError ? <ErrorState error={exportError} /> : null}
    <>
      {!historyId && schemes.length > 0 ? <div className="tag-result__toolbar">
        <div className="tag-result__schemes">
          {schemes.map(method => <Checkbox key={method.id} checked={selected.includes(method.id)}
            onChange={(checked: boolean) => setSelected(previous => checked
              ? [...previous, method.id]
              : previous.filter(id => id !== method.id))}>
            {method.name} <small className="tech-id">v{method.latest_version}</small>
            {method.semantics === 'flow_tag.v1' ? <small className="helper-text"> · {t('pcf.tagLegacyBadge')}</small> : null}
          </Checkbox>)}
        </div>
        <Select value={mode} aria-label={t('pcf.tagMode')} style={{ width: 180 }}
          onChange={value => setMode(value as typeof mode)}
          options={[
            { value: 'separate', label: t('pcf.tagModeSeparate') },
            { value: 'intersection', label: t('pcf.tagModeIntersection') },
            { value: 'union', label: t('pcf.tagModeUnion') },
          ]} />
      </div> : null}
      {!historyId && schemes.length > 0 && !refs.length ? <p className="helper-text">{t(
        legacyView ? 'pcf.tagPickScheme' : 'pcf.tagResultPickScheme')}</p> : null}
      {displayed.error ? <ErrorState error={displayed.error} onRetry={() => displayed.refetch()} /> : null}
      {displayed.data && !displayed.data.available ? <Alert type="warning" content={t(
        (legacyView ? LEGACY_REASON_KEYS : REASON_KEYS)[displayed.data.reason ?? '']
        ?? (legacyView ? 'pcf.tagUnavailable' : 'pcf.tagResultUnavailable'),
        { reason: displayed.data.reason ?? '' })} /> : null}
      {(historyId || refs.length > 0) && displayed.data?.available ? <TagGroupingBody data={displayed.data} formatNumber={formatNumber} /> : null}
      {(historyId || refs.length > 0) && displayed.isLoading ? <LoadingState rows={2} /> : null}
    </>
  </section>;
}

function TagGroupingBody({ data, formatNumber }: {
  data: import('../api/types').TagGroupingResult;
  formatNumber: (value: number) => string;
}) {
  const { t } = useI18n();
  const setTotal = data.mode === 'union' ? data.union : data.mode === 'intersection' ? data.intersection : null;
  return <div className="tag-result">
    {setTotal ? <div className="tag-result__set">
      <strong>{t(data.mode === 'union' ? 'pcf.tagUnionTotal' : 'pcf.tagIntersectionTotal')}</strong>
      <span className="tabular">{setTotal.value === null ? '—' : `${formatNumber(setTotal.value)} ${setTotal.unit ?? ''}`}</span>
      <small>{t('pcf.tagSetTerms', { count: setTotal.term_count })}</small>
      {data.overlap.multi_scheme_term_count !== undefined ? <small>{t('pcf.tagOverlap', { count: data.overlap.multi_scheme_term_count })}</small> : null}
    </div> : null}
    {data.schemes.map(scheme => <SchemeCard key={`${scheme.scheme.method_id}@${scheme.scheme.version}`}
      scheme={scheme} formatNumber={formatNumber} />)}
    {data.problems.length ? <div className="tag-result__problems">
      <strong>{t('pcf.tagProblems', { count: data.problems.length })}</strong>
      <details><summary>{t('pcf.tagDetail')}</summary><ul>{data.problems.map((problem, index) => <li key={`${problem.code ?? 'problem'}-${index}`}>
        <code>{problem.code ?? '—'}</code> {problem.message ?? ''}
        {problem.exchange_id ? <small className="tech-id"> · {problem.exchange_id}</small> : null}
      </li>)}</ul></details>
    </div> : null}
    <details className="frozen-input-identity"><summary>{t('pcf.tagDetail')}</summary>
      <pre className="audit-json">{JSON.stringify(data, null, 2)}</pre>
    </details>
  </div>;
}

function SchemeCard({ scheme, formatNumber }: {
  scheme: TagSchemeGrouping;
  formatNumber: (value: number) => string;
}) {
  const { t } = useI18n();
  const unit = scheme.tag_total.unit ?? '';
  const resultCategory = scheme.semantics === 'result_category.v1';
  const populated = scheme.populated !== false;
  const matched = scheme.matched.known_term_count;
  return <article className="tag-result__scheme">
    <div className="tag-result__scheme-head">
      <strong>{scheme.scheme.name}</strong>
      <small className="tech-id">v{scheme.scheme.version}</small>
      <span className="tabular">{scheme.tag_total.value === null ? '—' : `${formatNumber(scheme.tag_total.value)} ${unit}`}</span>
    </div>
    {populated ? <p className="helper-text">{scheme.reconciled
      ? t(resultCategory ? 'pcf.tagResultReconciled' : 'pcf.tagReconciled')
      : t(resultCategory ? 'pcf.tagResultUnreconciled' : 'pcf.tagUnreconciled')}</p>
      : <p className="helper-text">{t('pcf.tagNotPopulated')}</p>}
    {scheme.dimension.categories.length ? <Table rowKey="id" pagination={false} scroll={{ x: 420 }} data={scheme.dimension.categories}
      columns={[
        { title: t('pcf.tagCategory'), render: (_, row) => `${row.is_leaf ? '' : '· '}${row.name || row.id}` },
        { title: t('pcf.tagValue'), align: 'right' as const, width: 200,
          render: (_, row) => <span className="tabular">{row.subtotal === null ? '—' : `${formatNumber(row.subtotal)} ${row.unit ?? unit}`}</span> },
        { title: t('pcf.tagTerms'), align: 'right' as const, width: 90, render: (_, row) => row.term_count },
        { title: t('pcf.tagMissing'), align: 'right' as const, width: 90, render: (_, row) => row.missing_count },
      ]} /> : null}
    <dl className="pcf-result__facts">
      <div><dt>{t(resultCategory ? 'pcf.tagResultMatched' : 'pcf.tagMatched')}</dt><dd className="tabular">
        {t(resultCategory ? 'pcf.tagResultMatchedKnown' : 'pcf.tagMatchedKnown', { known: scheme.matched.known_term_count, count: scheme.matched.term_count })}</dd></div>
      {!resultCategory && scheme.uncategorized.term_count ? <div><dt>{t('pcf.tagUncategorized')}</dt>
        <dd className="tabular">{scheme.uncategorized.subtotal === null ? '—'
          : `${formatNumber(scheme.uncategorized.subtotal)} ${scheme.uncategorized.unit || unit}`}</dd></div> : null}
      <div><dt>{t(resultCategory ? 'pcf.tagResultUnmatched' : 'pcf.tagUnmatched')}</dt><dd className="tabular">
        {scheme.unmatched.term_count && scheme.unmatched.known_value !== null ? `${formatNumber(scheme.unmatched.known_value)} ${scheme.unmatched.unit ?? ''}` : '—'}
        {scheme.unmatched.term_count ? <small> · {t('pcf.tagTermsCount', { count: scheme.unmatched.term_count })}</small> : null}
        {scheme.unmatched.missing_count ? <small> · {t('pcf.tagMissingCount', { count: scheme.unmatched.missing_count })}</small> : null}</dd></div>
      {resultCategory ? null : <div><dt>{t('pcf.tagPending')}</dt><dd>{scheme.pending.term_count}</dd></div>}
      <div><dt>{t(resultCategory ? 'pcf.tagResultMissingLabel' : 'pcf.tagMissingLabel')}</dt><dd>{scheme.missing.term_count}</dd></div>
      <div><dt>{t('pcf.tagRealZero')}</dt><dd>{scheme.real_zero.term_count}</dd></div>
      <div><dt>{t(resultCategory ? 'pcf.tagResultCoverage' : 'pcf.tagCoverage')}</dt><dd>{scheme.coverage.matched_share === null ? '—'
        : `${formatNumber(scheme.coverage.matched_share * 100)}%`}</dd></div>
    </dl>
    {matched === 0 && populated ? <p className="helper-text">{t(resultCategory ? 'pcf.tagResultNoMatched' : 'pcf.tagNoMatched')}</p> : null}
  </article>;
}
