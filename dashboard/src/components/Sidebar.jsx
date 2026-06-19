import React, { useState } from 'react';
import { Plus, Trash2, Play, Rss, Settings, LayoutDashboard } from 'lucide-react';
import { motion } from 'framer-motion';

export default function Sidebar({ feeds, setFeeds, onRunScraper, isScraping }) {
  const [newFeed, setNewFeed] = useState('');

  const addFeed = () => {
    if (newFeed && !feeds.includes(newFeed)) {
      setFeeds([...feeds, newFeed]);
      setNewFeed('');
    }
  };

  const removeFeed = (feedToRemove) => {
    setFeeds(feeds.filter(f => f !== feedToRemove));
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
        
        <div className="feed-list" style={{ flex: 1, overflowY: 'auto' }}>
          {feeds.map(feed => (
            <motion.div key={feed} layout initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }} className="feed-item">
              <span style={{ fontSize: '0.85rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {feed.replace('https://www.', '')}
              </span>
              <button onClick={() => removeFeed(feed)} style={{ background: 'none', border: 'none', color: '#ff4757', cursor: 'pointer' }}>
                <Trash2 size={16} />
              </button>
            </motion.div>
          ))}
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
