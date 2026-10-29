import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import type { SolvedSystemSnapshot } from '../api/types';

export function referenceUnit(value: unknown): string {
  if (typeof value === 'string') return value;
  if (value && typeof value === 'object' && 'amount' in value && 'unit' in value) return `${String(value.amount)} ${String(value.unit)}`;
  return '未提供';
}

interface UserMethodRule {
  boundary_status?: string;
  scope?: string | null;
}
interface UserMethodSnapshot {
  method_id?: string;
  name?: string;
  purpose?: string;
  version?: number;
  content_sha256?: string | null;
  model_revision_id?: string;
  execution_plan_sha256?: string | null;
  compiler_version?: string | null;
  rules?: UserMethodRule[];
}

export function userCalculationMethod(snapshot: SolvedSystemSnapshot): UserMethodSnapshot | null {
  const raw = snapshot.provider_receipt?.user_calculation_method;
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  return raw as UserMethodSnapshot;
}

function scopeCounts(rules: UserMethodRule[] | undefined): Record<string, number> {
  const counts: Record<string, number> = { scope_1: 0, scope_2: 0, scope_3: 0 };
  for (const rule of rules ?? []) {
    if (rule.boundary_status === 'selected' && rule.scope && rule.scope in counts) counts[rule.scope] += 1;
  }
  return counts;
}

export function SnapshotContext({ snapshot }: { snapshot: SolvedSystemSnapshot }) {
  const context = useQuery({
    queryKey: ['snapshot-context', snapshot.application_id, snapshot.system_revision_id],
    queryFn: async () => {
      const models = await api.models(snapshot.application_id);
      const candidates = await Promise.all(models.map(async (model) => ({ model, revisions: await api.revisions(model.id) })));
      return candidates.flatMap(({ model, revisions }) => revisions.filter((revision) => revision.id === snapshot.system_revision_id).map((revision) => ({ model, revision })))[0] ?? null;
    },
    retry: false,
  });
  const method = userCalculationMethod(snapshot);
  const counts = scopeCounts(method?.rules);
  return <div className="analysis-context">
    <span>模型版本 <strong>{context.data ? `${context.data.model.name} · R${context.data.revision.revision_number}` : context.isLoading ? '读取中' : '版本信息暂不可用'}</strong></span>
    <span>参考单位 <strong>{referenceUnit(snapshot.functional_unit)}</strong></span>
    <span>数据版本 <strong>{snapshot.database_release}</strong></span>
    {method ? <span className="analysis-context__method">按用户方法计算 <strong>{`${method.name ?? '方法'} · v${method.version ?? '?'}`}</strong></span> : null}
    <small>参考单位不等于本次运行规模；各应用的核算边界与报告期分别列示。</small>
    {method ? <div className="analysis-context__grouping">
      <span>Scope 归组：Scope 1 {counts.scope_1} · Scope 2 {counts.scope_2} · Scope 3 {counts.scope_3}（用户声明的归组数量，实际可用范围取决于方法包与数据覆盖；未覆盖项不会显示为零）</span>
      <details className="frozen-input-identity"><summary>方法版本标识</summary>
        <pre className="audit-json">{JSON.stringify({ method_id: method.method_id, version: method.version, model_revision_id: method.model_revision_id, content_sha256: method.content_sha256, execution_plan_sha256: method.execution_plan_sha256, compiler_version: method.compiler_version }, null, 2)}</pre>
      </details>
    </div> : null}
  </div>;
}
