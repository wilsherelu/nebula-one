import { Button, Layout, Menu, Tooltip } from '@arco-design/web-react';
import { IconApps, IconHome, IconStorage, IconBranch, IconMenuFold, IconMenuUnfold } from '@arco-design/web-react/icon';
import { useLocation, useNavigate } from 'react-router-dom';
import { useState, type CSSProperties, type ReactNode } from 'react';
import { languageParam, useI18n } from '../i18n';
import { LanguageSwitch } from './LanguageSwitch';

const { Sider, Content } = Layout;

export function AppShell({ children }: { children: ReactNode }) {
  const location = useLocation();
  const navigate = useNavigate();
  const { lang, t } = useI18n();
  const [collapsed, setCollapsed] = useState(false);
  const active = location.pathname.startsWith('/modeling') ? 'modeling' : location.pathname === '/' ? 'home' : location.pathname.startsWith('/templates') || location.pathname.startsWith('/casepacks')
    ? 'templates'
    : 'applications';
  return (
    <Layout className={`app-shell${collapsed ? ' app-shell--collapsed' : ''}`}
      style={{ '--no-sidebar-width': collapsed ? '64px' : '200px' } as CSSProperties}>
      <Sider className="app-sidebar" width={200} collapsed={collapsed} collapsedWidth={64}>
        <div className="brand-mark" aria-label="Nebula One">
          <span className="brand-mark__orb" aria-hidden="true" />
          <span><strong>Nebula One</strong><small>{t('brand.tagline')}</small></span>
        </div>
        <LanguageSwitch compact={collapsed} />
        <Menu id="primary-navigation" collapse={collapsed} selectedKeys={[active]} onClickMenuItem={(key) => {
          if (key === 'home') navigate('/');
          if (key === 'templates') navigate('/templates');
          if (key === 'applications') navigate('/applications');
          // The modelling screen is a different app on a different port, so the language travels
          // as an explicit parameter instead of relying on storage both apps cannot share.
          if (key === 'modeling') {
            if (window.__NEBULA_ONE_DESKTOP__?.openEditorHome) void window.__NEBULA_ONE_DESKTOP__.openEditorHome(lang);
            else window.open(`/modeling?${languageParam(lang)}`, '_blank', 'noopener,noreferrer');
          }
        }}>
          <Menu.Item key="home" aria-label={t('nav.home')} aria-current={active === 'home' ? 'page' : undefined} renderItemInTooltip={() => t('nav.home')}><IconHome /><span>{t('nav.home')}</span></Menu.Item>
          <Menu.Item key="applications" aria-label={t('nav.projects')} aria-current={active === 'applications' ? 'page' : undefined} renderItemInTooltip={() => t('nav.projects')}><IconApps /><span className="nav-full">{t('nav.projects')}</span><span className="nav-short">{t('nav.projectsShort')}</span></Menu.Item>
          <Menu.Item key="templates" aria-label={t('nav.templates')} aria-current={active === 'templates' ? 'page' : undefined} renderItemInTooltip={() => t('nav.templates')}><IconStorage /><span className="nav-full">{t('nav.templates')}</span><span className="nav-short">{t('nav.templatesShort')}</span></Menu.Item>
          <Menu.Item key="modeling" aria-label={t('nav.modeling')} aria-current={active === 'modeling' ? 'page' : undefined} renderItemInTooltip={() => t('nav.modeling')}><IconBranch /><span className="nav-full">{t('nav.modeling')}</span><span className="nav-short">{t('nav.modelingShort')}</span></Menu.Item>
        </Menu>
      </Sider>
      <Tooltip content={t(collapsed ? 'nav.expand' : 'nav.collapse')}>
        <Button className="sidebar-toggle" aria-label={t(collapsed ? 'nav.expand' : 'nav.collapse')}
            aria-expanded={!collapsed} aria-controls="primary-navigation"
            icon={collapsed ? <IconMenuUnfold /> : <IconMenuFold />} onClick={() => setCollapsed(value => !value)} />
      </Tooltip>
      <Content className="app-content">{children}</Content>
    </Layout>
  );
}
