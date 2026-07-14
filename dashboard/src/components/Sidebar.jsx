import React from 'react';
import { LayoutDashboard, GitMerge, Bug, BarChart3, MessageSquare, Rss, Play, Newspaper, Database, CalendarDays, Users, LogOut } from 'lucide-react';
import { NavLink, Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/useAuth.js';

export default function Sidebar({
  onToggleSource,
}) {
  const { user, hasRole, logout } = useAuth();
  const navigate = useNavigate();
  const canRunScraper = hasRole('operator');

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
    justifyContent: 'flex-start',
  });

  return (
    <div className="sidebar">
      <div style={{ marginBottom: '20px' }}>
        <h1 className="title">Strata</h1>
        <p className="subtitle">Media Intelligence</p>
      </div>

      <nav style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginBottom: '24px' }}>
        <NavLink to="/dashboard" className="btn-secondary" style={navStyle}>
          <LayoutDashboard size={18} /> Dashboard
        </NavLink>
        <NavLink to="/articles" className="btn-secondary" style={navStyle}>
          <Newspaper size={18} /> Articles
        </NavLink>
        <NavLink to="/sources" className="btn-secondary" style={navStyle}>
          <Rss size={18} /> Sources
        </NavLink>
        <NavLink to="/events" className="btn-secondary" style={navStyle}>
          <CalendarDays size={18} /> Events
        </NavLink>
        <NavLink to="/workflow" className="btn-secondary" style={navStyle}>
          <GitMerge size={18} /> Workflow
        </NavLink>
        <NavLink to="/pipeline-runs" className="btn-secondary" style={navStyle}>
          <Database size={18} /> Pipeline Runs
        </NavLink>
        {canRunScraper && (
          <NavLink to="/spider" className="btn-secondary" style={navStyle}>
            <Bug size={18} /> Spider Mode
          </NavLink>
        )}
        <NavLink to="/sentiment" className="btn-secondary" style={navStyle}>
          <BarChart3 size={18} /> Brand Sentiment
        </NavLink>
        <NavLink to="/intelligence" className="btn-secondary" style={navStyle}>
          <MessageSquare size={18} /> Intelligence
        </NavLink>
        {hasRole('admin') && (
          <NavLink to="/admin/users" className="btn-secondary" style={navStyle}>
            <Users size={18} /> Users
          </NavLink>
        )}
      </nav>

      <Link
        to="/workflow"
        className="btn-primary"
        style={{ width: '100%', textDecoration: 'none', opacity: canRunScraper ? 1 : 0.6 }}
        title={canRunScraper ? undefined : 'Viewing only - running scrapes requires the operator or admin role.'}
      >
        <Play size={18} />
        Run Scraper
      </Link>

      {user && (
        <div className="sidebar-profile">
          <div className="sidebar-profile-row">
            <div className="sidebar-avatar">{initials}</div>
            <div className="sidebar-profile-meta">
              <span className="sidebar-profile-name">{user.username}</span>
              <span className={`panel-chip role-${user.role}`}>{user.role}</span>
            </div>
          </div>
          <button type="button" className="btn-secondary sidebar-logout" onClick={handleLogout}>
            <LogOut size={16} /> Log out
          </button>
        </div>
      )}
    </div>
  );
}
