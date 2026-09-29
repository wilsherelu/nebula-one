import type { ReactNode } from 'react';

/**
 * A refusal that is caused by missing data carries `details.dependency-gap.v1`, whose
 * values the backend computed from the inputs it actually held. Nothing here invents a
 * value for an absent field: an unknown field reads as 未知, and an empty list as 无.
 */
export const DEPENDENCY_GAP_SCHEMA_VERSION = 'nebula_one.dependency-gap.v1';

export interface DependencyGap {
  code: string;
  what_missing: Record<string, unknown>;
  affects: { step: string; downstream_steps?: unknown; scopes_affected?: unknown; results_produced?: unknown };
  how_to_resolve: { action: string; owner: string; precondition: string }[];
  evidence: Record<string, unknown>;
}

export function readDependencyGap(details: Record<string, unknown> | undefined): DependencyGap | undefined {
  const gap = details?.dependency_gap;
  if (!gap || typeof gap !== 'object') return undefined;
  const record = gap as Record<string, unknown>;
  if (record.schema_version !== DEPENDENCY_GAP_SCHEMA_VERSION) return undefined;
  if (typeof record.code !== 'string') return undefined;
  if (!record.what_missing || typeof record.what_missing !== 'object') return undefined;
  if (!record.affects || typeof record.affects !== 'object') return undefined;
  if (!Array.isArray(record.how_to_resolve)) return undefined;
  return {
    code: record.code,
    what_missing: record.what_missing as Record<string, unknown>,
    affects: record.affects as DependencyGap['affects'],
    how_to_resolve: record.how_to_resolve as DependencyGap['how_to_resolve'],
    evidence: (record.evidence ?? {}) as Record<string, unknown>,
  };
}

function valueText(value: unknown): string {
  if (value === null || value === undefined || value === '') return '未知';
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) return value.length ? value.map(valueText).join('、') : '无';
  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>);
    return entries.length ? entries.map(([key, item]) => `${key}=${valueText(item)}`).join('，') : '无';
  }
  return String(value);
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="dependency-gap__row">
      <strong>{label}</strong>
      <div>{children}</div>
    </div>
  );
}

export function DependencyGapNotice({ gap }: { gap: DependencyGap }) {
  const missing = gap.what_missing;
  const observed = missing.observed_resolution ?? missing.observed_identity;
  const affected: string[] = [
    `计算步骤 ${gap.affects.step}`,
    Array.isArray(gap.affects.downstream_steps) && gap.affects.downstream_steps.length
      ? `连带受阻 ${gap.affects.downstream_steps.map(valueText).join('、')}`
      : '无已确认的连带步骤',
    Array.isArray(gap.affects.scopes_affected) && gap.affects.scopes_affected.length
      ? `影响范围 ${gap.affects.scopes_affected.map(valueText).join('、')}`
      : '未指明范围',
  ];
  return (
    <div className="dependency-gap" role="note" aria-label="缺数据说明">
      <Row label="缺什么">
        <ul>
          <li>类型：{valueText(missing.kind)}</li>
          {missing.exchange_id ? <li>端口：{valueText(missing.exchange_id)}</li> : null}
          {observed !== undefined ? <li>当前观测：{valueText(observed)}</li> : null}
          {missing.required_identity ? <li>需要：{valueText(missing.required_identity)}</li> : null}
          {missing.identity && observed !== undefined ? <li>该端口流身份：{valueText(missing.identity)}</li> : null}
          {missing.unbound_refs ? <li>未绑定的方法包：{valueText(missing.unbound_refs)}</li> : null}
          {missing.unresolved_ids ? <li>解析不到的引用：{valueText(missing.unresolved_ids)}</li> : null}
          {missing.exchange_id_selectors ? <li>方法包指定的排放端口：{valueText(missing.exchange_id_selectors)}</li> : null}
        </ul>
      </Row>
      <Row label="影响哪部分">
        <span>{affected.join('；')}。</span>
        {gap.affects.results_produced === false ? <span>本次没有产出任何结果，缺项不会按零处理。</span> : null}
      </Row>
      <Row label="如何补齐">
        <ol>
          {gap.how_to_resolve.map((item) => (
            <li key={item.action}>
              {item.action}（负责：{item.owner}；前提：{item.precondition}）
            </li>
          ))}
        </ol>
      </Row>
    </div>
  );
}
