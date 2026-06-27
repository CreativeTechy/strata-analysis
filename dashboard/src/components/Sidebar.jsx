import React from 'react';
import { LayoutDashboard, GitMerge, Bug, BarChart3, MessageSquare, Rss, Play, Newspaper, Database, CalendarDays } from 'lucide-react';
import { NavLink, Link } from 'react-router-dom';

export default function Sidebar({
  onToggleFeed,
}) {
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
        <NavLink to="/feeds" className="btn-secondary" style={navStyle}>
          <Rss size={18} /> Feeds
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
        <NavLink to="/spider" className="btn-secondary" style={navStyle}>
          <Bug size={18} /> Spider Mode
        </NavLink>
        <NavLink to="/sentiment" className="btn-secondary" style={navStyle}>
          <BarChart3 size={18} /> Brand Sentiment
        </NavLink>
        <NavLink to="/intelligence" className="btn-secondary" style={navStyle}>
          <MessageSquare size={18} /> Intelligence
        </NavLink>
      </nav>

      <Link
        to="/workflow"
        className="btn-primary"
        style={{ width: '100%', textDecoration: 'none' }}
      >
        <Play size={18} />
        Run Scraper
      </Link>
    </div>
  );
}
