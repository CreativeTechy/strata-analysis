import React, { useState } from 'react';
import {
  LayoutDashboard,
  BarChart3,
  GitMerge,
  MessageSquare,
  Rss,
  Newspaper,
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
import { NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/useAuth.js';

// The two experiences answer different questions and are kept visibly apart:
// "Insights" is what people are saying (sentiment, opinions); "Monitoring" is
// the two ongoing watch programs (your own brand's opinion monitor and rival
// companies' competitor analysis). Mixing them in one flat list is what made
// the old navigation ambiguous.
const NAV_SECTIONS = [
  {
    label: 'Insights',
    items: [
      { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
      { to: '/reports', label: 'Reports', icon: BarChart3 },
      { to: '/articles', label: 'Articles', icon: Newspaper },
      { to: '/intelligence', label: 'Copilot', icon: MessageSquare },
    ],
  },
  {
    label: 'Monitoring',
    items: [
      { to: '/projects', label: 'Opinion Monitor', icon: CalendarDays },
      { to: '/competitors', label: 'Competitor Analysis', icon: Radar, permission: 'competitors.view' },
    ],
  },
  {
    label: 'Setup',
    items: [
      { to: '/sources', label: 'Sources', icon: Rss },
      { to: '/workflow', label: 'Manual Run', icon: GitMerge },
      { to: '/pipeline-runs', label: 'Pipeline Runs', icon: Database },
      { to: '/analysis', label: 'Performance Logs', icon: ScanSearch },
    ],
  },
];

const ADMIN_NAV_ITEMS = [
  { to: '/admin/users', label: 'Users', icon: Users, permission: 'users.view' },
  { to: '/admin/roles', label: 'Roles', icon: ShieldCheck, permission: 'roles.view' },
  { to: '/admin/project-linkage', label: 'Project Access', icon: Link2, permission: 'projects.link_users' },
];

// Rendered as one more collapsible group alongside NAV_SECTIONS so admin gets
// the same expand/collapse and permission-filtering treatment as everything else.
const ALL_NAV_SECTIONS = [...NAV_SECTIONS, { label: 'Admin', items: ADMIN_NAV_ITEMS }];

const SECTION_STATE_KEY = 'strata.sidebarSections';

function loadSectionState() {
  if (typeof window === 'undefined') return {};
  try {
    return JSON.parse(window.localStorage.getItem(SECTION_STATE_KEY)) || {};
  } catch {
    return {};
  }
}

function sectionDomId(label) {
  return `sidebar-section-${label.toLowerCase().replace(/\s+/g, '-')}`;
}

export default function Sidebar({
  collapsed = false,
  onToggleCollapse = () => {},
  mobileOpen = false,
  onCloseMobile = () => {},
}) {
  const { user, hasPermission, logout } = useAuth();
  const navigate = useNavigate();
  const [openSections, setOpenSections] = useState(loadSectionState);

  // On mobile the drawer always renders fully expanded; only the desktop rail collapses.
  const showCollapsed = collapsed && !mobileOpen;

  // Sections default to open unless the user has explicitly collapsed them before.
  const isSectionOpen = (label) => openSections[label] !== false;

  const toggleSection = (label) => {
    setOpenSections((prev) => {
      const next = { ...prev, [label]: !(prev[label] !== false) };
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
              <h1 className="title">Strata</h1>
              <p className="subtitle">Media Intelligence</p>
            </>
          )}
        </div>
        <button
          type="button"
          className="sidebar-toggle-btn"
          onClick={mobileOpen ? onCloseMobile : onToggleCollapse}
          title={mobileOpen ? 'Close navigation' : (collapsed ? 'Expand navigation' : 'Collapse navigation')}
          aria-label={mobileOpen ? 'Close navigation' : (collapsed ? 'Expand navigation' : 'Collapse navigation')}
        >
          {mobileOpen ? <X size={18} /> : (collapsed ? <ChevronsRight size={18} /> : <ChevronsLeft size={18} />)}
        </button>
      </div>

      <nav className="sidebar-nav">
        {ALL_NAV_SECTIONS.map((section) => {
          // A section with nothing the user may see should not leave a stray heading.
          const visible = section.items.filter(
            (item) => !item.permission || hasPermission(item.permission),
          );
          if (!visible.length) return null;

          const links = visible.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className="btn-secondary sidebar-nav-link"
              style={navStyle}
              title={showCollapsed ? label : undefined}
              onClick={onCloseMobile}
            >
              <Icon size={18} /> {!showCollapsed && <span>{label}</span>}
            </NavLink>
          ));

          // Collapsed desktop rail stays a flat icon list; no headers to toggle.
          if (showCollapsed) {
            return <React.Fragment key={section.label}>{links}</React.Fragment>;
          }

          const open = isSectionOpen(section.label);
          const domId = sectionDomId(section.label);
          return (
            <div className="sidebar-nav-group" key={section.label}>
              <button
                type="button"
                className="sidebar-nav-section"
                onClick={() => toggleSection(section.label)}
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

      {user && (
        <div className="sidebar-profile">
          <div
            className="sidebar-profile-row"
            title={showCollapsed ? `${user.username} (${user.role})` : undefined}
          >
            <div className="sidebar-avatar">{initials}</div>
            {!showCollapsed && (
              <div className="sidebar-profile-meta">
                <span className="sidebar-profile-name">{user.username}</span>
                <span className={`panel-chip role-${user.role}`}>{user.role}</span>
              </div>
            )}
          </div>
          <button
            type="button"
            className="btn-secondary sidebar-logout"
            onClick={handleLogout}
            title={showCollapsed ? 'Log out' : undefined}
          >
            <LogOut size={16} /> {!showCollapsed && 'Log out'}
          </button>
        </div>
      )}
    </div>
  );
}
