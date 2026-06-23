import React from 'react';
import { LayoutDashboard, ToggleLeft, ToggleRight, GitMerge, Bug, BarChart3, MessageSquare, Rss, Play } from 'lucide-react';
import { motion } from 'framer-motion';
import { NavLink } from 'react-router-dom';

export default function Sidebar({
  feeds = [],
  onToggleFeed,
  onRunScraper,
  isScraping,
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
        <NavLink to="/feeds" className="btn-secondary" style={navStyle}>
          <Rss size={18} /> Feeds
        </NavLink>
        <NavLink to="/workflow" className="btn-secondary" style={navStyle}>
          <GitMerge size={18} /> Workflow
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

      <div className="glass-card" style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '10px', marginBottom: '12px' }}>
          <strong style={{ fontSize: '0.92rem' }}>Tracked Feeds</strong>
          <span style={{ fontSize: '0.72rem', color: 'var(--text-light)' }}>{feeds.length}</span>
        </div>

        <div className="feed-list" style={{ flex: 1, overflowY: 'auto' }}>
          {feeds.length === 0 ? (
            <div style={{ fontSize: '0.85rem', color: 'var(--text-light)', padding: '8px 0' }}>
              No feeds yet.
            </div>
          ) : feeds.map((feed) => (
            <motion.div
              key={feed.id ?? feed.url}
              layout
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              className="feed-item"
              style={{ gap: '10px', alignItems: 'center' }}
            >
              <button
                onClick={() => onToggleFeed?.(feed)}
                style={{ background: 'none', border: 'none', color: feed.enabled ? '#2ed573' : '#9aa0aa', cursor: 'pointer', display: 'flex', alignItems: 'center' }}
                title={feed.enabled ? 'Disable feed' : 'Enable feed'}
              >
                {feed.enabled ? <ToggleRight size={18} /> : <ToggleLeft size={18} />}
              </button>

              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ fontSize: '0.84rem', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {feed.name || feed.url?.replace('https://www.', '')}
                </div>
                <div style={{ fontSize: '0.72rem', color: 'var(--text-light)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {feed.url}
                </div>
              </div>
            </motion.div>
          ))}
        </div>

        <button
          className="btn-primary"
          style={{ marginTop: '20px', width: '100%' }}
          onClick={onRunScraper}
          disabled={isScraping}
        >
          {isScraping ? (
            <motion.div animate={{ rotate: 360 }} transition={{ repeat: Infinity, duration: 1, ease: 'linear' }}>
              <Play size={18} />
            </motion.div>
          ) : <Play size={18} />}
          {isScraping ? 'Scraping...' : 'Run Scraper'}
        </button>
      </div>
    </div>
  );
}
