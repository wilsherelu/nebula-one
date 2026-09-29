import { Button, Message, Tooltip } from '@arco-design/web-react';
import { IconCopy } from '@arco-design/web-react/icon';
import { shortId } from '../../api/client';

export function CopyableValue({ value, compact = true }: { value: string | null | undefined; compact?: boolean }) {
  const normalized = value ?? '';
  const copy = async () => {
    if (!normalized) return;
    await navigator.clipboard.writeText(normalized);
    Message.success('已复制');
  };
  return (
    <span className="copyable-value">
      <span className="mono-value">{compact ? shortId(value) : value || '未记录'}</span>
      {normalized ? (
        <Tooltip content="复制完整值">
          <Button type="text" size="mini" icon={<IconCopy />} aria-label="复制完整值" onClick={copy} />
        </Tooltip>
      ) : null}
    </span>
  );
}
