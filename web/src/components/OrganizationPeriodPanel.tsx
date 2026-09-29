import { Alert, Button, Select, Table } from '@arco-design/web-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { api } from '../api/client';
import type { MethodPackage, OrganizationPeriodRequest, OrganizationSupplierActivity, SolvedSystemSnapshot } from '../api/types';
import { EmptyState, ErrorState, LoadingState } from './ui/States';

interface CategoryRule { name?: string; factor_boundary?: string; eligible_consumer_exchange_ids?: string[] }
interface Entry { status: 'missing_activity' | 'not_applicable' | 'excluded_by_boundary' | 'calculated'; exchangeId: string; factor: string; version: string; source: string; hash: string; evidenceRole: 'supplier_specific' | 'demonstration_proxy' }

const number = (value: number | null | undefined) => value == null ? '—' : new Intl.NumberFormat('zh-CN', { maximumSignificantDigits: 9 }).format(value);
const statusText = (status: string) => ({ calculated: '已计算', missing_activity: '缺活动数据', not_applicable: '不适用', excluded_by_boundary: '本次边界排除', partial: '部分覆盖', configured_categories: '已按配置计算', model_boundary_direct: '模型受控过程', purchased_energy_native_background_leaf: '历史版本：生命周期背景误归属', missing_generation_only_evidence: '缺仅发电阶段依据' } as Record<string, string>)[status] ?? status;

