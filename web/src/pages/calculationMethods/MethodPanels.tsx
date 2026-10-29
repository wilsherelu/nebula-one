import { Alert, Button, Input, Select, Table } from '@arco-design/web-react';
import type { CalculationMethod, CalculationMethodValidation, CalculationMethodValidationProblem, CalculationMethodVersion, MethodCategory, MethodDimension, ModelProcessingRulesRef, ProcessingPackageOption } from '../../api/types';
import { useI18n } from '../../i18n';
import type { MessageKey } from '../../i18n';
import { EmptyState, ErrorState, LoadingState } from '../../components/ui/States';
import { boundaryText, directionText, locationText, purposeText, ruleIdentity, scopeText, statusText } from './labels';
import type { MethodDraftMeta, StaleMethodDraft } from './useMethodDraft';

/** A previous, unsaved draft whose base version is no longer the head. It is kept intact and never
 * folded into the live edit surface: the user compares it, discards it, or migrates it on purpose. */
export function StaleDraftBanner({ stale, onCompareToggle, comparing, onMigrate, onDiscard }: {
  stale: StaleMethodDraft;
  comparing: boolean;
  onCompareToggle: () => void;
  onMigrate: () => void;
  onDiscard: () => void;
}) {
  const { t } = useI18n();
  return <Alert type="warning" showIcon className="calculation-method-stale" content={<div>
    <strong>{t('cm.staleTitle', { version: stale.baseVersion })}</strong>
    <p>{t('cm.staleBody', {
      edited: stale.editedCount,
      added: stale.addedCount,
      removed: stale.removedCount,
    })}</p>
    {comparing ? <div className="calculation-method-stale__compare">
      <p className="helper-text">{t('cm.staleCompareHint')}</p>
      <ul className="calculation-method-stale__list">
        {stale.rules.map(rule => <li key={ruleIdentity(rule)}>
          <code>{rule.process_instance_id}</code>
          <span>{rule.exchange_id ?? rule.flow_uuid ?? t('cm.ruleProcessDefault')}</span>
          <span>{directionText(t, rule.direction)}</span>
          <span>{boundaryText(t, rule.boundary_status)}</span>
          <span>{locationText(t, rule.location_role)}</span>
          <span>{scopeText(t, rule.scope)}</span>
          <span>{rule.cbam_relevant ? t('cm.boundary.selected') : '—'}</span>
        </li>)}
      </ul>
    </div> : null}
    <div className="calculation-method-stale__actions">
      <Button size="mini" type="text" onClick={onCompareToggle}>{comparing ? t('cm.staleCompareClose') : t('cm.staleCompare')}</Button>
      <Button size="mini" type="text" onClick={onDiscard}>{t('cm.staleDiscard')}</Button>
      <Button size="mini" type="primary" onClick={onMigrate}>{t('cm.staleMigrate')}</Button>
    </div>
  </div>} />;
}

export function IdentityPanel({ method, version, editable, meta, onMeta }: {
  method: CalculationMethod;
  version: CalculationMethodVersion;
  editable: boolean;
  meta: MethodDraftMeta;
  onMeta: (patch: Partial<MethodDraftMeta>) => void;
}) {
  const { t } = useI18n();
  return <div className="calculation-method-identity">
    {!editable && <p className="helper-text">{t('cm.historyReadOnly')}</p>}
    {editable ? <div className="calculation-method-identity__fields">
      <label>{t('cm.identityName')}
        <Input value={meta.name} onChange={value => onMeta({ name: value })} maxLength={255} />
      </label>
      <label>{t('cm.identityPurpose')}
        <Input value={purposeText(t, method.purpose)} disabled />
      </label>
      <label>{t('cm.identityDescription')}
        <Input.TextArea value={meta.description ?? ''} onChange={value => onMeta({ description: value })} maxLength={4096} rows={3} />
      </label>
    </div> : <dl>
      <div><dt>{t('cm.identityName')}</dt><dd>{method.name}</dd></div>
      <div><dt>{t('cm.identityPurpose')}</dt><dd>{purposeText(t, method.purpose)}</dd></div>
      <div><dt>{t('cm.identityDescription')}</dt><dd>{method.description || '—'}</dd></div>
    </dl>}
    <details className="frozen-input-identity"><summary>{t('cm.identityOrigin')}</summary>
      <pre className="audit-json">{JSON.stringify({ origin_method_id: method.origin_method_id, model_revision_id: method.model_revision_id, version: version.version, content_sha256: version.content_sha256, cbam_boundary_ref: version.cbam_boundary_ref }, null, 2)}</pre>
    </details>
  </div>;
}

