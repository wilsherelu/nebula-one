import { Alert, Button, Descriptions, Drawer, Select, Tabs } from '@arco-design/web-react';
import { IconExpand, IconInfoCircle } from '@arco-design/web-react/icon';
import { useQuery } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { api, formatDate, shortId } from '../api/client';
import { useI18n } from '../i18n';
import { useUrlSelection, useUrlSelectionMap, type InvalidReference } from '../hooks/useUrlSelection';
import type {
  EnergyCarrierResult,
  InventorySnapshot,
  MethodPackage,
  OrganizationGhgInventoryRequest,
  ReportingPeriod,
  SolvedSystemSnapshot,
} from '../api/types';
import { OrganizationGhgInventoryFormalPanel } from './OrganizationGhgInventoryFormalPanel';
import { resolvePeriodTotalRequest } from './PeriodEnergyTotalPanel';
import { CopyableValue } from './ui/CopyableValue';
import { InvalidReferencesAlert } from './ui/InvalidReferencesAlert';
import { MetricCard } from './ui/MetricCard';
import { EmptyState, ErrorState, LoadingState } from './ui/States';
import { StatusBadge, statusLabel } from './ui/StatusBadge';

interface Props {
  applicationId: string;
  snapshots: SolvedSystemSnapshot[];
  organizationMethods: MethodPackage[];
  formalOrganizationMethods?: MethodPackage[];
  pcfMethods?: MethodPackage[];
  carbonMethods: MethodPackage[];
  provinceMethods: MethodPackage[];
  enabled: boolean;
  packagesLoading: boolean;
  packagesError: unknown;
  onPackagesRetry: () => void;
}

interface ProvinceScenario {
  id: string;
  label: string;
}

function reference(item: MethodPackage | undefined): string {
  return item ? `${item.package_id}@${item.version}` : '';
}

export function provinceScenarios(item: MethodPackage | undefined): ProvinceScenario[] {
  const classification = item?.manifest.classification_rules;
  if (!classification || typeof classification !== 'object') return [];
  const scenarios = (classification as Record<string, unknown>).scenarios;
  if (!Array.isArray(scenarios)) return [];
  return scenarios.flatMap((candidate) => {
    if (!candidate || typeof candidate !== 'object') return [];
    const record = candidate as Record<string, unknown>;
    if (typeof record.scenario_id !== 'string' || typeof record.province_name !== 'string') return [];
    return [{ id: record.scenario_id, label: record.province_name }];
  });
}

export function suggestPeriodBindings(
  periods: ReportingPeriod[],
  energyResults: EnergyCarrierResult[],
  snapshots: SolvedSystemSnapshot[],
  inventories: InventorySnapshot[],
): Record<string, string> {
  const snapshotById = new Map(snapshots.map((item) => [item.id, item]));
  return Object.fromEntries(periods.flatMap((period) => {
    const revisions = [...new Set(inventories.filter((item) => (
      item.period_id === period.id && item.status === 'frozen' && item.content_sha256
    )).map((item) => item.system_revision_id))];
    if (revisions.length !== 1) return [];
    const matches = energyResults.filter((item) => (
      snapshotById.get(item.solved_snapshot_id)?.system_revision_id === revisions[0]
    ));
    return matches.length === 1 ? [[period.id, matches[0].id]] : [];
  }));
}

