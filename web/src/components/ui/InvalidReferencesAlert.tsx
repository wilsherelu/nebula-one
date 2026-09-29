import { Alert, Button } from '@arco-design/web-react';
import { useParamWriter, type InvalidReference } from '../../hooks/useUrlSelection';

/** Recoverable error for a deep link that references a method, period or snapshot this object does not have. */
export function InvalidReferencesAlert({ references, note }: { references: InvalidReference[]; note?: string }) {
  const write = useParamWriter();
  return <Alert
    type="error"
    title="链接指定的引用无法使用"
    content={`${references.map((item) => `${item.label}「${item.requested}」不属于当前对象或已不存在。`).join(' ')}${note ? ` ${note}` : ''}`}
    action={<Button size="mini" onClick={() => write((next) => references.forEach((item) => next.delete(item.key)), true)}>清除并重新选择</Button>}
  />;
}