/** Business-facing summary of what a processing package does to this purpose's emissions, so a variant
 * that must narrow per-exchange can tell an explicit package from one that already froze the whole set. */
function flowsModeText(t: (key: MessageKey, vars?: Record<string, string | number>) => string, mode: string | null): string {
  if (mode === 'template_prelimited') return t('cm.processingModePrelimited');
  if (mode === 'explicit_flow_rules' || mode === 'identity_selector_rules') return t('cm.processingModeExplicit');
  return t('cm.processingModeUnknown');
}

/** The variant's processing-rule selector: bind this method version to one compatible reviewed package,
 * or keep the automatic official default (no explicit binding). The list comes from the server under the
 * method's own template, graph and purpose, so nothing here edits model or rule internals; the exact
 * identity and content hash are surfaced in a details area, and a save writes the binding for readback. */
export function ProcessingPackagesPanel({ options, loading, error, currentRef, editable, onChange }: {
  options: ProcessingPackageOption[];
  loading: boolean;
  error: unknown;
  currentRef: ModelProcessingRulesRef | null;
  editable: boolean;
  onChange: (ref: ModelProcessingRulesRef | null) => void;
}) {
  const { t } = useI18n();
  if (error) return <ErrorState error={error} />;
  if (loading) return <LoadingState />;

  const byHash = new Map(options.map(option => [option.content_sha256, option]));
  const selectedValue = currentRef?.content_sha256 ?? '';
  const selectOptions = [
    { value: '', label: t('cm.processingAutomatic') },
    ...options.map(option => ({
      value: option.content_sha256,
      label: `${option.package_id} · ${option.version}${option.purpose_declared ? '' : ` — ${t('cm.processingPurposeUndeclared')}`}`,
    })),
  ];
  const apply = (value: string) => {
    if (!value) { onChange(null); return; }
    const option = byHash.get(value);
    if (!option) return;
    onChange({ package_id: option.package_id, version: option.version, content_sha256: option.content_sha256 });
  };

  return <div className="calculation-method-processing">
    <p className="helper-text">{t('cm.processingHint')}</p>
    {!editable ? <p className="helper-text">{t('cm.historyReadOnly')}</p> : null}
    {editable
      ? <Select value={selectedValue} aria-label={t('cm.processingSelectLabel')} style={{ width: 360 }}
          disabled={!options.length && selectedValue === ''}
          options={selectOptions} onChange={apply} />
      : <p className="calculation-method-processing__current">
          {currentRef ? `${currentRef.package_id} · ${currentRef.version}` : t('cm.processingAutomatic')}
        </p>}
    {editable && !options.length ? <p className="helper-text">{t('cm.processingNone')}</p> : null}
    <details className="frozen-input-identity"><summary>{t('cm.processingIdentity')}</summary>
      <pre className="audit-json">{JSON.stringify(currentRef
        ? { package_id: currentRef.package_id, version: currentRef.version, content_sha256: currentRef.content_sha256,
            elementary_flows_mode: byHash.get(currentRef.content_sha256)?.elementary_flows_mode ?? null }
        : { automatic: true }, null, 2)}</pre>
    </details>
    {currentRef ? <p className="helper-text">{t('cm.processingMode', { mode: flowsModeText(t, byHash.get(currentRef.content_sha256)?.elementary_flows_mode ?? null) })}</p> : null}
  </div>;
}

