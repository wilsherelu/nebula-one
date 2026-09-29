import { Alert, Button, Descriptions, Drawer, Select, Tag } from '@arco-design/web-react';
import { IconExpand, IconInfoCircle } from '@arco-design/web-react/icon';
import { useQuery } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import { useUrlSelection, type InvalidReference } from '../hooks/useUrlSelection';
import type { MethodPackage, OrganizationGhgInventoryV1Request, SystemBinding } from '../api/types';
import { CopyableValue } from './ui/CopyableValue';
import { InvalidReferencesAlert } from './ui/InvalidReferencesAlert';
import { MetricCard } from './ui/MetricCard';
import { EmptyState, ErrorState } from './ui/States';
import { StatusBadge } from './ui/StatusBadge';

interface Props {
  applicationId: string;
  bindings: SystemBinding[];
  organizationMethods: MethodPackage[];
  pcfMethods: MethodPackage[];
  enabled: boolean;
}

interface RoleClassification {
  scope: string;
  category: string;
}

function reference(item: MethodPackage | undefined): string {
  return item ? `${item.package_id}@${item.version}` : '';
}

function roleMatches(role: string, pattern: string): boolean {
  return pattern.endsWith('*') ? role.startsWith(pattern.slice(0, -1)) : role === pattern;
}

