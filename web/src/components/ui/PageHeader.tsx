import type { ReactNode } from 'react';

interface Props {
  title: string;
  description: string;
  action?: ReactNode;
}

export function PageHeader({ title, description, action }: Props) {
  return (
    <header className="page-header">
      <div className="page-header__copy">
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action ? <div className="page-header__action">{action}</div> : null}
    </header>
  );
}
