import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import '@arco-design/web-react/dist/css/arco.css';
import './styles/tokens.css';
import './styles/base.css';
import './styles/components.css';
import './styles/layout.css';
import './styles/domain.css';
import './styles/pages.css';
import './styles/workbench.css';
import './styles/catalog.css';
import { App } from './App';
import { I18nProvider } from './i18n';
import { createAppQueryClient } from './api/queryClient';

const queryClient = createAppQueryClient();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <I18nProvider><BrowserRouter><App /></BrowserRouter></I18nProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
