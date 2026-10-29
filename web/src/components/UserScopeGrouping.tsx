import { Alert, Table } from '@arco-design/web-react';
import { useI18n } from '../i18n';

interface Bucket { value: number | null; unit?: string | null; term_count?: number }
interface Grouping {
  scopes?: Partial<Record<'scope_1' | 'scope_2' | 'scope_3', Bucket>>;
  excluded?: Bucket;
  unattributed?: Bucket;
  engine_gap?: Bucket;
  reconciled?: boolean;
}

/** Display frozen engine contributions only; this component never classifies or calculates them. */
export function UserScopeGrouping({ grouping }: { grouping?: Record<string, unknown> | null }) {
  const { t, formatNumber } = useI18n();
  const values = grouping as Grouping | undefined;
  if (!values?.scopes) return null;
  const rows = Object.entries(values.scopes).map(([key, bucket]) => ({ key, name: t(`cm.scope.${key as 'scope_1' | 'scope_2' | 'scope_3'}`), ...bucket }));
  for (const key of ['excluded', 'unattributed', 'engine_gap'] as const) {
    const bucket = values[key];
    if (bucket) rows.push({ key, name: t(`pcf.scopeBucket.${key}`), ...bucket });
  }
  return <>
    {values.reconciled === false ? <Alert type="warning" content={t('pcf.scopeUnreconciled')} /> : null}
    <Table rowKey="key" pagination={false} data={rows} aria-label={t('pcf.scopeValues')} columns={[
      { title: t('pcf.dimGroupCategory'), dataIndex: 'name' },
      { title: t('pcf.dimGroupValue'), render: (_, row) => row.value == null ? '—' : `${formatNumber(row.value)} ${row.unit ?? ''}` },
    ]} />
  </>;
}
