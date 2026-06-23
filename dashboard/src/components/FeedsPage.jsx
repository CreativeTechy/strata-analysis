import React, { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { Rss, Plus, Pencil, Trash2, Check, X, ToggleLeft, ToggleRight } from 'lucide-react';

const emptyDraft = {
  url: '',
  name: '',
  source_type: 'rss',
  category: '',
  enabled: true,
};

export default function FeedsPage({
  feeds = [],
  feedsSource,
  onCreateFeed,
  onUpdateFeed,
  onDeleteFeed,
  isLoadingFeeds,
}) {
  const [draft, setDraft] = useState(emptyDraft);
  const [editingId, setEditingId] = useState(null);

  useEffect(() => {
    if (!editingId) return;
    const current = feeds.find((feed) => feed.id === editingId);
    if (!current) {
      setEditingId(null);
      setDraft(emptyDraft);
    }
  }, [feeds, editingId]);

  const beginEdit = (feed) => {
    setEditingId(feed.id);
    setDraft({
      url: feed.url || '',
      name: feed.name || '',
      source_type: feed.source_type || 'rss',
      category: feed.category || '',
      enabled: feed.enabled ?? true,
    });
  };

  const reset = () => {
    setEditingId(null);
    setDraft(emptyDraft);
  };

  const submit = async () => {
    const payload = {
      url: draft.url.trim(),
      name: draft.name.trim(),
      source_type: draft.source_type,
      category: draft.category.trim(),
      enabled: Boolean(draft.enabled),
    };

    if (!payload.url) return;

    if (editingId) {
      await onUpdateFeed?.(editingId, payload);
    } else {
      await onCreateFeed?.(payload);
    }
    reset();
  };

  const toggle = async (feed) => {
    await onUpdateFeed?.(feed.id, {
      ...feed,
      enabled: !feed.enabled,
    });
  };

  const remove = async (feed) => {
    const confirmed = window.confirm(`Delete feed "${feed.name || feed.url}"?`);
    if (!confirmed) return;
    await onDeleteFeed?.(feed.id);
    if (editingId === feed.id) reset();
  };

  return (
    <div style={{ minHeight: '100vh', padding: '32px 28px 40px' }}>
      <div style={{ maxWidth: 1200, margin: '0 auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
          <Rss size={26} color="#ff6b35" />
          <h1 style={{ fontSize: '1.9rem', fontWeight: 800, margin: 0 }}>Feed Manager</h1>
        </div>
        <p style={{ color: 'var(--text-light)', marginBottom: 24 }}>
          Add, edit, enable, disable, and remove tracked sources. Source: {feedsSource || 'supabase'}.
        </p>

        <div style={{ display: 'grid', gridTemplateColumns: '360px 1fr', gap: 20, alignItems: 'start' }}>
          <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <strong style={{ fontSize: '1rem' }}>{editingId ? 'Edit Feed' : 'Add Feed'}</strong>
            <input
              type="text"
              className="feed-input"
              placeholder="Feed URL"
              value={draft.url}
              onChange={(e) => setDraft((prev) => ({ ...prev, url: e.target.value }))}
            />
            <input
              type="text"
              className="feed-input"
              placeholder="Display name"
              value={draft.name}
              onChange={(e) => setDraft((prev) => ({ ...prev, name: e.target.value }))}
            />
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              <select
                className="filter-select"
                value={draft.source_type}
                onChange={(e) => setDraft((prev) => ({ ...prev, source_type: e.target.value }))}
              >
                <option value="rss">RSS</option>
                <option value="web">Web</option>
                <option value="social">Social</option>
              </select>
              <input
                type="text"
                className="feed-input"
                placeholder="Category"
                value={draft.category}
                onChange={(e) => setDraft((prev) => ({ ...prev, category: e.target.value }))}
              />
            </div>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.85rem', color: 'var(--text-dark)' }}>
              <input
                type="checkbox"
                checked={draft.enabled}
                onChange={(e) => setDraft((prev) => ({ ...prev, enabled: e.target.checked }))}
              />
              Enabled
            </label>
            <div style={{ display: 'flex', gap: 10 }}>
              <button className="btn-primary" onClick={submit} style={{ flex: 1 }}>
                {editingId ? <><Check size={18} /> Save</> : <><Plus size={18} /> Add</>}
              </button>
              {editingId && (
                <button className="btn-secondary" onClick={reset} style={{ flexShrink: 0 }}>
                  <X size={18} />
                </button>
              )}
            </div>
          </div>

          <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
              <strong style={{ fontSize: '1rem' }}>Tracked Feeds</strong>
              {isLoadingFeeds && <span style={{ fontSize: '0.72rem', color: 'var(--text-light)' }}>Loading...</span>}
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {feeds.length === 0 && !isLoadingFeeds && (
                <div style={{ color: 'var(--text-light)', padding: '20px 0', textAlign: 'center' }}>
                  No feeds yet.
                </div>
              )}

              {feeds.map((feed, index) => (
                <motion.div
                  key={feed.id ?? feed.url}
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.03 }}
                  style={{
                    border: '1px solid rgba(0,0,0,0.06)',
                    borderRadius: 14,
                    padding: '14px 16px',
                    background: 'rgba(255,255,255,0.55)',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'flex-start' }}>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                        <strong style={{ fontSize: '0.95rem' }}>{feed.name || feed.url?.replace('https://www.', '')}</strong>
                        <button
                          onClick={() => toggle(feed)}
                          style={{ background: 'none', border: 'none', color: feed.enabled ? '#2ed573' : '#9aa0aa', cursor: 'pointer', display: 'flex', alignItems: 'center' }}
                          title={feed.enabled ? 'Disable feed' : 'Enable feed'}
                        >
                          {feed.enabled ? <ToggleRight size={18} /> : <ToggleLeft size={18} />}
                        </button>
                      </div>
                      <div style={{ fontSize: '0.78rem', color: 'var(--text-light)', wordBreak: 'break-all' }}>
                        {feed.url}
                      </div>
                      <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap', fontSize: '0.68rem', textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--text-light)' }}>
                        <span>{feed.source_type || 'rss'}</span>
                        {feed.category ? <span style={{ color: 'var(--secondary-color)' }}>{feed.category}</span> : null}
                      </div>
                    </div>

                    <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>
                      <button className="btn-secondary" onClick={() => beginEdit(feed)} style={{ padding: '8px 10px', fontSize: '0.8rem' }}>
                        <Pencil size={14} /> Edit
                      </button>
                      <button className="btn-secondary" onClick={() => remove(feed)} style={{ padding: '8px 10px', fontSize: '0.8rem', color: '#ff4757' }}>
                        <Trash2 size={14} /> Delete
                      </button>
                    </div>
                  </div>
                </motion.div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