export function classifyBindingRole(role: string, method: MethodPackage | undefined): RoleClassification | undefined {
  const rules = method?.manifest.classification_rules;
  if (!rules || typeof rules !== 'object') return undefined;
  const mappings = (rules as Record<string, unknown>).role_mappings;
  if (!Array.isArray(mappings)) return undefined;
  const matches = mappings.flatMap((candidate) => {
    if (!candidate || typeof candidate !== 'object') return [];
    const item = candidate as Record<string, unknown>;
    if (typeof item.role_pattern !== 'string' || typeof item.scope !== 'string' || typeof item.category !== 'string') return [];
    return roleMatches(role, item.role_pattern) ? [{ scope: item.scope, category: item.category }] : [];
  });
  return matches.length === 1 ? matches[0] : undefined;
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

function amount(value: number): string {
  return Number.isFinite(value) ? value.toLocaleString('zh-CN', { maximumFractionDigits: 4 }) : '—';
}

export function OrganizationGhgInventoryFormalPanel({ applicationId, bindings, organizationMethods, pcfMethods, enabled }: Props) {
  const models = useQuery({ queryKey: ['models', applicationId], queryFn: () => api.models(applicationId), enabled });
  const periods = useQuery({ queryKey: ['periods', applicationId], queryFn: () => api.periods(applicationId), enabled });
  const [auditVisible, setAuditVisible] = useState(false);
  const organizationRefs = useMemo(() => organizationMethods.map(reference), [organizationMethods]);
  const pcfRefs = useMemo(() => pcfMethods.map(reference), [pcfMethods]);
  const organizationMethod = useUrlSelection('ghg-method', organizationRefs);
  const pcfMethod = useUrlSelection('ghg-pcf', pcfRefs);
  const invalidReferences = useMemo(() => [
    organizationMethod.invalid ? { label: '组织清单方法包', requested: organizationMethod.requested, key: 'ghg-method' } : null,
    pcfMethod.invalid ? { label: 'PCF 方法包', requested: pcfMethod.requested, key: 'ghg-pcf' } : null,
  ].filter((item): item is InvalidReference => Boolean(item)), [organizationMethod, pcfMethod]);
  const selectedMethod = organizationMethods.find((item) => reference(item) === organizationMethod.value);
  const orderedBindings = useMemo(() => [...bindings].sort((left, right) => left.binding_id.localeCompare(right.binding_id)), [bindings]);
  const classifiedBindings = useMemo(() => orderedBindings.map((binding) => ({ binding, classification: classifyBindingRole(binding.role, selectedMethod) })), [orderedBindings, selectedMethod]);
  const classificationComplete = classifiedBindings.every((item) => item.classification);
  const request = useMemo(() => (
    !invalidReferences.length && organizationMethod.value && pcfMethod.value && orderedBindings.length && classificationComplete
      ? {
        method_package_ref: organizationMethod.value,
        pcf_method_package_ref: pcfMethod.value,
        binding_ids: orderedBindings.map((item) => item.binding_id),
      } satisfies OrganizationGhgInventoryV1Request
      : undefined
  ), [classificationComplete, invalidReferences.length, orderedBindings, organizationMethod.value, pcfMethod.value]);
  const aggregate = useQuery({
    queryKey: ['organization-ghg-inventory', applicationId, request ?? null],
    queryFn: () => api.organizationGhgInventoryV1(applicationId, request!),
    enabled: Boolean(enabled && request),
  });
  const chart = useQuery({
    queryKey: ['organization-ghg-inventory-chart', applicationId, request ?? null],
    queryFn: () => api.organizationGhgInventoryV1Chart(applicationId, request!),
    enabled: Boolean(enabled && aggregate.data),
  });
  const chartUrl = useObjectUrl(chart.data);
  const result = aggregate.data;

  if (!enabled) return null;
  if (!bindings.length) return <EmptyState description="当前应用没有 active System Binding，正式组织清单暂不可执行。" />;
  if (!organizationMethods.length || !pcfMethods.length) return <EmptyState description="当前应用没有同时绑定正式组织清单与产品碳足迹方法包。" />;
  if (invalidReferences.length) {
    return <InvalidReferencesAlert references={invalidReferences} note="未使用其它方法包替代链接中的引用。" />;
  }

  return <div className="organization-ghg organization-ghg--formal">
    <div className="period-trend__head">
      <div><h3>组织温室气体清单</h3><p>按同一组织边界和报告期汇总独立活动系统，不要求装置彼此相连。</p></div>
      <Button type="primary" loading={aggregate.isFetching} disabled={!request || aggregate.isFetching} onClick={() => aggregate.refetch()}>执行聚合</Button>
    </div>
    <div className="organization-ghg__methods organization-ghg__methods--formal">
      <div><label htmlFor="formal-ghg-method">组织清单方法</label><Select id="formal-ghg-method" value={organizationMethod.value} onChange={organizationMethod.select} options={organizationMethods.map((item) => ({ value: reference(item), label: `${item.package_id} · ${item.version}` }))} /></div>
      <div><label htmlFor="formal-pcf-method">PCF 方法</label><Select id="formal-pcf-method" value={pcfMethod.value} onChange={pcfMethod.select} options={pcfMethods.map((item) => ({ value: reference(item), label: `${item.package_id} · ${item.version}` }))} /></div>
    </div>
    <div className="organization-binding-grid" aria-label="System Binding 与 Scope 分类">
      {classifiedBindings.map(({ binding, classification }) => <article className="organization-binding-card" key={binding.binding_id}>
        <div><strong>{models.data?.find((model) => model.id === binding.system_model_id)?.name ?? '活动系统名称未提供'}</strong><small>{periods.data?.find((period) => period.id === binding.reporting_period_id)?.name ?? '报告期信息未提供'}</small></div>
        {classification ? <div className="inline-actions"><Tag color="arcoblue">{classification.scope}</Tag><Tag>{classification.category}</Tag></div> : <Tag color="red">未唯一分类</Tag>}
      </article>)}
    </div>
    {!classificationComplete ? <Alert type="error" title="Binding 角色不可聚合" content="至少一个 active binding 未能被当前方法包唯一分类。" /> : null}
    {aggregate.error ? <ErrorState error={aggregate.error} onRetry={() => aggregate.refetch()} /> : null}
    {chart.error ? <ErrorState error={chart.error} onRetry={() => chart.refetch()} /> : null}
    {result ? <>
      <div className="organization-ghg__summary organization-ghg__summary--formal">
        {result.scopes.map((scope) => <MetricCard key={scope.scope} label={scope.scope.replace('_', ' ').toUpperCase()} value={amount(scope.total.value)} unit={scope.total.unit} />)}
        <MetricCard label="组织总量" value={amount(result.total.value)} unit={result.total.unit} />
      </div>
      <div className="period-trend__summary"><StatusBadge status={result.audit.status} /><span>{result.audit.source_binding_count} 个活动系统</span><Button type="text" size="small" icon={<IconInfoCircle />} onClick={() => setAuditVisible(true)}>清单审计</Button></div>
      <Alert type="info" content="仅汇总已绑定并通过校验的活动；未纳入的范围或类别不代表零排放。" />
      {chartUrl ? <div className="organization-ghg__chart" tabIndex={0} role="region" aria-label="组织温室气体清单图滚动区域"><div className="pcf-result__chart-toolbar"><strong>Scope 聚合结果</strong><Button type="text" size="small" icon={<IconExpand />} href={chartUrl} target="_blank" rel="noreferrer">打开全图</Button></div><img src={chartUrl} alt="组织温室气体清单聚合图" /></div> : null}
      <Drawer className="audit-drawer" width={560} visible={auditVisible} onCancel={() => setAuditVisible(false)} footer={null} title="组织清单证据" unmountOnExit>
        <Descriptions column={1} size="small" border data={[
          { label: '结果 hash', value: <CopyableValue value={result.content_sha256} compact={false} /> },
          { label: '方法包 hash', value: <CopyableValue value={result.method_package.content_sha256} compact={false} /> },
          { label: '报告期 ID', value: <CopyableValue value={result.reporting_period_id} compact={false} /> },
          { label: '组织边界 ID', value: <CopyableValue value={result.organizational_boundary_id} compact={false} /> },
        ]} />
        <h3 className="audit-heading">Binding 回执</h3><pre className="audit-json">{JSON.stringify(orderedBindings, null, 2)}</pre>
        <h3 className="audit-heading">Scope 来源</h3><pre className="audit-json">{JSON.stringify(result.scopes, null, 2)}</pre>
        <h3 className="audit-heading">完整性检查</h3><pre className="audit-json">{JSON.stringify(result.audit, null, 2)}</pre>
      </Drawer>
    </> : null}
  </div>;
}
