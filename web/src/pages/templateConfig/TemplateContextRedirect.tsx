import { Navigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Radio } from '@arco-design/web-react';
import { useState } from 'react';
import { seedProjectsApi, templateName, type SeedProjectTemplate } from '../../api/seedProjects';
import { useI18n } from '../../i18n';
import { ErrorState, LoadingState } from '../../components/ui/States';
import { resolveTemplateContext } from './resolveTemplate';

export const templateConfigPath = (templateId: string, tab: 'model' | 'methods' = 'methods') =>
  `/templates/${encodeURIComponent(templateId)}/config?tab=${tab}`;

/**
 * Carry an old template deep link into the config workspace.
 *
 * The link names a modelling source, not a template version, and several versions can share one
 * source; the reader then chooses instead of being sent to whichever version happens to be first.
 */
export function TemplateContextRedirect({ source, model, revision, tab }: {
  source: string | null; model: string | null; revision: string | null; tab: 'model' | 'methods';
}) {
  const { t, lang } = useI18n();
  const catalog = useQuery({ queryKey: ['seed-project-templates'], queryFn: seedProjectsApi.catalog });
  const [chosen, setChosen] = useState<string | null>(null);
  if (catalog.isLoading) return <LoadingState />;
  if (catalog.isError) return <ErrorState error={catalog.error} onRetry={() => catalog.refetch()} />;
  if (chosen) return <Navigate to={templateConfigPath(chosen, tab)} replace />;
  const resolution = resolveTemplateContext(catalog.data?.items, source, model, revision);
  if (resolution.status === 'resolved') return <Navigate to={templateConfigPath(resolution.item.id, tab)} replace />;
  if (resolution.status === 'ambiguous') {
    return <section className="section-panel template-context-choice">
      <h2>{t('tm.chooseVersion')}</h2>
      <p className="helper-text">{t('tm.chooseVersionHint')}</p>
      <Radio.Group aria-label={t('tm.chooseVersion')} className="template-options" onChange={value => setChosen(String(value))}>
        {resolution.matches.map((item: SeedProjectTemplate) => <Radio key={item.id} value={item.id}>
          <strong>{templateName(item, lang)}</strong>
          <small>{t('templates.version', { version: item.version })}</small>
        </Radio>)}
      </Radio.Group>
    </section>;
  }
  return <ErrorState error={Object.assign(new Error(t('tm.contextUnresolved')), { name: 'TemplateContextUnresolved' })} />;
}
