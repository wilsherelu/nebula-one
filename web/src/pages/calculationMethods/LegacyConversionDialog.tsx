import { Alert, Button, Input, Modal, Select } from '@arco-design/web-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useRef, useState } from 'react';
import { api } from '../../api/client';
import type {
  MethodDimension,
  ResultCategoryConversionOptions,
  ResultCategoryConversionPreview,
  ResultCategoryConversionRule,
} from '../../api/types';
import { useI18n, type MessageKey } from '../../i18n';
import { ErrorState, LoadingState } from '../../components/ui/States';
import { categoryName } from './TagSchemeEditor';

const NONE = '__none__';

const INCLUDED_COUNTS = [
  'total', 'assigned', 'selected_without_category', 'pending', 'excluded',
  'invalid_category', 'unresolved_invalid', 'resolved_without_category',
] as const;

const COUNT_KEYS: Record<(typeof INCLUDED_COUNTS)[number], MessageKey> = {
  total: 'cm.convertCount.total',
  assigned: 'cm.convertCount.assigned',
  selected_without_category: 'cm.convertCount.selectedWithoutCategory',
  pending: 'cm.convertCount.pending',
  excluded: 'cm.convertCount.excluded',
  invalid_category: 'cm.convertCount.invalidCategory',
  unresolved_invalid: 'cm.convertCount.unresolvedInvalid',
  resolved_without_category: 'cm.convertCount.resolvedWithoutCategory',
};

interface TargetCategoryDraft { id: string; name: string }

/** Convert one legacy (tag or pre-caliber ordinary) version into an independent result-category
 * caliber. The POST preview is the same plan the server applies: an invalid legacy category blocks
 * both until the reader maps it to a declared leaf or explicitly chooses “无”. */
