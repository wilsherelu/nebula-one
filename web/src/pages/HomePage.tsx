import { IconArrowRight, IconPlus, IconFolder, IconApps } from '@arco-design/web-react/icon';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import { languageParam, useI18n } from '../i18n';
import { EmptyState, ErrorState, LoadingState } from '../components/ui/States';

export function HomePage() {
  const { t, lang, formatDate } = useI18n();
  const projects = useQuery({ queryKey: ['applications', lang], queryFn: () => api.applications(lang) });
  const recent = [...(projects.data ?? [])].sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at)).slice(0, 5);
  const modelingHref = `/modeling?${languageParam(lang)}`;
  return <main className="app-page home-page">
    <section className="section-panel home-intro">
      <h1>{t('home.title')}</h1>
      <p>{t('home.subtitle')}</p>
      <div className="home-entry-grid">
        <Link className="home-entry home-entry--primary" to="/templates"><IconPlus className="home-entry__icon" /><span><strong>{t('home.newProject')}</strong><small>{t('home.newProjectHint')}</small></span><IconArrowRight /></Link>
        <Link className="home-entry" to="/applications"><IconFolder className="home-entry__icon" /><span><strong>{t('home.myProjects')}</strong><small>{t('home.myProjectsHint')}</small></span><IconArrowRight /></Link>
        <Link className="home-entry" to={modelingHref} target="_blank" rel="noopener noreferrer"><IconApps className="home-entry__icon" /><span><strong>{t('home.professional')}</strong><small>{t('home.professionalHint')}</small></span><IconArrowRight /></Link>
      </div>
    </section>
    <section className="section-panel">
      <div className="section-heading"><h2>{t('home.recent')}</h2><Link to="/applications">{t('home.viewAll')}</Link></div>{projects.isLoading ? <LoadingState /> : projects.isError ? <ErrorState error={projects.error} onRetry={() => projects.refetch()} /> : !recent.length ? <EmptyState description={t('home.emptyRecent')} /> : recent.map(project => <Link className="home-project-row home-recent-row" key={project.id} to={`/applications/${project.id}/workbench`}><IconFolder /><strong>{project.name}</strong><span>{formatDate(project.updated_at)}</span><IconArrowRight /></Link>)}
    </section>
    <p className="helper-text">{t('home.customProcess')}<Link to={modelingHref} target="_blank" rel="noopener noreferrer">{t('nav.modeling')}</Link>{t('home.or')}<Link to="/model-import">{t('home.importModel')}</Link></p>
  </main>;
}
