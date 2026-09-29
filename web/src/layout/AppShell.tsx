import { Layout, Menu } from '@arco-design/web-react';
import { IconApps, IconHome, IconStorage, IconBranch } from '@arco-design/web-react/icon';
import { useLocation, useNavigate } from 'react-router-dom';
import type { ReactNode } from 'react';
import { languageParam, useI18n } from '../i18n';
import { LanguageSwitch } from './LanguageSwitch';

const { Sider, Content } = Layout;

export function AppShell({ children }: { children: ReactNode }) {
  const location = useLocation();
  const navigate = useNavigate();
  const { lang, t } = useI18n();
  const active = location.pathname.startsWith('/modeling') ? 'modeling' : location.pathname === '/' ? 'home' : location.pathname.startsWith('/templates') || location.pathname.startsWith('/casepacks')
    ? 'templates'
    : 'applications';
  return (
    <Layout className="app-shell">
      <Sider className="app-sidebar" width={200}>
        <div className="brand-mark" aria-label="Nebula One">
          <span className="brand-mark__orb" aria-hidden="true" />
          <span><strong>Nebula One</strong><small>{t('brand.tagline')}</small></span>
        </div>
        <Menu selectedKeys={[active]} onClickMenuItem={(key) => {
          if (key === 'home') navigate('/');
          if (key === 'templates') navigate('/templates');
          if (key === 'applications') navigate('/applications');
          // The modelling screen is a different app on a different port, so the language travels
          // as an explicit parameter instead of relying on storage both apps cannot share.
          if (key === 'modeling') window.open(`/modeling?${languageParam(lang)}`, '_blank', 'noopener,noreferrer');
        }}>
          <Menu.Item key="home"><IconHome /><span>{t('nav.home')}</span></Menu.Item>
          <Menu.Item key="applications"><IconApps /><span className="nav-full">{t('nav.projects')}</span><span className="nav-short">{t('nav.projectsShort')}</span></Menu.Item>
          <Menu.Item key="templates"><IconStorage /><span className="nav-full">{t('nav.templates')}</span><span className="nav-short">{t('nav.templatesShort')}</span></Menu.Item>
          <Menu.Item key="modeling"><IconBranch /><span className="nav-full">{t('nav.modeling')}</span><span className="nav-short">{t('nav.modelingShort')}</span></Menu.Item>
        </Menu>
        <LanguageSwitch />
      </Sider>
      <Content className="app-content">{children}</Content>
    </Layout>
  );
}