export function LegacyConversionDialog({ methodId, version, methodName, flowLabel, onClose, onConverted }: {
  methodId: string;
  version: number;
  methodName: string;
  flowLabel?: (rule: ResultCategoryConversionRule, index: number) => string;
  onClose: () => void;
  onConverted: (methodId: string) => void;
}) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [name, setName] = useState(() => t('cm.convertDefaultName', { name: methodName }));
  const [sourceDimensionId, setSourceDimensionId] = useState<string | null>(null);
  const [targetName, setTargetName] = useState('');
  const [targetCategories, setTargetCategories] = useState<TargetCategoryDraft[]>([]);
  const [decisions, setDecisions] = useState<Record<number, string | null | undefined>>({});
  const counter = useRef(0);

  const options = useMemo<ResultCategoryConversionOptions>(() => {
    const resolutions = Object.entries(decisions)
      .filter(([, value]) => value !== undefined)
      .map(([index, value]) => ({ rule_index: Number(index), category: value ?? null }));
    const target: MethodDimension | null = targetCategories.length && targetCategories.every(item => item.name.trim())
      ? {
          id: 'legacy_conversion_target',
          name: targetName.trim() || null,
          source: 'user',
          categories: targetCategories.map(item => ({ id: item.id, name: item.name.trim(), parent_id: null, is_leaf: true })),
        }
      : null;
    return { source_dimension_id: sourceDimensionId, target_dimension: target, resolutions };
  }, [decisions, sourceDimensionId, targetCategories, targetName]);

  const preview = useQuery({
    queryKey: ['result-category-conversion', methodId, version, JSON.stringify(options)],
    queryFn: () => api.resultCategoryConversionPreviewMapping(methodId, version, options),
  });
  const convert = useMutation({
    mutationFn: () => api.convertToResultCategory(methodId, version, {
      ...options,
      name: name.trim(),
      expected_mapping_sha256: preview.data?.mapping_sha256 ?? null,
    }),
    onSuccess: created => {
      queryClient.invalidateQueries({ queryKey: ['calculation-methods'] });
      queryClient.invalidateQueries({ queryKey: ['calculation-method', created.method.id] });
      queryClient.invalidateQueries({ queryKey: ['template-accounting-methods'] });
      onConverted(created.method.id);
    },
  });
  const data: ResultCategoryConversionPreview | undefined = preview.data;
  const leaves = (data?.dimension?.categories ?? []).filter(category => category.is_leaf !== false);
  const categoryOf = (id: string | null) => {
    if (!id) return t('cm.convertOldNone');
    const found = data?.dimension?.categories.find(category => category.id === id);
    return found ? categoryName(found) : t('cm.convertOldMissing', { category: id });
  };
  const decisionsNeeded = (data?.rules ?? []).filter(rule => rule.needs_resolution || rule.resolved);
  const canConvert = !!data?.can_convert && !!name.trim() && !preview.isFetching;
  const setDecision = (index: number, value: string) => {
    setDecisions(previous => ({ ...previous, [index]: value === NONE ? null : value }));
  };
  const addTargetCategory = () => {
    counter.current += 1;
    setTargetCategories(previous => [...previous, { id: `target_${counter.current}`, name: '' }]);
  };
  const removeTargetCategory = (id: string) => {
    setTargetCategories(previous => previous.filter(item => item.id !== id));
    setDecisions(previous => Object.fromEntries(
      Object.entries(previous).filter(([, value]) => value !== id),
    ));
  };
  return <Modal className="legacy-conversion" title={t('cm.convertTitle')} visible
    onCancel={onClose} style={{ width: 720, maxWidth: 'calc(100vw - 32px)' }}
    footer={<div className="form-actions">
      <Button onClick={onClose}>{t('cm.createCancel')}</Button>
      <Button type="primary" loading={convert.isPending} disabled={!canConvert} onClick={() => convert.mutate()}>
        {t('cm.convertSubmit')}
      </Button>
    </div>}>
    {preview.isLoading ? <LoadingState rows={3} /> : preview.error ? <ErrorState error={preview.error} onRetry={() => preview.refetch()} /> : data ? <>
      <p>{t('cm.convertBody', { name: data.source_method_name, version: data.source_version })}</p>
      {data.source_dimensions.length > 1 ? <label className="project-field"><span>{t('cm.convertSourceTree')}</span>
        <Select aria-label={t('cm.convertSourceTree')} style={{ width: '100%' }}
          value={sourceDimensionId ?? undefined} placeholder={t('cm.convertSourceTreePlaceholder')}
          options={data.source_dimensions.map((item, index) => ({
            value: item.id,
            label: item.name || t('cm.convertTreeFallback', { index: index + 1 }),
          }))}
          onChange={value => { setSourceDimensionId(value); setDecisions({}); }} />
      </label> : null}
      {!data.source_dimensions.length ? <div className="legacy-conversion__target">
        <p className="helper-text">{t('cm.convertTargetRequired')}</p>
        <label className="project-field"><span>{t('cm.convertTargetName')}</span>
          <Input value={targetName} onChange={setTargetName} maxLength={120} placeholder={t('cm.convertTargetNamePlaceholder')} /></label>
        <div className="legacy-conversion__target-list">
          {targetCategories.map((item, index) => <div className="legacy-conversion__target-row" key={item.id}>
            <Input aria-label={t('cm.convertTargetCategory', { index: index + 1 })} value={item.name}
              onChange={value => setTargetCategories(previous => previous.map(entry => entry.id === item.id ? { ...entry, name: value } : entry))}
              placeholder={t('cm.convertTargetCategory', { index: index + 1 })} maxLength={120} />
            <Button type="text" size="small" onClick={() => removeTargetCategory(item.id)}>{t('cm.convertRemoveCategory')}</Button>
          </div>)}
          <Button size="small" type="outline" onClick={addTargetCategory}>{t('cm.convertAddCategory')}</Button>
        </div>
      </div> : null}
      <div className="legacy-conversion__categories">
        <span className="legacy-conversion__label">{t('cm.tagCategories')}</span>
        {leaves.length ? leaves.map(category => <span className="tag-scheme__chip" key={category.id}>{categoryName(category)}</span>)
          : <span className="helper-text">{t('cm.convertNoCategories')}</span>}
      </div>
      <dl className="legacy-conversion__counts">
        {INCLUDED_COUNTS.map(key => <div key={key}>
          <dt>{t(COUNT_KEYS[key])}</dt>
          <dd>{data.counts[key]}</dd>
        </div>)}
      </dl>
      {data.counts.assigned ? <p className="helper-text">{t('cm.convertAssignedHint', { count: data.counts.assigned })}</p> : null}
      {data.counts.selected_without_category ? <p className="helper-text">{t('cm.convertUnassignedHint', { count: data.counts.selected_without_category })}</p> : null}
      {data.counts.resolved_without_category ? <p className="helper-text">{t('cm.convertResolvedNoneHint', { count: data.counts.resolved_without_category })}</p> : null}
      {decisionsNeeded.length ? <div className="legacy-conversion__rows">
        <p className="legacy-conversion__label">{t('cm.convertResolveTitle', { count: decisionsNeeded.length })}</p>
        <p className="helper-text">{t('cm.convertResolveHint')}</p>
        <ul>
          {decisionsNeeded.map((rule, position) => <li key={rule.rule_index}>
            <span className="legacy-conversion__flow">
              {flowLabel ? flowLabel(rule, rule.rule_index) : t('cm.convertRuleFallback', { index: position + 1 })}
            </span>
            <span className="legacy-conversion__old">{categoryOf(rule.old_category)}</span>
            <Select aria-label={t('cm.convertResolveSelect', { index: position + 1 })} size="small" style={{ width: 180 }}
              value={decisions[rule.rule_index] === undefined ? undefined : decisions[rule.rule_index] ?? NONE}
              placeholder={t('cm.convertResolvePlaceholder')}
              options={[...leaves.map(category => ({ value: category.id, label: categoryName(category) })),
                { value: NONE, label: t('cm.convertNone') }]}
              onChange={value => setDecision(rule.rule_index, value)} />
          </li>)}
        </ul>
      </div> : null}
      {data.problems.length ? <Alert type="warning" showIcon content={t('cm.convertProblems', { count: data.problems.length })} /> : null}
      {data.can_convert
        ? <p className="helper-text">{t('cm.convertImpact', {
            carried: data.counts.assigned,
            none: data.counts.selected_without_category + data.counts.resolved_without_category,
          })}</p>
        : <Alert type="error" showIcon content={data.counts.unresolved_invalid
            ? t('cm.convertUnresolved', { count: data.counts.unresolved_invalid })
            : t('cm.convertBlocked')} />}
      <label className="project-field"><span>{t('cm.cloneName')}</span>
        <Input value={name} onChange={setName} maxLength={255} />
      </label>
      <p className="helper-text">{t('cm.convertConfirmHint')}</p>
      {convert.isError ? <ErrorState error={convert.error} /> : null}
    </> : null}
  </Modal>;
}
