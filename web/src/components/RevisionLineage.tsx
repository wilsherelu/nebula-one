import { Timeline } from '@arco-design/web-react';
import type { SystemRevision } from '../api/types';
import { formatDate, shortId } from '../api/client';
import { StatusBadge } from './ui/StatusBadge';

export function RevisionLineage({ revisions }: { revisions: SystemRevision[] }) {
  const ordered = [...revisions].sort((a, b) => a.revision_number - b.revision_number);
  return (
    <div className="revision-lineage">
      <Timeline mode="alternate">
        {ordered.map((revision) => (
          <Timeline.Item key={revision.id} label={`R${revision.revision_number}`}>
            <div className="revision-lineage__item">
              <div><strong>{revision.label || `Revision ${revision.revision_number}`}</strong> <StatusBadge status={revision.status} /></div>
              <div className="helper-text">{revision.parent_revision_id ? `父版本 ${shortId(revision.parent_revision_id)}` : '基线版本'} · {formatDate(revision.created_at)}</div>
            </div>
          </Timeline.Item>
        ))}
      </Timeline>
    </div>
  );
}
