import { Button, Radio } from '@arco-design/web-react';
import { IconExpand } from '@arco-design/web-react/icon';
import { useEffect, useState } from 'react';
import { ErrorState, LoadingState } from './ui/States';
import { useI18n } from '../i18n';

interface SankeyViewerProps {
  src: string;
  alt: string;
  helperText?: string;
  viewportLabel?: string;
  errorText?: string;
}

export function SankeyViewer({
  src,
  alt,
  helperText,
  viewportLabel,
  errorText,
}: SankeyViewerProps) {
  const { t } = useI18n();
  const [attempt, setAttempt] = useState(0);
  const [zoom, setZoom] = useState('fit');
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');

  useEffect(() => {
    setState('loading');
    setAttempt(0);
  }, [src]);

  const retry = () => {
    setState('loading');
    setAttempt((value) => value + 1);
  };

  const imageSrc = attempt ? `${src}${src.includes('?') ? '&' : '?'}retry=${attempt}` : src;

  return (
    <div className="sankey-viewer" role="region" aria-label={alt}>
      <div className="sankey-viewer__toolbar">
        <span>{helperText ?? t('mfa.chartHelper')}</span>
        <div className="inline-actions">
        <Radio.Group type="button" size="small" value={zoom} onChange={setZoom} aria-label={t('mfa.chartZoom')}>
          <Radio value="fit">{t('mfa.chartFit')}</Radio><Radio value="detail">{t('mfa.chartDetail')}</Radio>
        </Radio.Group>
        <Button
          type="text"
          size="small"
          icon={<IconExpand />}
          href={src}
          target="_blank"
          rel="noreferrer"
        >
          {t('cbam.openChart')}
        </Button>
        </div>
      </div>
      <div className="sankey-viewer__viewport" tabIndex={0} aria-label={viewportLabel ?? t('mfa.chartViewport')}>
        {state === 'loading' ? <div className="sankey-viewer__state"><LoadingState rows={6} /></div> : null}
        {state === 'error' ? (
          <div className="sankey-viewer__state">
            <ErrorState error={new Error(errorText ?? t('mfa.chartLoadError'))} onRetry={retry} />
          </div>
        ) : null}
        <img
          key={imageSrc}
          className={`${state === 'ready' ? '' : 'is-pending'} ${zoom === 'detail' ? 'is-enlarged' : ''}`}
          src={imageSrc}
          alt={alt}
          onLoad={() => setState('ready')}
          onError={() => setState('error')}
        />
      </div>
    </div>
  );
}
