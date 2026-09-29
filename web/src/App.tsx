import { Route, Routes, useSearchParams } from 'react-router-dom';
import { HomePage } from './pages/HomePage';
import { ProjectCreateDialog, ProjectTemplatesPage } from './pages/ProjectTemplatesPage';
import { ProjectWorkspacePage } from './pages/ProjectWorkspacePage';
import { AppShell } from './layout/AppShell';
import { ApplicationsPage } from './pages/ApplicationsPage';
import { ComparisonResultsPage } from './pages/ComparisonResultsPage';
import { ScenariosPage } from './pages/ScenariosPage';
import { NotFoundState } from './components/ui/States';
import { CasePacksPage } from './pages/CasePacksPage';
import { AnalysisResultsPage } from './pages/AnalysisResultsPage';
import { ModelImportPage } from './pages/ModelImportPage';
import { ModelingPage } from './pages/ModelingPage';
import { ModelingReturnPage } from './pages/ModelingReturnPage';
import { ProjectHistoryPage } from './pages/ProjectHistoryPage';
import { OrganizationCalculationPage } from './pages/OrganizationCalculationPage';

export function App() {
  const [params, setParams] = useSearchParams();
  const closeCreate = () => setParams(previous => { const next = new URLSearchParams(previous); next.delete('create'); next.delete('template'); return next; }, { replace: true });
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/templates" element={<ProjectTemplatesPage />} />
        <Route path="/casepacks" element={<CasePacksPage />} />
        <Route path="/applications" element={<ApplicationsPage />} />
        <Route path="/model-import" element={<ModelImportPage />} />
        <Route path="/modeling" element={<ModelingPage />} />
        <Route path="/modeling/return" element={<ModelingReturnPage />} />
        <Route path="/applications/:applicationId/scenarios" element={<ScenariosPage />} />
        <Route path="/applications/:applicationId/workbench" element={<ProjectWorkspacePage />} />
        <Route path="/applications/:applicationId/history" element={<ProjectHistoryPage />} />
        <Route path="/applications/:applicationId/organization" element={<OrganizationCalculationPage />} />
        <Route path="/applications/:applicationId/results" element={<AnalysisResultsPage />} />
        <Route path="/comparison-runs/:runId" element={<ComparisonResultsPage />} />
        <Route path="*" element={<main className="app-page"><NotFoundState /></main>} />
      </Routes>
      {params.get('create') === 'project' ? <ProjectCreateDialog initialSelection={params.get('template') ?? ''} onClose={closeCreate} /> : null}
    </AppShell>
  );
}
