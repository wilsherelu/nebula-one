import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import type { SolvedSystemSnapshot } from '../api/types';

export function referenceUnit(value: unknown): string {
  if (typeof value === 'string') return value;
  if (value && typeof value === 'object' && 'amount' in value && 'unit' in value) return `${String(value.amount)} ${String(value.unit)}`;
  return '未提供';
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
  return <div className="analysis-context">
    <span>模型版本 <strong>{context.data ? `${context.data.model.name} · R${context.data.revision.revision_number}` : context.isLoading ? '读取中' : '版本信息暂不可用'}</strong></span>
    <span>参考单位 <strong>{referenceUnit(snapshot.functional_unit)}</strong></span>
    <span>数据版本 <strong>{snapshot.database_release}</strong></span>
    <small>参考单位不等于本次运行规模；各应用的核算边界与报告期分别列示。</small>
  </div>;
}
