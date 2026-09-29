import { Tag } from '@arco-design/web-react';
import { useI18n, type Lang } from '../../i18n';

const semantics: Record<string, { color: string; label: readonly [string, string] }> = {
  succeeded: { color: 'green', label: ['已完成', 'Succeeded'] },
  passed: { color: 'green', label: ['审计通过', 'Audit passed'] },
  passed_with_warnings: { color: 'orange', label: ['通过并有警告', 'Passed with warnings'] },
  pass_with_warnings: { color: 'orange', label: ['通过并有警告', 'Passed with warnings'] },
  trial_passed: { color: 'orange', label: ['试算通过', 'Trial passed'] },
  frozen: { color: 'blue', label: ['已冻结', 'Frozen'] },
  published: { color: 'blue', label: ['已发布', 'Published'] },
  running: { color: 'arcoblue', label: ['运行中', 'Running'] },
  failed: { color: 'red', label: ['失败', 'Failed'] },
  draft: { color: 'gray', label: ['草稿', 'Draft'] },
  active: { color: 'green', label: ['可用', 'Active'] },
  compatible: { color: 'green', label: ['可比较', 'Comparable'] },
  incompatible: { color: 'red', label: ['不可比较', 'Not comparable'] },
  quantified_partial: { color: 'orange', label: ['部分量化', 'Partly quantified'] },
  reference_only: { color: 'blue', label: ['参考值', 'Reference only'] },
  not_calculated: { color: 'gray', label: ['未计算', 'Not calculated'] },
  available: { color: 'green', label: ['热点可用', 'Hotspot available'] },
  unavailable: { color: 'gray', label: ['热点不可用', 'Hotspot unavailable'] },
};

/** An unknown status is shown as-is: inventing a label would present an unverified meaning. */
export function statusLabel(status: string, lang: Lang): string {
  const pair = semantics[status]?.label;
  return pair ? (lang === 'zh' ? pair[0] : pair[1]) : status;
}

export function StatusBadge({ status }: { status: string }) {
  const { lang } = useI18n();
  const item = semantics[status] ?? { color: 'gray', label: [status, status] as const };
  return <Tag color={item.color}>{statusLabel(status, lang)}</Tag>;
}
