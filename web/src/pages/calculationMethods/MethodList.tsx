import { Button, Input, Table } from '@arco-design/web-react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { api } from '../../api/client';
import type { CalculationMethod, CalculationMethodDetail, MethodPackage } from '../../api/types';
import { useI18n } from '../../i18n';
import { ErrorState, LoadingState } from '../../components/ui/States';
import { packageKindText, purposeText, statusText } from './labels';

/** The single creation entry: a result-category caliber. It starts with at most one simple
 * category, and every further flow decision is made by assigning a leaf in the workspace. Legacy
 * `flow_tag.v1` schemes are never created here; they stay readable and convertible. */
export function NewMethodForm({ applicationId, revisionId, onCancel, onCreated }: {
  applicationId: string;
  revisionId: string;
  onCancel: () => void;
  onCreated: (id: string) => void;
}) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [name, setName] = useState('');
  const [categoryName, setCategoryName] = useState('');
  const create = useMutation({
    mutationFn: () => {
      const category = categoryName.trim();
      return api.createCalculationMethod(applicationId, {
        name,
        purpose: 'custom',
        model_revision_id: revisionId,
        rules: [],
        semantics: 'result_category.v1',
        reporting_dimensions: [{
          id: 'result_category',
          name: t('cm.tagCategories'),
          categories: category ? [{ id: 'result_category_1', name: category, is_leaf: true }] : [],
        }],
      });
    },
    onSuccess: (created: CalculationMethodDetail) => {
      queryClient.invalidateQueries({ queryKey: ['calculation-methods', applicationId, revisionId] });
      onCreated(created.method.id);
    },
  });
  return <div className="calculation-methods__create">
    <label>{t('cm.identityName')}
      <Input autoFocus value={name} onChange={setName} placeholder={t('cm.identityName')} maxLength={255} />
    </label>
    <label>{t('cm.tagFirstCategoryOptional')}
      <Input value={categoryName} onChange={setCategoryName} placeholder={t('cm.tagCategoryName')} maxLength={120} />
    </label>
    <p className="helper-text">{t('cm.resultCategoryCreateHint')}</p>
    {create.isError ? <ErrorState error={create.error} /> : null}
    <div className="calculation-methods__create-actions">
      <Button type="primary" onClick={() => create.mutate()} loading={create.isPending} disabled={!name.trim()}>{t('cm.createSubmit')}</Button>
      <Button type="text" onClick={onCancel}>{t('cm.createCancel')}</Button>
    </div>
    {!name.trim() ? <p className="helper-text">{t('cm.nameRequired')}</p> : null}
  </div>;
}

export function MethodList({ methods, packages, packagesLoading, revisionLabel, applicationId, revisionId, onOpen }: {
  methods: CalculationMethod[];
  packages: MethodPackage[];
  packagesLoading: boolean;
  revisionLabel: string;
  applicationId: string;
  revisionId: string;
  onOpen: (id: string) => void;
}) {
  const { t } = useI18n();
  const [creating, setCreating] = useState(false);
  const legacyOrdinary = (row: CalculationMethod) => row.semantics == null && row.purpose === 'custom';
  const typeOf = (row: CalculationMethod) => row.semantics === 'result_category.v1'
    ? t('cm.typeResultCategory')
    : row.semantics === 'flow_tag.v1'
      ? t('cm.typeLegacyTag')
      : legacyOrdinary(row) ? t('cm.typeLegacyMethod') : t('cm.typeMethod');
  const isCaliber = (row: CalculationMethod) => row.semantics === 'result_category.v1' || row.semantics === 'flow_tag.v1';
  return <section className="section-panel calculation-methods__list">
    <div className="calculation-methods__list-head">
      <h2>{t('cm.userGroup')}</h2>
      <div className="calculation-methods__list-actions">
        <Button type="primary" size="small" onClick={() => setCreating(true)}>{t('cm.newResultCategory')}</Button>
      </div>
    </div>
    {creating ? <NewMethodForm applicationId={applicationId} revisionId={revisionId}
      onCancel={() => setCreating(false)} onCreated={id => { setCreating(false); onOpen(id); }} /> : null}
    <Table rowKey="id" pagination={false} scroll={{ x: 760 }} data={methods}
      columns={[
        { title: t('cm.colName'), dataIndex: 'name', width: 220 },
        { title: t('cm.colType'), width: 130, render: (_, row: CalculationMethod) => typeOf(row) },
        { title: t('cm.colCategories'), width: 220, render: (_, row: CalculationMethod) => isCaliber(row)
          ? (row.category_summary?.length ? row.category_summary.join('、') : t('cm.tagNoCategoryHint'))
          : '—' },
        { title: t('cm.colPurpose'), width: 130, render: (_, row: CalculationMethod) => purposeText(t, row.purpose) },
        { title: t('cm.colModel'), width: 140, render: () => revisionLabel },
        { title: t('cm.colStatus'), width: 120, render: (_, row: CalculationMethod) => statusText(t, row.latest_status ?? row.status) },
        { title: '', width: 110, fixed: 'right' as const, render: (_, row: CalculationMethod) => <Button type="text" size="small" onClick={() => onOpen(row.id)}>{t('cm.viewDetail')}</Button> },
      ]} />
    <h2>{t('cm.officialGroup')}</h2>
    <p className="helper-text">{t('cm.officialPackagesSummary', { count: packages.length })}</p>
    {/* Package ids are engineering identifiers: they stay behind the disclosure, not in the list. */}
    <details className="calculation-methods__packages">
      <summary>{t('cm.officialPackagesDetail')}</summary>
      {packagesLoading ? <LoadingState rows={1} /> : <Table rowKey="id" pagination={false} scroll={{ x: 520 }} data={packages}
        columns={[
          { title: t('cm.colName'), dataIndex: 'package_id', width: 260 },
          { title: t('cm.colPurpose'), width: 200, render: (_, row: MethodPackage) => packageKindText(t, row.package_kind) },
          { title: t('cm.versionLabel'), dataIndex: 'version', width: 120 },
        ]} />}
    </details>
  </section>;
}
