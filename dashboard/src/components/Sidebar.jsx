import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  LayoutDashboard,
  BarChart3,
  MessageSquare,
  Newspaper,
  Globe2,
  Database,
  ScanSearch,
  CalendarDays,
  Radar,
  Users,
  ShieldCheck,
  Link2,
  LogOut,
  ChevronsLeft,
  ChevronsRight,
  ChevronDown,
  X,
} from 'lucide-react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/useAuth.js';
import LanguageSwitcher from './LanguageSwitcher.jsx';
import { transferableIntelligenceScope } from '../lib/intelligenceScope.js';

// The two experiences answer different questions and are kept visibly apart:
// "Insights" is what people are saying (sentiment, opinions); "Monitoring" is
// the two ongoing watch programs (your own brand's opinion monitor and rival
// companies' competitor analysis). Mixing them in one flat list is what made
// the old navigation ambiguous. Section/item ids are stable (never
// translated) - only `labelKey` is resolved through `t()` at render time, in
// buildNavSections() below, so localStorage's collapsed-section state and
// sectionDomId() stay keyed on an id that doesn't change with locale.
function buildNavSections(t) {
  return [
    {
      id: 'insights',
      label: t('sections.insights'),
      items: [
        { to: '/dashboard', label: t('items.dashboard'), icon: LayoutDashboard },
        { to: '/reports', label: t('items.reports'), icon: BarChart3 },
        { to: '/articles', label: t('items.articles'), icon: Newspaper },
        { to: '/sources', label: t('items.sources'), icon: Globe2 },
        { to: '/intelligence', label: t('items.copilot'), icon: MessageSquare },
      ],
    },
    {
      id: 'monitoring',
      label: t('sections.monitoring'),
      items: [
        { to: '/projects', label: t('items.opinionMonitor'), icon: CalendarDays },
        { to: '/competitors', label: t('items.competitorAnalysis'), icon: Radar, permission: 'competitors.view' },
      ],
    },
    {
      id: 'analysis',
      label: t('sections.analysis'),
      items: [
        { to: '/pipeline-runs', label: t('items.analysisRuns'), icon: Database },
        { to: '/analysis', label: t('items.performanceLogs'), icon: ScanSearch },
      ],
    },
    {
      id: 'admin',
      label: t('sections.admin'),
      items: [
        { to: '/admin/users', label: t('items.users'), icon: Users, permission: 'users.view' },
        { to: '/admin/roles', label: t('items.roles'), icon: ShieldCheck, permission: 'roles.view' },
        { to: '/admin/project-linkage', label: t('items.projectAccess'), icon: Link2, permission: 'projects.link_users' },
      ],
    },
  ];
}

const SECTION_STATE_KEY = 'strata.sidebarSections';

function loadSectionState() {
  if (typeof window === 'undefined') return {};
  try {
    return JSON.parse(window.localStorage.getItem(SECTION_STATE_KEY)) || {};
  } catch {
    return {};
  }
}

function sectionDomId(id) {
  return `sidebar-section-${id}`;
}