/** Generate a stable, unused id of the form `<prefix>_<n>` so a category the rules already point at
 * is never renumbered when the user adds another. Ids are the save keys; names are display only. */
function nextId(prefix: string, taken: string[]): string {
  let index = 1;
  while (taken.includes(`${prefix}_${index}`)) index += 1;
  return `${prefix}_${index}`;
}

/** Author one or more user-defined reporting dimensions and their leaf categories. The generic compile
 * and grouping kernels consume these definitions directly, so declaring a non-Scope tree (onsite
 * production / purchased energy / upstream materials) needs no industry-specific calculation code.
 * The legacy Scope column stays for compatibility; a custom dimension is added alongside it. */
export function DimensionsEditor({ dimensions, editable, onChange }: {
  dimensions: MethodDimension[];
  editable: boolean;
  onChange: (next: MethodDimension[]) => void;
}) {
  const { t } = useI18n();
  const customDims = dimensions.filter(dim => dim.id !== 'lc_scope');

  const mapDim = (id: string, transform: (dim: MethodDimension) => MethodDimension) =>
    onChange(dimensions.map(dim => dim.id === id ? transform(dim) : dim));

  const addDim = () => onChange([...dimensions, {
    id: nextId('dimension', dimensions.map(dim => dim.id)),
    name: '',
    categories: [{ id: 'category_1', name: '', is_leaf: true }],
  }]);
  const removeDim = (id: string) => onChange(dimensions.filter(dim => dim.id !== id));

  const patchCategory = (dimId: string, catId: string, patch: Partial<MethodCategory>) =>
    mapDim(dimId, dim => ({ ...dim, categories: dim.categories.map(cat => cat.id === catId ? { ...cat, ...patch } : cat) }));
  const removeCategory = (dimId: string, catId: string) =>
    mapDim(dimId, dim => ({ ...dim, categories: dim.categories.filter(cat => cat.id !== catId) }));
  const addCategory = (dimId: string) =>
    mapDim(dimId, dim => ({ ...dim, categories: [...dim.categories, { id: nextId('category', dim.categories.map(cat => cat.id)), name: '', is_leaf: true }] }));

  return <div className="calculation-method-dimensions">
    <p className="helper-text">{t('cm.dimHint')}</p>
    {customDims.map(dim => <div className="calculation-method-dimensions__dim" key={dim.id}>
      {editable ? <div className="calculation-method-dimensions__dim-head">
        <Input className="calculation-method-dimensions__id" value={dim.id} aria-label={t('cm.dimId')} size="small" style={{ width: 160 }}
          onChange={value => mapDim(dim.id, current => ({ ...current, id: value.trim() || current.id }))} />
        <Input value={dim.name ?? ''} aria-label={t('cm.dimName')} size="small" placeholder={t('cm.dimName')} style={{ width: 200 }}
          onChange={value => mapDim(dim.id, current => ({ ...current, name: value }))} />
        <Button type="text" size="mini" onClick={() => removeDim(dim.id)}>{t('cm.dimRemove')}</Button>
      </div> : <strong className="calculation-method-dimensions__name">{dim.name || dim.id}</strong>}
      {dim.categories.map(cat => <div className="calculation-method-dimensions__cat" key={cat.id}>
        {editable ? <>
          <Input className="calculation-method-dimensions__id" value={cat.id} aria-label={t('cm.dimCatId')} size="small" style={{ width: 160 }}
            onChange={value => patchCategory(dim.id, cat.id, { id: value.trim() || cat.id })} />
          <Input value={cat.name ?? ''} aria-label={t('cm.dimCatName')} size="small" placeholder={t('cm.dimCatName')} style={{ width: 200 }}
            onChange={value => patchCategory(dim.id, cat.id, { name: value })} />
          <Button type="text" size="mini" disabled={dim.categories.length <= 1} onClick={() => removeCategory(dim.id, cat.id)}>{t('cm.dimCatRemove')}</Button>
        </> : <span className="calculation-method-dimensions__cat-ro">{cat.name || cat.id}</span>}
      </div>)}
      {editable ? <Button type="outline" size="mini" onClick={() => addCategory(dim.id)}>{t('cm.dimCatAdd')}</Button> : null}
    </div>)}
    {editable ? <Button type="outline" size="small" onClick={addDim}>{t('cm.dimAdd')}</Button> : null}
    {!customDims.length && !editable ? <p className="helper-text">{t('cm.dimNone')}</p> : null}
  </div>;
}

