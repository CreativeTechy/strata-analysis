import React from 'react';
import {
  LayoutDashboard,
  BarChart3,
  GitMerge,
  MessageSquare,
  Rss,
  Newspaper,
  Database,
  CalendarDays,
  Users,
  ShieldCheck,
  Link2,
  LogOut,
  ChevronsLeft,
  ChevronsRight,
  X,
} from 'lucide-react';
import { NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/useAuth.js';

const NAV_ITEMS = [
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/reports', label: 'Reports', icon: BarChart3 },
  { to: '/articles', label: 'Articles', icon: Newspaper },
  { to: '/sources', label: 'Sources', icon: Rss },
  { to: '/projects', label: 'Projects', icon: CalendarDays },
  { to: '/workflow', label: 'Workflow', icon: GitMerge },
  { to: '/pipeline-runs', label: 'Pipeline Runs', icon: Database },
  { to: '/intelligence', label: 'Copilot', icon: MessageSquare },
];

const ADMIN_NAV_ITEMS = [
  { to: '/admin/users', label: 'Users', icon: Users, permission: 'users.view' },
  { to: '/admin/roles', label: 'Roles', icon: ShieldCheck, permission: 'roles.view' },
  { to: '/admin/project-linkage', label: 'Project Access', icon: Link2, permission: 'projects.link_users' },
];

export default function Sidebar({
  collapsed = false,
  onToggleCollapse = () => {},
  mobileOpen = false,
  onCloseMobile = () => {},
}) {
  const { user, hasPermission, logout } = useAuth();
  const navigate = useNavigate();

  // On mobile the drawer always renders fully expanded; only the desktop rail collapses.
  const showCollapsed = collapsed && !mobileOpen;

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
        {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
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
        ))}
        {ADMIN_NAV_ITEMS.filter((item) => hasPermission(item.permission)).map(({ to, label, icon: Icon }) => (
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
        ))}
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
