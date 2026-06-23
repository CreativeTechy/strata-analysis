import React, { useMemo, useState } from 'react';
import { Plus, Trash2, Play, Rss, Settings, LayoutDashboard, ToggleLeft, ToggleRight } from 'lucide-react';
import { motion } from 'framer-motion';

export default function Sidebar({
  feeds,
  feedsSource,
  onAddFeed,
  onToggleFeed,
  onRemoveFeed,
  onRunScraper,
  isScraping,
  isLoadingFeeds,
}) {
  const [newFeed, setNewFeed] = useState('');

  const visibleFeeds = useMemo(() => feeds || [], [feeds]);

  const addFeed = async () => {
    const url = newFeed.trim();
    if (!url) return;
    await onAddFeed?.({ url });
    setNewFeed('');
  };

  return (
    <div className="sidebar">
      <div style={{ marginBottom: '20px' }}>
        <h1 className="title">Strata</h1>
        <p className="subtitle">Media Intelligence</p>
      </div>

      <nav style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginBottom: '30px' }}>
        <button className="btn-secondary" style={{ background: 'white', borderColor: 'transparent', boxShadow: '0 4px 10px rgba(0,0,0,0.05)' }}>
          <LayoutDashboard size={18} /> Dashboard
        </button>
        <button className="btn-secondary" style={{ border: 'none', background: 'transparent' }}>
          <Settings size={18} /> Settings
        </button>
      </nav>

      <div className="glass-card" style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        <h3 style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
          <Rss size={18} color="var(--primary-color)" /> Tracked Feeds
        </h3>
        <div style={{ fontSize: '0.72rem', color: 'var(--text-light)', marginBottom: '10px' }}>
          Source: {feedsSource || 'supabase'}
        </div>

        <div className="feed-list" style={{ flex: 1, overflowY: 'auto' }}>
          {isLoadingFeeds && (
            <div style={{ fontSize: '0.85rem', color: 'var(--text-light)', padding: '8px 0' }}>
              Loading feeds...
            </div>
          )}

          {!isLoadingFeeds && visibleFeeds.map((feed) => (
            <motion.div
              key={feed.id ?? feed.url}
              layout
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
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

              <button
                onClick={() => onRemoveFeed?.(feed)}
                style={{ background: 'none', border: 'none', color: '#ff4757', cursor: 'pointer', flexShrink: 0 }}
                title="Remove feed"
              >
                <Trash2 size={16} />
              </button>
            </motion.div>
          ))}

          {!isLoadingFeeds && visibleFeeds.length === 0 && (
            <div style={{ fontSize: '0.85rem', color: 'var(--text-light)', padding: '8px 0' }}>
              No feeds yet.
            </div>
          )}
        </div>

        <div className="feed-input-group">
          <input
            type="text"
            className="feed-input"
            placeholder="Add new RSS..."
            value={newFeed}
            onChange={(e) => setNewFeed(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && addFeed()}
          />
          <button className="btn-secondary" onClick={addFeed} style={{ padding: '10px' }}>
            <Plus size={18} />
          </button>
        </div>

        <button
          className="btn-primary"
          style={{ marginTop: '20px', width: '100%' }}
          onClick={onRunScraper}
          disabled={isScraping}
        >
          {isScraping ? (
            <motion.div animate={{ rotate: 360 }} transition={{ repeat: Infinity, duration: 1, ease: "linear" }}>
              <Settings size={18} />
            </motion.div>
          ) : <Play size={18} />}
          {isScraping ? 'Scraping...' : 'Run Scraper'}
        </button>
      </div>
    </div>
  );
}