export default function Sidebar({
  collapsed = false,
  onToggleCollapse = () => {},
  mobileOpen = false,
  onCloseMobile = () => {},
}) {
  const { t } = useTranslation(['nav', 'common']);
  const { user, hasPermission, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [openSections, setOpenSections] = useState(loadSectionState);
  const navSections = buildNavSections(t);

  // On mobile the drawer always renders fully expanded; only the desktop rail collapses.
  const showCollapsed = collapsed && !mobileOpen;

  // Sections default to open unless the user has explicitly collapsed them before.
  const isSectionOpen = (id) => openSections[id] !== false;

  const toggleSection = (id) => {
    setOpenSections((prev) => {
      const next = { ...prev, [id]: !(prev[id] !== false) };
      if (typeof window !== 'undefined') {
        window.localStorage.setItem(SECTION_STATE_KEY, JSON.stringify(next));
      }
      return next;
    });
  };

  const handleLogout = async () => {
    await logout();
    navigate('/login', { replace: true });
  };

  const initials = user?.username
    ? user.username.trim().slice(0, 2).toUpperCase()
    : '?';

  const navStyle = ({ isActive }) => ({
    background: isActive ? 'white' : 'rgba(255,255,255,0.45)',
    borderColor: isActive ? 'transparent' : 'rgba(0,0,0,0.08)',
    boxShadow: isActive ? '0 6px 18px rgba(0,0,0,0.08)' : 'none',
    textDecoration: 'none',
    width: '100%',
    justifyContent: showCollapsed ? 'center' : 'flex-start',
  });

  return (
    <div
      className={`sidebar${showCollapsed ? ' sidebar-collapsed' : ''}${mobileOpen ? ' sidebar-mobile-open' : ''}`}
    >
      <div className="sidebar-header">
        <div className="sidebar-brand">
          {showCollapsed ? (
            <span className="sidebar-brand-mark">S</span>
          ) : (
            <>
              <h1 className="title">{t('common:app.name')}</h1>
              <p className="subtitle">{t('brand.subtitle')}</p>
            </>
          )}
        </div>
        <button
          type="button"
          className="sidebar-toggle-btn"
          onClick={mobileOpen ? onCloseMobile : onToggleCollapse}
          title={mobileOpen ? t('toggle.closeNavigation') : (collapsed ? t('toggle.expandNavigation') : t('toggle.collapseNavigation'))}
          aria-label={mobileOpen ? t('toggle.closeNavigation') : (collapsed ? t('toggle.expandNavigation') : t('toggle.collapseNavigation'))}
        >
          {mobileOpen ? <X size={18} /> : (
            collapsed
              ? <ChevronsRight size={18} className="rtl-mirror" />
              : <ChevronsLeft size={18} className="rtl-mirror" />
          )}
        </button>
      </div>

      <nav className="sidebar-nav">
        {navSections.map((section) => {
          // A section with nothing the user may see should not leave a stray heading.
          const visible = section.items.filter(
            (item) => !item.permission || hasPermission(item.permission),
          );
          if (!visible.length) return null;

          const links = visible.map(({ to, label, icon: Icon }) => {
            const isScopePage = ['/dashboard', '/reports'].includes(location.pathname);
            const carriesScope = ['/dashboard', '/reports'].includes(to);
            const destination = isScopePage && carriesScope
              ? { pathname: to, search: transferableIntelligenceScope(location.search) }
              : to;
            return (
            <NavLink
              key={to}
              to={destination}
              className="btn-secondary sidebar-nav-link"
              style={navStyle}
              title={showCollapsed ? label : undefined}
              onClick={onCloseMobile}
            >
              <Icon size={18} /> {!showCollapsed && <span>{label}</span>}
            </NavLink>
            );
          });

          // Collapsed desktop rail stays a flat icon list; no headers to toggle.
          if (showCollapsed) {
            return <React.Fragment key={section.id}>{links}</React.Fragment>;
          }

          const open = isSectionOpen(section.id);
          const domId = sectionDomId(section.id);
          return (
            <div className="sidebar-nav-group" key={section.id}>
              <button
                type="button"
                className="sidebar-nav-section"
                onClick={() => toggleSection(section.id)}
                aria-expanded={open}
                aria-controls={domId}
              >
                <span>{section.label}</span>
                <ChevronDown size={14} className={`sidebar-nav-chevron${open ? '' : ' sidebar-nav-chevron-closed'}`} />
              </button>
              {open && (
                <div className="sidebar-nav-items" id={domId}>
                  {links}
                </div>
              )}
            </div>
          );
        })}
      </nav>

      {!showCollapsed && <LanguageSwitcher className="sidebar-language-switcher" />}

      {user && (
        <div className="sidebar-profile">
          <div
            className="sidebar-profile-row"
            title={showCollapsed ? `${user.username} (${user.role})` : undefined}
          >
            <div className="sidebar-avatar">{initials}</div>
            {!showCollapsed && (
              <div className="sidebar-profile-meta">
                <span className="sidebar-profile-name" dir="auto">{user.username}</span>
                <span className={`panel-chip role-${user.role}`} dir="auto">{user.role}</span>
              </div>
            )}
          </div>
          <button
            type="button"
            className="btn-secondary sidebar-logout"
            onClick={handleLogout}
            title={showCollapsed ? t('profile.logout') : undefined}
          >
            <LogOut size={16} /> {!showCollapsed && t('profile.logout')}
          </button>
        </div>
      )}
    </div>
  );
}