function useObjectUrl(blob: Blob | undefined): string | undefined {
  const [url, setUrl] = useState<string>();
  useEffect(() => {
    if (!blob || typeof URL.createObjectURL !== 'function') return setUrl(undefined);
    const next = URL.createObjectURL(blob);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [blob]);
  return url;
}

function amount(value: string | null): string {
  if (value === null) return '未计算';
  const parsed = Number(value);
  return Number.isFinite(parsed)
    ? parsed.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
    : value;
}

export function OrganizationGhgInventoryPanel(props: Props) {
  const mode = useUrlSelection('ghg-tab', ['formal', 'trial']);
  const systemBindings = useQuery({
    queryKey: ['system-bindings', props.applicationId],
    queryFn: () => api.systemBindings(props.applicationId),
    enabled: props.enabled,
  });
  const activeBindings = useMemo(() => (systemBindings.data ?? []).filter((item) => item.status === 'active'), [systemBindings.data]);
  if (!props.enabled) return null;
  if (mode.invalid) return <InvalidReferencesAlert references={[{ label: '清单视图', requested: mode.requested, key: 'ghg-tab' }]} />;
  return <Tabs activeTab={mode.value} onChange={mode.select}>
    <Tabs.TabPane key="formal" title="正式清单">
      {systemBindings.isLoading || props.packagesLoading ? <LoadingState rows={8} /> : null}
      {systemBindings.isError || props.packagesError ? <ErrorState error={systemBindings.error || props.packagesError} onRetry={() => { systemBindings.refetch(); props.onPackagesRetry(); }} /> : null}
      {!systemBindings.isLoading && !systemBindings.isError && !props.packagesLoading && !props.packagesError ? (
        <OrganizationGhgInventoryFormalPanel
          applicationId={props.applicationId}
          bindings={activeBindings}
          organizationMethods={props.formalOrganizationMethods ?? []}
          pcfMethods={props.pcfMethods ?? []}
          enabled={mode.value === 'formal'}
        />
      ) : null}
    </Tabs.TabPane>
    <Tabs.TabPane key="trial" title="兼容试算">
      <OrganizationGhgInventoryTrialPanel {...props} enabled={mode.value === 'trial'} />
    </Tabs.TabPane>
  </Tabs>;
}

function OrganizationGhgInventoryTrialPanel(props: Props) {
  const { lang } = useI18n();
  const [auditVisible, setAuditVisible] = useState(false);
  const periods = useQuery({ queryKey: ['periods', props.applicationId], queryFn: () => api.periods(props.applicationId), enabled: props.enabled });
  const energyResults = useQuery({
    queryKey: ['application-energy-results', props.applicationId, props.snapshots.map((item) => item.id)],
    queryFn: async () => (await Promise.all(props.snapshots.map((snapshot) => api.energyCarrierResults(snapshot.id)))).flat(),
    enabled: props.enabled && props.snapshots.length > 0,
  });
  const inventories = useQuery({ queryKey: ['inventory-snapshots', props.applicationId], queryFn: () => api.inventorySnapshots(props.applicationId), enabled: props.enabled });
  const frozenInventoryIds = useMemo(() => (inventories.data ?? []).filter((item) => item.status === 'frozen').map((item) => item.id).sort(), [inventories.data]);
  const points = useQuery({
    queryKey: ['organization-ghg-points', props.applicationId, frozenInventoryIds],
    queryFn: async () => (await Promise.all(frozenInventoryIds.map((id) => api.inventoryDataPoints(id)))).flat(),
    enabled: props.enabled && frozenInventoryIds.length > 0,
  });
  const orderedPeriods = useMemo(() => [...(periods.data ?? [])].sort((left, right) => left.start_date.localeCompare(right.start_date)), [periods.data]);
  const loadError = props.packagesError || periods.error || energyResults.error || inventories.error || points.error;
  const catalogReady = !loadError && !props.packagesLoading && !periods.isLoading && !energyResults.isLoading && !inventories.isLoading && !points.isLoading;
  const organizationRefs = useMemo(() => props.organizationMethods.map(reference), [props.organizationMethods]);
  const carbonRefs = useMemo(() => props.carbonMethods.map(reference), [props.carbonMethods]);
  const provinceRefs = useMemo(() => props.provinceMethods.map(reference), [props.provinceMethods]);
  const missingPackageLabels = [
    ...props.organizationMethods.length ? [] : ['组织清单方法包'],
    ...props.carbonMethods.length ? [] : ['直接贡献方法包'],
    ...props.provinceMethods.length ? [] : ['分省电力因子方法包'],
  ];
  const organizationMethod = useUrlSelection('ghg-trial-method', organizationRefs, { ready: catalogReady });
  const carbonMethod = useUrlSelection('ghg-trial-carbon', carbonRefs, { ready: catalogReady });
  const provinceMethod = useUrlSelection('ghg-trial-province', provinceRefs, { ready: catalogReady, clearKeys: ['ghg-trial-scenario'] });
  const selectedProvinceMethod = props.provinceMethods.find((item) => reference(item) === provinceMethod.value);
  const scenarios = useMemo(() => provinceScenarios(selectedProvinceMethod), [selectedProvinceMethod]);
  const scenarioIds = useMemo(() => scenarios.map((item) => item.id), [scenarios]);
  const scenario = useUrlSelection('ghg-trial-scenario', scenarioIds, { ready: catalogReady });
  const energyIds = useMemo(() => (energyResults.data ?? []).map((item) => item.id), [energyResults.data]);
  const bindingCandidates = useMemo(() => Object.fromEntries(orderedPeriods.map((period) => [period.id, energyIds])), [energyIds, orderedPeriods]);
  const bindings = useUrlSelectionMap('ghg-trial-energy', bindingCandidates, { ready: catalogReady });
  const suggestions = useMemo(() => suggestPeriodBindings(orderedPeriods, energyResults.data ?? [], props.snapshots, inventories.data ?? []), [energyResults.data, inventories.data, orderedPeriods, props.snapshots]);
  const invalidReferences = useMemo(() => [
    organizationMethod.invalid ? { label: '清单方法包', requested: organizationMethod.requested, key: 'ghg-trial-method' } : null,
    carbonMethod.invalid ? { label: '直接贡献方法包', requested: carbonMethod.requested, key: 'ghg-trial-carbon' } : null,
    provinceMethod.invalid ? { label: '购电因子方法包', requested: provinceMethod.requested, key: 'ghg-trial-province' } : null,
    scenario.invalid ? { label: 'Scope 2 地区', requested: scenario.requested, key: 'ghg-trial-scenario' } : null,
    ...bindings.invalid.map((periodId) => ({
      label: `${orderedPeriods.find((period) => period.id === periodId)?.name ?? `期间 ${shortId(periodId)}`}的冻结能源结果`,
      requested: bindings.requested[periodId] ?? periodId,
      key: 'ghg-trial-energy',
    })),
  ].filter((item): item is InvalidReference => Boolean(item)), [bindings, carbonMethod, orderedPeriods, organizationMethod, provinceMethod, scenario]);
  const selectedBindings = useMemo(() => {
    const effective = { ...suggestions, ...bindings.values };
    return orderedPeriods.flatMap((period) => effective[period.id]
      ? [{ period_id: period.id, energy_result_id: effective[period.id] }]
      : []);
  }, [bindings.values, orderedPeriods, suggestions]);
  const baselinePeriodId = orderedPeriods[0]?.id ?? '';
  const resolution = useMemo(() => resolvePeriodTotalRequest(
    selectedBindings,
    baselinePeriodId,
    energyResults.data ?? [],
    props.snapshots,
    inventories.data ?? [],
    points.data ?? [],
  ), [baselinePeriodId, energyResults.data, inventories.data, points.data, props.snapshots, selectedBindings]);
  const completeCoverage = orderedPeriods.length >= 2 && selectedBindings.length === orderedPeriods.length;
  const payload = completeCoverage && resolution.request && !invalidReferences.length && organizationMethod.value && carbonMethod.value && provinceMethod.value && scenario.value
    ? {
      method_package_ref: organizationMethod.value,
      carbon_method_package_ref: carbonMethod.value,
      province_electricity: { method_package_ref: provinceMethod.value, period_energy_total: resolution.request },
      scope_2_scenario_id: scenario.value,
    } satisfies OrganizationGhgInventoryRequest
    : undefined;
  const run = useQuery({
    queryKey: ['organization-ghg-inventory-trial', props.applicationId, payload ?? null],
    queryFn: () => api.organizationGhgInventory(props.applicationId, payload!),
    enabled: Boolean(props.enabled && payload),
  });
  const chart = useQuery({
    queryKey: ['organization-ghg-inventory-trial-chart', props.applicationId, payload ?? null],
    queryFn: () => api.organizationGhgInventoryChart(props.applicationId, payload!),
    enabled: Boolean(props.enabled && run.data),
  });
  const chartUrl = useObjectUrl(chart.data);
  const result = run.data;

  if (!props.enabled) return null;
  if (props.packagesLoading || periods.isLoading || energyResults.isLoading || inventories.isLoading || points.isLoading) return <LoadingState rows={8} />;
  if (loadError) return <ErrorState error={loadError} onRetry={() => { props.onPackagesRetry(); periods.refetch(); energyResults.refetch(); inventories.refetch(); points.refetch(); }} />;
  if (invalidReferences.length) return <InvalidReferencesAlert references={invalidReferences} />;
  if (!props.organizationMethods.length || !props.carbonMethods.length || !props.provinceMethods.length) return <EmptyState description={`当前应用缺少绑定完整的组织清单方法包。缺：${missingPackageLabels.join('、')}。`} />;
  if (orderedPeriods.length < 2 || !energyResults.data?.length) return <EmptyState description={`至少需要两个报告期及其冻结能源结果，才能生成组织清单试算。当前报告期 ${orderedPeriods.length} 个，冻结能源结果 ${energyResults.data?.length ?? 0} 份。`} />;

  return <div className="organization-ghg">
    <Alert type="info" content="该入口保留旧版期间证据试算流程；有 active System Binding 时请优先使用正式清单。" />
    <div className="period-trend__head">
      <div><h3>组织温室气体清单试算</h3><p>组合冻结的期间产量、精确直接贡献和省级购电情景，不补算缺失范围。</p></div>
      <Button type="primary" loading={run.isFetching} disabled={!payload || !completeCoverage || run.isFetching} onClick={() => run.refetch()}>生成组织清单</Button>
    </div>
    <div className="organization-ghg__methods">
      <div><label htmlFor="ghg-method">清单方法</label><Select id="ghg-method" value={organizationMethod.value} onChange={organizationMethod.select} options={props.organizationMethods.map((item) => ({ value: reference(item), label: `${item.package_id} · ${item.version}` }))} /></div>
      <div><label htmlFor="ghg-carbon-method">直接贡献方法</label><Select id="ghg-carbon-method" value={carbonMethod.value} onChange={carbonMethod.select} options={props.carbonMethods.map((item) => ({ value: reference(item), label: `${item.package_id} · ${item.version}` }))} /></div>
      <div><label htmlFor="ghg-province-method">购电因子方法</label><Select id="ghg-province-method" value={provinceMethod.value} onChange={provinceMethod.select} options={props.provinceMethods.map((item) => ({ value: reference(item), label: `${item.package_id} · ${item.version}` }))} /></div>
      <div><label htmlFor="ghg-scope2-scenario">Scope 2 地区</label><Select id="ghg-scope2-scenario" value={scenario.value || undefined} onChange={scenario.select} options={scenarios.map((item) => ({ value: item.id, label: item.label }))} /></div>
    </div>
    <div className="period-trend__bindings">
      {orderedPeriods.map((period) => <div className="period-trend__binding" key={period.id}>
        <div><strong>{period.name}</strong><small>{period.start_date} – {period.end_date}</small></div>
        <Select aria-label={`${period.name}冻结能源结果`} value={bindings.values[period.id] || suggestions[period.id] || undefined} placeholder="选择冻结能源结果" onChange={(value) => bindings.set(period.id, value)} options={(energyResults.data ?? []).map((item) => ({ value: item.id, label: `${formatDate(item.created_at)} · revision ${shortId(props.snapshots.find((snapshot) => snapshot.id === item.solved_snapshot_id)?.system_revision_id)}` }))} />
      </div>)}
    </div>
    {!completeCoverage || resolution.issues.length ? <Alert type="warning" title="期间证据尚未就绪" content={[!completeCoverage ? '每个报告期都必须绑定一份冻结能源结果。' : '', ...resolution.issues].filter(Boolean).join(' ')} /> : <Alert type="success" content="全部报告期已绑定唯一冻结产量证据和求解结果。" />}
    {run.error ? <ErrorState error={run.error} onRetry={() => run.refetch()} /> : null}
    {chart.error ? <ErrorState error={chart.error} onRetry={() => chart.refetch()} /> : null}
    {result ? <>
      <div className="organization-ghg__summary">
        {result.scopes.map((scope) => <MetricCard key={scope.scope} label={scope.scope.replace('_', ' ').toUpperCase()} value={amount(scope.value)} unit={scope.unit ?? undefined} delta={statusLabel(scope.status, lang)} />)}
      </div>
      <div className="period-trend__summary"><StatusBadge status={result.status} /><span>{result.reporting_period.covered_start_date}—{result.reporting_period.covered_end_date}</span><span>综合总量未生成</span><Button type="text" size="small" icon={<IconInfoCircle />} onClick={() => setAuditVisible(true)}>清单审计</Button></div>
      <Alert type="warning" title="部分组织清单" content="Scope 1 仅覆盖模型中已有的精确直接贡献；Scope 2 为所选地区的购电参考值；Scope 3 尚未计算，因此不生成综合总量。" />
      {chartUrl ? <div className="organization-ghg__chart" tabIndex={0} role="region" aria-label="组织温室气体清单图滚动区域"><div className="pcf-result__chart-toolbar"><strong>Scope 结果</strong><Button type="text" size="small" icon={<IconExpand />} href={chartUrl} target="_blank" rel="noreferrer">打开全图</Button></div><img src={chartUrl} alt="组织温室气体清单试算图" /></div> : null}
      <Drawer className="audit-drawer" width={560} visible={auditVisible} onCancel={() => setAuditVisible(false)} footer={null} title="组织清单证据" unmountOnExit>
        <Descriptions column={1} size="small" border data={[
          { label: '结果 hash', value: <CopyableValue value={result.content_sha256} compact={false} /> },
          { label: '方法包 hash', value: <CopyableValue value={result.method_package.content_sha256} compact={false} /> },
          { label: '期间总量 hash', value: <CopyableValue value={result.source_period_energy_total.content_sha256} compact={false} /> },
          { label: '报告期 hash', value: <CopyableValue value={result.reporting_period.content_sha256} compact={false} /> },
        ]} />
        <h3 className="audit-heading">Scope 来源</h3><pre className="audit-json">{JSON.stringify(result.scopes, null, 2)}</pre>
        <h3 className="audit-heading">完整性检查</h3><pre className="audit-json">{JSON.stringify(result.audit, null, 2)}</pre>
      </Drawer>
    </> : null}
  </div>;
}
