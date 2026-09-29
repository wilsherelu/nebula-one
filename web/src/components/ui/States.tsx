import { Alert, Button, Empty, Result, Skeleton } from '@arco-design/web-react';
import { ApiError } from '../../api/client';
import { useI18n } from '../../i18n';
import { DependencyGapNotice, readDependencyGap } from './DependencyGapNotice';

export function LoadingState({ rows = 3 }: { rows?: number }) {
  const { t } = useI18n();
  return <Skeleton loading text={{ rows }} animation aria-label={t('state.loadingAria')} />;
}

export function EmptyState({ description }: { description: string }) {
  return <Empty description={description} />;
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { t, errorText } = useI18n();
  // A known code is answered in the interface language; anything else keeps the server's own
  // sentence rather than an invented translation.
  const apiError = error instanceof ApiError ? error : undefined;
  const message = errorText(apiError?.code)
    ?? (error instanceof Error && error.message ? error.message : t('error.fallback'));
  const details = apiError?.details && Object.keys(apiError.details).length ? apiError.details : undefined;
  const gap = readDependencyGap(apiError?.details);
  // A structured gap already states the refusal in operator terms, so the stable code moves into
  // the technical disclosure instead of competing with it on the same screen.
  const code = apiError?.code ? <div className="error-state__code">{t('error.code', { code: apiError.code, status: apiError.status })}</div> : null;
  return (
    <Alert
      type="error"
      title={t('error.title')}
      content={<>
        {message}
        {gap ? <DependencyGapNotice gap={gap} /> : code}
        {gap || details ? <details className="error-state__details"><summary>{t('error.technical')}</summary>{gap ? code : null}{details ? <pre>{JSON.stringify(details, null, 2)}</pre> : null}</details> : null}
      </>}
      action={onRetry ? <Button size="small" onClick={onRetry}>{t('state.reload')}</Button> : undefined}
    />
  );
}

export function NotFoundState() {
  const { t } = useI18n();
  return <Result status="404" title={t('state.notFound')} subTitle={t('notFound.subtitle')} />;
}
