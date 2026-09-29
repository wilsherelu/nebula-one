import { Alert, Button, Select, Table } from '@arco-design/web-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { api } from '../api/client';
import type { MethodPackage, OrganizationLifecycleActivity, SolvedSystemSnapshot } from '../api/types';
import { useI18n } from '../i18n';
import { EmptyState, ErrorState, LoadingState } from './ui/States';

interface CategoryRule { name?: string; factor_boundary?: string; boundary_status?: string; eligible_consumer_exchange_ids?: string[]; exchange_labels?: Record<string, string> }
interface Entry { enabled: boolean; factorRef: string; factor: string; version: string; source: string; hash: string; evidenceRole: 'supplier_specific' | 'demonstration_proxy'; methodId: string; methodVersion: string; methodHash: string; referenceProduct: string }
export function OrganizationLifecyclePanel({ applicationId, snapshot, method, methodPackages = [] }: { applicationId: string; snapshot: SolvedSystemSnapshot; method: MethodPackage; methodPackages?: MethodPackage[] }) {
  const { lang, t, formatNumber } = useI18n();
  const format = (value: number | null | undefined) => formatNumber(value, { maximumSignificantDigits: 9 });
  const queryClient = useQueryClient();
  const periods = useQuery({ queryKey: ['periods', applicationId], queryFn: () => api.periods(applicationId) });
  const workspace = useQuery({ queryKey: ['workspace', applicationId, snapshot.system_revision_id, lang], queryFn: () => api.workspace(applicationId, snapshot.system_revision_id, lang) });
  const records = useQuery({ queryKey: ['organization-lifecycle', applicationId], queryFn: () => api.organizationLifecycleInventories(applicationId) });
  const display = useQuery({ queryKey: ['organization-lifecycle-display', method.package_id, method.version, method.content_sha256, lang],
    queryFn: () => api.organizationLifecycleDisplay(method, lang),
    enabled: lang === 'en' && Boolean(method.content_sha256) && Array.isArray(snapshot.provider_receipt.project_background_process_receipts),
  });
  const [periodId, setPeriodId] = useState('');
  const [facility, setFacility] = useState('');
  const [output, setOutput] = useState('');
  const [basisMode, setBasisMode] = useState<'per_unit_product' | 'annual_total'>('per_unit_product');
  const [entries, setEntries] = useState<Record<string, Entry>>({});
  const rules = ((method.manifest.classification_rules as Record<string, unknown> | undefined)?.other_value_chain_categories ?? {}) as Record<string, CategoryRule>;
  const projectSupplyMethod = (method.manifest.classification_rules as Record<string, unknown> | undefined)?.energy_path_source === 'project_background_process_receipts';
  const labels = (method.manifest.display_labels ?? {}) as { input_basis?: Record<string, string>; group_status?: Record<string, string> };
  const categoryName = (key: string) => lang === 'en' ? display.data?.labels.categories[key] ?? key : rules[key]?.name ?? key;
  const exchangeName = (key: string, rule: CategoryRule) => lang === 'en' ? display.data?.labels.exchanges[key] ?? key : rule.exchange_labels?.[key] ?? key;
  const groupStatus = (key: string) => lang === 'en' ? display.data?.labels.group_status[key] ?? key : labels.group_status?.[key] ?? key;
  const basis = (snapshot.provider_receipt.calculation_basis ?? {}) as Record<string, unknown>;
  const demand = Array.isArray(basis.demand) ? basis.demand[0] as { amount?: number; unit?: string } | undefined : undefined;
  const baseline = Number(demand?.amount);
  const scale = basisMode === 'annual_total' ? 1 : Number(output) / baseline;
  const matching = useMemo(() => (records.data ?? []).filter(item => item.solved_snapshot_id === snapshot.id
    && item.result.method_package.reference === `${method.package_id}@${method.version}`),
  [records.data, snapshot.id, method.package_id, method.version]);
  const update = (key: string, patch: Partial<Entry>) => setEntries(previous => ({ ...previous, [key]: {
    ...(previous[key] ?? { enabled: false, factorRef: '', factor: '', version: '', source: '', hash: '', evidenceRole: 'demonstration_proxy', methodId: '', methodVersion: '', methodHash: '', referenceProduct: '' }),
    ...patch,
  } }));
  const selectFactor = (key: string, reference: string) => {
    const pack = methodPackages.find(item => `${item.package_id}@${item.version}` === reference);
    const factor = pack?.manifest.factor as { value?: number; evidence_role?: Entry['evidenceRole']; reference_flow_uuid?: string;
      evidence?: { source?: string; sha256?: string }; climate_method?: { id?: string; version?: string; content_sha256?: string } } | undefined;
    update(key, { factorRef: reference, factor: factor?.value == null ? '' : String(factor.value), version: pack?.version ?? '',
      source: factor?.evidence?.source ?? '', hash: factor?.evidence?.sha256 ?? '', evidenceRole: factor?.evidence_role ?? 'demonstration_proxy',
      methodId: factor?.climate_method?.id ?? '', methodVersion: factor?.climate_method?.version ?? '',
      methodHash: factor?.climate_method?.content_sha256 ?? '', referenceProduct: factor?.reference_flow_uuid ?? '' });
  };
  const create = useMutation({
    mutationFn: () => {
      if (!periodId || !facility.trim() || !Number.isFinite(scale) || scale <= 0 || !workspace.data?.process_graph?.nodes.length) {
        throw new Error(t('org.missingForm'));
      }
      const activities: OrganizationLifecycleActivity[] = Object.entries(rules).flatMap(([category, rule]) => (rule.eligible_consumer_exchange_ids ?? []).flatMap(exchangeId => {
        const entry = entries[`${category}:${exchangeId}`];
        if (!entry?.enabled) return [];
        const rule = rules[category];
        const exchange = snapshot.scaled_technosphere_exchanges.find(item => item.exchange_id === exchangeId);
        if (!rule?.eligible_consumer_exchange_ids?.includes(exchangeId) || !exchange) throw new Error(t('org.wrongCategory'));
        const quantity = Number(exchange.amount) * scale;
        if (!Number.isFinite(quantity) || quantity <= 0 || !Number.isFinite(Number(entry.factor)) || Number(entry.factor) <= 0) throw new Error(t('org.invalidActivity'));
        return [{ activity_id: `${category}:${exchangeId}`, category, consumer_exchange_id: exchangeId,
          quantity, activity_unit: String(exchange.unit), factor_value: Number(entry.factor),
          factor_unit: `kg CO2-Eq/${String(exchange.unit)}`, factor_version: entry.version, factor_source: entry.source,
          factor_boundary: rule.factor_boundary ?? '', evidence_sha256: entry.hash, evidence_role: entry.evidenceRole,
          factor_package_ref: entry.factorRef || null,
          outside_model: true, factor_method_id: entry.methodId || null,
          factor_method_version: entry.methodVersion || null, factor_method_sha256: entry.methodHash || null,
          factor_reference_product: entry.referenceProduct || null }];
      }));
      return api.createOrganizationLifecycleInventory(applicationId, {
        solved_snapshot_id: snapshot.id, method_package_ref: `${method.package_id}@${method.version}`,
        reporting_period_id: periodId, facility: facility.trim(),
        controlled_process_ids: workspace.data.process_graph.nodes.map(node => node.id),
        input_basis: basisMode, period_product_output: Number(output), other_activities: activities,
      });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['organization-lifecycle', applicationId] }),
  });
  if (projectSupplyMethod
    ? !Array.isArray(snapshot.provider_receipt.project_background_process_receipts) || !snapshot.provider_receipt.project_background_process_receipts.length
    : !snapshot.native_background_climate) {
    return <EmptyState description={projectSupplyMethod ? t('org.needSupply') : t('org.needNative')} />;
  }
  if (lang === 'en' && display.isLoading) return <LoadingState rows={4} />;
  if (lang === 'en' && display.isError) return <ErrorState error={display.error} />;
  return <div className="pcf-result">
    <h3>{t('org.title')}</h3>
    <p>{t('org.intro')}</p>
    <Alert type="info" content={t('org.scopeNote')} />
    {periods.isLoading || workspace.isLoading || records.isLoading ? <LoadingState rows={4} /> : null}
    {periods.isError || workspace.isError || records.isError ? <ErrorState error={periods.error || workspace.error || records.error} /> : null}
    <div className="project-period-form">
      <label>{t('org.period')}<Select aria-label={t('org.periodAria')} value={periodId} onChange={setPeriodId} options={(periods.data ?? []).map(item => ({ label: `${item.name} · ${item.start_date}—${item.end_date}`, value: item.id }))} /></label>
      <label>{t('org.facility')}<input aria-label={t('org.facilityAria')} value={facility} onChange={event => setFacility(event.target.value)} /></label>
      <label>{t('org.basis')}<Select aria-label={t('org.basis')} value={basisMode} onChange={value => setBasisMode(value as typeof basisMode)} options={[{ label: lang === 'zh' ? labels.input_basis?.per_unit_product ?? t('org.perProduct') : t('org.perProduct'), value: 'per_unit_product' }, { label: lang === 'zh' ? labels.input_basis?.annual_total ?? t('org.annual') : t('org.annual'), value: 'annual_total' }]} /></label>
      <label>{t('org.output', { unit: demand?.unit ?? 'kg' })}<input aria-label={t('org.outputAria')} type="number" min="0" step="any" value={output} onChange={event => setOutput(event.target.value)} /></label>
      <p>{t('org.baseline', { value: format(baseline), unit: demand?.unit ?? '' })}</p>
    </div>
    <h4>{t('org.otherActivities')}</h4>
    {Object.entries(rules).map(([category, rule]) => <div className="section-panel" key={category}>
        <strong>{categoryName(category)}</strong>
        {(rule.eligible_consumer_exchange_ids ?? []).length === 0 ? <p>{rule.boundary_status === 'not_in_boundary' ? t('org.outOfBoundary') : t('org.missingPath')}</p> : null}
        {(rule.eligible_consumer_exchange_ids ?? []).map(exchangeId => {
          const key = `${category}:${exchangeId}`;
          const entry = entries[key];
          const exchange = snapshot.scaled_technosphere_exchanges.find(item => item.exchange_id === exchangeId);
          const factorOptions = methodPackages.filter(item => {
            const factor = item.manifest.factor as { consumer_exchange_id?: string; reference_flow_uuid?: string; boundary?: string } | undefined;
            return item.package_kind === 'organization_lifecycle_factor' && factor?.consumer_exchange_id === exchangeId
              && factor?.reference_flow_uuid === exchange?.flow_uuid && factor?.boundary === rule.factor_boundary
              && (!periodId || !(periods.data ?? []).some(period => period.id === periodId)
                || (item.valid_from != null && item.valid_to != null && item.valid_from <= (periods.data ?? []).find(period => period.id === periodId)!.start_date
                  && item.valid_to >= (periods.data ?? []).find(period => period.id === periodId)!.end_date));
          });
          return <div className="project-period-form" key={exchangeId}>
            <label><input aria-label={t('org.enableFactor', { key })} type="checkbox" checked={entry?.enabled ?? false} onChange={event => update(key, { enabled: event.target.checked })} />{exchangeName(exchangeId, rule)}</label>
            {entry?.enabled ? <>
              <span>{t('org.periodAmount', { amount: exchange ? `${format(Number(exchange.amount) * scale)} ${String(exchange.unit)}` : t('org.noExchange') })} </span>
              {factorOptions.length ? <label>{t('org.registeredEvidence')}<Select aria-label={t('org.registeredEvidence')} value={entry.factorRef} onChange={value => selectFactor(key, value)}
                options={[{ label: t('org.manualEvidence'), value: '' }, ...factorOptions.map(item => ({ label: `${item.package_id} · ${item.version}`, value: `${item.package_id}@${item.version}` }))]} /></label>
                : <p>{t('org.noRegisteredFactor')}</p>}
              {entry.factorRef ? <p>{t('org.factorSelected', { version: entry.version })}</p> : <details><summary>{t('org.advanced')}</summary>
              <label>{t('org.factor')}<input aria-label={t('org.factor')} type="number" min="0" step="any" value={entry.factor} onChange={event => update(key, { factor: event.target.value })} /></label>
              <label>{t('org.factorVersion')}<input aria-label={t('org.factorVersion')} value={entry.version} onChange={event => update(key, { version: event.target.value })} /></label>
              <label>{t('org.factorSource')}<input aria-label={t('org.factorSource')} value={entry.source} onChange={event => update(key, { source: event.target.value })} /></label>
              <label>{t('org.sourceHash')}<input aria-label={t('org.sourceHash')} value={entry.hash} onChange={event => update(key, { hash: event.target.value })} /></label>
              <label>{t('org.evidenceType')}<Select aria-label={t('org.evidenceType')} value={entry.evidenceRole} onChange={value => update(key, { evidenceRole: value as Entry['evidenceRole'] })} options={[{ label: t('org.exampleProxy'), value: 'demonstration_proxy' }, { label: t('org.supplierEvidence'), value: 'supplier_specific' }]} /></label>
              {entry.evidenceRole === 'supplier_specific' ? <>
                <label>{t('org.climateMethodId')}<input aria-label={t('org.climateMethodId')} value={entry.methodId} onChange={event => update(key, { methodId: event.target.value })} /></label>
                <label>{t('org.climateMethodVersion')}<input aria-label={t('org.climateMethodVersion')} value={entry.methodVersion} onChange={event => update(key, { methodVersion: event.target.value })} /></label>
                <label>{t('org.climateMethodHash')}<input aria-label={t('org.climateMethodHash')} value={entry.methodHash} onChange={event => update(key, { methodHash: event.target.value })} /></label>
                <label>{t('org.referenceProduct')}<input aria-label={t('org.referenceProduct')} value={entry.referenceProduct} onChange={event => update(key, { referenceProduct: event.target.value })} /></label>
              </> : null}
              </details>}
            </> : null}
            <details><summary>{t('org.flowIdentity')}</summary><small>{exchangeId}</small></details>
          </div>;
        })}
      </div>)}
    <Button type="primary" loading={create.isPending} onClick={() => create.mutate()}>{t('org.calculate')}</Button>
    {create.isError ? <ErrorState error={create.error} /> : null}
    <h4>{t('org.savedResults')}</h4>
    {matching.length ? matching.map(record => <section className="section-panel" key={record.id}>
      <strong>{record.result.reporting_period.name} · {record.result.facility}</strong>
      <p><Button href={`/api/v1/applications/${applicationId}/organization-lifecycle-inventories/${record.id}/report.html?lang=${lang}`} target="_blank">{t('org.openReport')}</Button></p>
      <p>{t('org.resultBasis', { basis: lang === 'en' ? display.data?.labels.input_basis[record.result.activity_basis.mode] ?? record.result.activity_basis.mode : labels.input_basis?.[record.result.activity_basis.mode] ?? record.result.activity_basis.mode, output: format(record.result.activity_basis.period_output), scale: format(record.result.activity_basis.scale_factor) })}</p>
      <Table rowKey="key" pagination={false} data={[
        { key: 'direct', ...record.result.groups.on_site_direct, label: t('org.groupDirect') },
        { key: 'energy', ...record.result.groups.purchased_energy_lifecycle, label: t('org.groupEnergy') },
        { key: 'other', ...record.result.groups.other_value_chain, label: t('org.groupOther') },
      ]} columns={[{ title: t('org.group'), dataIndex: 'label' }, { title: t('org.emissions'), render: (_, row) => `${format(row.value)} ${row.unit}` }, { title: t('org.status'), render: (_, row) => groupStatus(row.status) }]} />
      <p>{t('org.coverage', { total: format(record.result.combined_total), missing: record.result.coverage.missing_categories.map(categoryName).join(lang === 'zh' ? '、' : ', ') || t('org.none'), outside: (record.result.coverage.not_in_boundary_categories ?? []).map(categoryName).join(lang === 'zh' ? '、' : ', ') || t('org.none'), proxy: record.result.coverage.demonstration_proxy_activity_ids.length ? t('org.itemCount', { count: record.result.coverage.demonstration_proxy_activity_ids.length }) : t('org.none') })}</p>
      {record.result.groups.other_value_chain.categories.filter(item => item.proxy_reference_value != null).map(item => <p key={item.category}>{t('org.proxyReference', { name: categoryName(item.category), value: format(item.proxy_reference_value) })}</p>)}
      <small>{t('org.methodEvidence', { method: record.result.method_package.reference, hash: record.content_sha256 })}</small>
    </section>) : <EmptyState description={t('org.noResults')} />}
  </div>;
}