export function OrganizationPeriodPanel({ applicationId, snapshot, method }: { applicationId: string; snapshot: SolvedSystemSnapshot; method: MethodPackage }) {
  const client = useQueryClient();
  const periods = useQuery({ queryKey: ['periods', applicationId], queryFn: () => api.periods(applicationId) });
  const workspace = useQuery({ queryKey: ['workspace', applicationId, snapshot.system_revision_id], queryFn: () => api.workspace(applicationId, snapshot.system_revision_id) });
  const records = useQuery({ queryKey: ['organization-period', applicationId], queryFn: () => api.organizationPeriodInventories(applicationId) });
  const [periodId, setPeriodId] = useState('');
  const [facility, setFacility] = useState('');
  const [output, setOutput] = useState('');
  const [entries, setEntries] = useState<Record<string, Entry>>({});
  const rules = ((method.manifest.classification_rules as Record<string, unknown> | undefined)?.scope3_categories ?? {}) as Record<string, CategoryRule>;
  const basis = (snapshot.provider_receipt.calculation_basis ?? {}) as Record<string, unknown>;
  const demand = Array.isArray(basis.demand) ? basis.demand[0] as { amount?: number; unit?: string } | undefined : undefined;
  const sourceOutput = demand?.amount;
  const scale = sourceOutput && Number(output) > 0 ? Number(output) / sourceOutput : null;
  const knownRecords = useMemo(() => (records.data ?? []).filter(record => record.solved_snapshot_id === snapshot.id).reverse(), [records.data, snapshot.id]);
  const update = (category: string, patch: Partial<Entry>) => setEntries(previous => {
    const current: Entry = previous[category] ?? { status: 'missing_activity', exchangeId: '', factor: '', version: '', source: '', hash: '', evidenceRole: 'demonstration_proxy' };
    return { ...previous, [category]: { ...current, ...patch } };
  });
  const create = useMutation({
    mutationFn: () => {
      if (!periodId || !facility.trim() || !scale || !workspace.data?.process_graph?.nodes.length || !sourceOutput) throw new Error('请先填写报告期、设施和期间产量。');
      const activities: OrganizationSupplierActivity[] = [];
      const categoryStatuses: OrganizationPeriodRequest['category_statuses'] = {};
      for (const [category, rule] of Object.entries(rules)) {
        const entry = entries[category];
        if (entry?.status !== 'calculated') {
          categoryStatuses[category] = entry?.status ?? 'missing_activity';
          continue;
        }
        const exchange = snapshot.scaled_technosphere_exchanges.find(item => item.exchange_id === entry.exchangeId);
        if (!exchange || !rule.eligible_consumer_exchange_ids?.includes(entry.exchangeId)) throw new Error('所选采购投入不属于该方法类别。');
        const amount = Number(exchange.amount) * scale;
        if (!Number.isFinite(amount) || amount <= 0 || !Number.isFinite(Number(entry.factor)) || Number(entry.factor) <= 0) throw new Error('供应商活动量或因子无效。');
        activities.push({ activity_id: `${category}:${entry.exchangeId}`, category, consumer_exchange_id: entry.exchangeId,
          quantity: amount, activity_unit: String(exchange.unit), factor_value: Number(entry.factor),
          factor_unit: `kg CO2-Eq/${String(exchange.unit)}`, factor_version: entry.version,
          factor_source: entry.source, factor_boundary: rule.factor_boundary ?? '', evidence_sha256: entry.hash,
          evidence_role: entry.evidenceRole,
          outside_model: true });
      }
      return api.createOrganizationPeriodInventory(applicationId, {
        solved_snapshot_id: snapshot.id, method_package_ref: `${method.package_id}@${method.version}`,
        reporting_period_id: periodId, facility: facility.trim(),
        controlled_process_ids: workspace.data.process_graph.nodes.map(node => node.id),
        period_product_output: Number(output), scope3_activities: activities, category_statuses: categoryStatuses,
      });
    },
    onSuccess: () => client.invalidateQueries({ queryKey: ['organization-period', applicationId] }),
  });
  if (!snapshot.native_background_climate) return <EmptyState description="请先从工艺与数据页计算含原生背景的产品气候结果。" />;
  return <div className="pcf-result">
    <h3>组织期间温室气体清单</h3>
    <p>以当前冻结模型为基准，按期间产量缩放受控过程。电力生命周期背景单列参考；范围 2 需要仅发电阶段依据。供应链活动独立填报，不重复使用产品总足迹。</p>
    <Alert type="warning" content="这是模型范围和已提供活动数据的示例清单；未填报类别保留缺项状态，不代表完整企业盘查。" />
    {periods.isLoading || workspace.isLoading || records.isLoading ? <LoadingState rows={4} /> : null}
    {periods.isError || workspace.isError || records.isError ? <ErrorState error={periods.error || workspace.error || records.error} /> : null}
    <div className="project-period-form">
      <label>报告期<Select aria-label="组织报告期" value={periodId} onChange={setPeriodId} options={(periods.data ?? []).map(item => ({ label: `${item.name} · ${item.start_date}—${item.end_date}`, value: item.id }))} /></label>
      <label>设施或组织名称<input aria-label="设施或组织名称" value={facility} onChange={event => setFacility(event.target.value)} /></label>
      <label>期间产品产量（{demand?.unit ?? 'kg'}）<input aria-label="期间产品产量" type="number" min="0" step="any" value={output} onChange={event => setOutput(event.target.value)} /></label>
      <p>模型计算基准：{number(sourceOutput)} {demand?.unit ?? ''}；受控过程：{workspace.data?.process_graph?.nodes.map(node => node.name).join('、') ?? '读取中'}</p>
    </div>
    <h4>范围 3 采购活动</h4>
    {Object.entries(rules).map(([category, rule]) => {
      const entry = entries[category];
      const status = entry?.status ?? 'missing_activity';
      const exchange = snapshot.scaled_technosphere_exchanges.find(item => item.exchange_id === entry?.exchangeId);
      return <div className="section-panel" key={category}>
        <strong>{rule.name ?? category}</strong>
        <Select aria-label={`${rule.name ?? category}状态`} value={status} onChange={value => update(category, { status: value as Entry['status'] })} options={[
          { label: '缺活动数据', value: 'missing_activity' }, { label: '本范围不适用', value: 'not_applicable' },
          { label: '本次边界排除', value: 'excluded_by_boundary' }, { label: '使用供应商因子计算', value: 'calculated' },
        ]} />
        {status === 'calculated' ? <div className="project-period-form">
          <label>采购投入<Select aria-label={`${category}采购投入`} value={entry?.exchangeId} onChange={value => update(category, { exchangeId: value })} options={(rule.eligible_consumer_exchange_ids ?? []).map(value => ({ label: value, value }))} /></label>
          <span>期间数量：{exchange && scale ? `${number(Number(exchange.amount) * scale)} ${String(exchange.unit)}` : '请先选择投入与期间产量'}</span>
          <label>供应商排放因子（kg CO₂e / 投入单位）<input aria-label={`${category}供应商因子`} type="number" min="0" step="any" value={entry?.factor ?? ''} onChange={event => update(category, { factor: event.target.value })} /></label>
          <label>因子版本<input aria-label={`${category}因子版本`} value={entry?.version ?? ''} onChange={event => update(category, { version: event.target.value })} /></label>
          <label>因子来源<input aria-label={`${category}因子来源`} value={entry?.source ?? ''} onChange={event => update(category, { source: event.target.value })} /></label>
          <label>来源文件 SHA-256<input aria-label={`${category}来源文件哈希`} value={entry?.hash ?? ''} onChange={event => update(category, { hash: event.target.value })} /></label>
          <label>来源用途<Select aria-label={`${category}来源用途`} value={entry?.evidenceRole ?? 'demonstration_proxy'} onChange={value => update(category, { evidenceRole: value as Entry['evidenceRole'] })} options={[{ label: '公开参考示例', value: 'demonstration_proxy' }, { label: '实际供应商数据', value: 'supplier_specific' }]} /></label>
        </div> : null}
      </div>;
    })}
    <Button type="primary" loading={create.isPending} onClick={() => create.mutate()}>计算并保存期间清单</Button>
    {create.isError ? <ErrorState error={create.error} /> : null}
    <h4>已保存结果</h4>
    {knownRecords.length ? knownRecords.map(record => <section className="section-panel" key={record.id}>
      <strong>{record.result.reporting_period.name} · {record.result.organizational_boundary.facility}</strong>
      <p><Button href={`/api/v1/applications/${applicationId}/organization-period-inventories/${record.id}/report.html`} target="_blank">打开 HTML 报告</Button></p>
      <p>期间产量 {number(record.result.activity_basis.period_output)} {record.result.activity_basis.output_unit}，缩放系数 {number(record.result.activity_basis.scale_factor)}</p>
      <Table rowKey="scope" pagination={false} data={[
        { scope: '范围 1', ...record.result.scopes.scope_1 },
        { scope: '范围 2', ...record.result.scopes.scope_2 },
        { scope: '范围 3（已提供类别）', ...record.result.scopes.scope_3 },
      ]} columns={[{ title: '范围', dataIndex: 'scope' }, { title: '排放量', render: (_, item) => `${number(item.value)} ${item.unit}` }, { title: '状态', render: (_, item) => statusText(item.status) }]} />
      {record.result.unclassified_background_reference ? <p>待分类电力生命周期背景参考量：{number(record.result.unclassified_background_reference.value)} {record.result.unclassified_background_reference.unit}；未计入范围 2 或组织合计。</p> : null}
      <ul>{record.result.scopes.scope_3.categories.map(category => <li key={category.category}>{category.name}：{statusText(category.status)}{category.value === null ? '' : `，${number(category.value)} ${category.unit}`}
        {category.activities.map(activity => <small key={activity.activity_id}> · {activity.factor_source}（{activity.factor_version}，SHA-256 {activity.evidence_sha256}）</small>)}</li>)}</ul>
      <p>合计：{number(record.result.combined_total)} {record.result.scopes.scope_1.unit}；未取得活动数据：{record.result.coverage.missing_activity_categories.map(key => record.result.scopes.scope_3.categories.find(item => item.category === key)?.name ?? key).join('、') || '无（按本次配置）'}；参考示例：{record.result.coverage.demonstration_proxy_activity_ids?.join('、') || '无'}</p>
      <small>方法 {record.result.method_package.reference} · 结果哈希 {record.content_sha256}</small>
    </section>) : <EmptyState description="当前快照还没有保存期间清单。" />}
  </div>;
}