export function ValidationPanel({ validation, validating, canValidate, draftDirty, onValidate }: {
  validation: CalculationMethodValidation | null;
  validating: boolean;
  canValidate: boolean;
  draftDirty: boolean;
  onValidate: () => void;
}) {
  const { t } = useI18n();
  const problemLocation = (problem: CalculationMethodValidationProblem): string => {
    if (!problem.process_instance_id) return t('cm.validationProblemUnknown');
    const base = `${t('cm.validationLocProcess')} ${problem.process_instance_id}`;
    return problem.exchange_id ? `${base} · ${t('cm.validationLocExchange')} ${problem.exchange_id}` : base;
  };
  return <div className="calculation-method-review">
    {!canValidate ? <p className="helper-text">{t('cm.validateReadOnly')}</p> : draftDirty ? <p className="helper-text">{t('cm.validateNeedsSaved')}</p> : null}
    <div className="calculation-method-review__validate">
      <Button type="primary" onClick={onValidate} loading={validating} disabled={!canValidate || draftDirty}>{t('cm.validate')}</Button>
    </div>
    {validation && validation.valid ? <Alert type="success" showIcon content={t('cm.validationPassed')} /> : null}
    {validation && !validation.valid ? <Alert type="error" showIcon content={<div>
      <strong>{t('cm.validationFailedTitle', { count: validation.problems.length })}</strong>
      <p>{t('cm.validationBlocked')}</p>
      <ul className="calculation-method-review__problems">
        {validation.problems.map((problem, index) => <li key={`${problem.code}-${index}`}>
          <code>{problem.code}</code>
          <span>{problem.message}</span>
          <small>{problem.rule_index !== null ? t('cm.validationRule', { index: problem.rule_index + 1 }) : null} · {problemLocation(problem)}</small>
        </li>)}
      </ul>
    </div>} /> : null}
  </div>;
}

/** Historical versions live in their own dialog: the list is not the editing surface, and the count
 * of matched records is neither a count of flows nor a count of numerical contributions. */
export function VersionHistoryPanel({ versions, currentVersion, onView }: {
  versions: CalculationMethodVersion[];
  currentVersion: number;
  onView: (version: number) => void;
}) {
  const { t, formatDate } = useI18n();
  return <div className="calculation-method-history">
    <Table rowKey="id" pagination={false} scroll={{ x: 620 }} data={versions}
      columns={[
        { title: t('cm.versionLabel'), width: 90, render: (_, row: CalculationMethodVersion) => `v${row.version}` },
        { title: t('cm.reviewStatus'), width: 120, render: (_, row: CalculationMethodVersion) => statusText(t, row.status) },
        { title: t('cm.matchedRecords'), width: 120, align: 'right', render: (_, row: CalculationMethodVersion) => row.rules.length },
        { title: t('cm.reviewCreated'), width: 200, render: (_, row: CalculationMethodVersion) => formatDate(row.created_at) },
        { title: '', width: 100, render: (_, row: CalculationMethodVersion) => <Button size="mini" type="text"
          disabled={row.version === currentVersion} onClick={() => onView(row.version)}>{t('cm.viewVersion')}</Button> },
      ]} />
    <details className="frozen-input-identity"><summary>{t('cm.reviewContent')}</summary>
      <pre className="audit-json">{JSON.stringify(versions.map(item => ({ version: item.version, content_sha256: item.content_sha256, matched_records: item.rules.length })), null, 2)}</pre>
    </details>
  </div>;
}
