import React, { useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import { Rss, Plus, Pencil, Trash2, Check, X, ToggleLeft, ToggleRight, Search, Link2, CheckCircle2, Layers3 } from 'lucide-react';

const emptyDraft = {
  url: '',
  name: '',
  source_type: 'rss',
  category: '',
  enabled: true,
  event_ids: [],
};

const PAGE_SIZE = 10;

export default function FeedsPage({
  feeds = [],
  events = [],
  feedsSource,
  onCreateFeed,
  onUpdateFeed,
  onDeleteFeed,
  isLoadingFeeds,
}) {
  const [draft, setDraft] = useState(emptyDraft);
  const [editingId, setEditingId] = useState(null);
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [currentPage, setCurrentPage] = useState(1);

  useEffect(() => {
    if (!editingId) return;
    const current = feeds.find((feed) => feed.id === editingId);
    if (!current) {
      setEditingId(null);
      setDraft(emptyDraft);
    }
  }, [feeds, editingId]);

  const feedEventsById = useMemo(() => {
    const map = new Map();
    events.forEach((event) => {
      (event.feed_ids || []).forEach((feedId) => {
        const id = Number(feedId);
        if (!map.has(id)) map.set(id, []);
        map.get(id).push(event);
      });
    });
    return map;
  }, [events]);

  const stats = useMemo(() => {
    const total = feeds.length;
    const enabled = feeds.filter((feed) => feed.enabled).length;
    const assigned = feeds.filter((feed) => (feedEventsById.get(Number(feed.id)) || []).length > 0).length;
    const rss = feeds.filter((feed) => (feed.source_type || 'rss') === 'rss').length;
    return { total, enabled, assigned, rss };
  }, [feeds, feedEventsById]);

  const visibleFeeds = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return feeds.filter((feed) => {
      const feedEvents = feedEventsById.get(Number(feed.id)) || [];
      const matchesQuery =
        !needle ||
        [feed.name, feed.url, feed.category, feed.source_type, ...feedEvents.map((event) => event.name)]
          .filter(Boolean)
          .some((value) => String(value).toLowerCase().includes(needle));
      const matchesStatus =
        statusFilter === 'all' ||
        (statusFilter === 'enabled' && feed.enabled) ||
        (statusFilter === 'disabled' && !feed.enabled) ||
        (statusFilter === 'assigned' && feedEvents.length > 0) ||
        (statusFilter === 'unassigned' && feedEvents.length === 0);
      return matchesQuery && matchesStatus;
    });
  }, [feeds, feedEventsById, query, statusFilter]);

  const totalPages = Math.max(1, Math.ceil(visibleFeeds.length / PAGE_SIZE));
  const safePage = Math.min(currentPage, totalPages);
  const pagedFeeds = useMemo(() => {
    const start = (safePage - 1) * PAGE_SIZE;
    return visibleFeeds.slice(start, start + PAGE_SIZE);
  }, [visibleFeeds, safePage]);

  useEffect(() => {
    setCurrentPage(1);
  }, [query, statusFilter]);

  useEffect(() => {
    if (currentPage > totalPages) {
      setCurrentPage(totalPages);
    }
  }, [currentPage, totalPages]);

  const beginEdit = (feed) => {
    setEditingId(feed.id);
    const assignedEventIds = events
      .filter((event) => Array.isArray(event.feed_ids) && event.feed_ids.map(Number).includes(Number(feed.id)))
      .map((event) => Number(event.id));
    setDraft({
      url: feed.url || '',
      name: feed.name || '',
      source_type: feed.source_type || 'rss',
      category: feed.category || '',
      enabled: feed.enabled ?? true,
      event_ids: assignedEventIds,
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
      event_ids: draft.event_ids,
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

  const toggleEvent = (eventId) => {
    const id = Number(eventId);
    setDraft((prev) => ({
      ...prev,
      event_ids: prev.event_ids.includes(id)
        ? prev.event_ids.filter((value) => value !== id)
        : [...prev.event_ids, id],
    }));
  };

  const remove = async (feed) => {
    const confirmed = window.confirm(`Delete feed "${feed.name || feed.url}"?`);
    if (!confirmed) return;
    await onDeleteFeed?.(feed.id);
    if (editingId === feed.id) reset();
  };

  return (
    <div className="admin-page-shell">
      <div className="admin-page-header">
        <div>
          <div className="admin-page-kicker">
            <Rss size={14} /> Source library
          </div>
          <h1 className="admin-page-title">Feed Manager</h1>
          <p className="admin-page-subtitle">
            Curate the source pool, assign feeds to one or more events, and keep enabled sources easy to scan.
          </p>
        </div>
        <div className="admin-page-toolbar">
          <div className="admin-page-toolbar-meta">
            <span>Source</span>
            <strong>{feedsSource || 'supabase'}</strong>
          </div>
          <div className="admin-page-toolbar-meta">
            <span>Editing</span>
            <strong>{editingId ? 'Active' : 'None'}</strong>
          </div>
        </div>
      </div>

      <div className="admin-stats-grid">
        <div className="admin-stat-card">
          <div className="admin-stat-icon"><Layers3 size={18} /></div>
          <div>
            <span>Total feeds</span>
            <strong>{stats.total.toLocaleString()}</strong>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon" style={{ background: 'rgba(46, 213, 115, 0.12)', color: '#2ed573' }}><CheckCircle2 size={18} /></div>
          <div>
            <span>Enabled</span>
            <strong>{stats.enabled.toLocaleString()}</strong>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon" style={{ background: 'rgba(46, 134, 222, 0.12)', color: 'var(--secondary-color)' }}><Link2 size={18} /></div>
          <div>
            <span>Assigned</span>
            <strong>{stats.assigned.toLocaleString()}</strong>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon" style={{ background: 'rgba(255, 159, 67, 0.14)', color: 'var(--primary-color)' }}><Rss size={18} /></div>
          <div>
            <span>RSS feeds</span>
            <strong>{stats.rss.toLocaleString()}</strong>
          </div>
        </div>
      </div>

      <div className="admin-toolbar-row">
        <label className="admin-search">
          <Search size={16} />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search feeds, URLs, categories, or event names"
          />
        </label>

        <select className="filter-select" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="all">All feeds</option>
          <option value="enabled">Enabled</option>
          <option value="disabled">Disabled</option>
          <option value="assigned">Assigned</option>
          <option value="unassigned">Unassigned</option>
        </select>
      </div>

      <div className="admin-split-layout">
        <div className="glass-card admin-form-panel">
          <div className="panel-header-tight">
            <strong style={{ fontSize: '1rem' }}>{editingId ? 'Edit Feed' : 'Add Feed'}</strong>
            <span className="panel-chip">{editingId ? 'Updating existing source' : 'Create a new source'}</span>
          </div>
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

            <div style={{ padding: '8px 0 2px', fontSize: '0.86rem', color: 'var(--text-light)' }}>
              Assign to events
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 220, overflow: 'auto' }}>
              {events.length === 0 ? (
                <div style={{ color: 'var(--text-light)', fontSize: '0.85rem' }}>
                  No events yet. Create an event first.
                </div>
              ) : (
                events.map((event) => (
                  <label
                    key={event.id}
                    style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.85rem', color: 'var(--text-dark)' }}
                  >
                    <input
                      type="checkbox"
                      checked={draft.event_ids.includes(Number(event.id))}
                      onChange={() => toggleEvent(event.id)}
                    />
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {event.name}
                    </span>
                  </label>
                ))
              )}
            </div>

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

        <div className="glass-card admin-list-panel">
          <div className="panel-header-tight">
            <strong style={{ fontSize: '1rem' }}>Tracked Feeds</strong>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              {isLoadingFeeds && <span style={{ fontSize: '0.72rem', color: 'var(--text-light)' }}>Loading...</span>}
              <span className="panel-chip">{visibleFeeds.length} visible</span>
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {feeds.length === 0 && !isLoadingFeeds && (
              <div className="admin-empty-state">
                <div className="admin-empty-state-icon"><Rss size={18} /></div>
                <strong>No feeds yet</strong>
                <span>Add your first source on the left, then attach it to one or more events.</span>
              </div>
            )}

            {pagedFeeds.map((feed, index) => {
              const feedEvents = feedEventsById.get(Number(feed.id)) || [];
              return (
                <motion.div
                  key={feed.id ?? feed.url}
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.03 }}
                  className="admin-item-card"
                >
                  <div className="admin-item-top">
                    <div style={{ minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8, flexWrap: 'wrap' }}>
                        <strong className="admin-item-title">{feed.name || feed.url?.replace('https://www.', '')}</strong>
                        <span className={`panel-chip ${feed.enabled ? 'success' : 'muted'}`}>
                          {feed.enabled ? 'Enabled' : 'Disabled'}
                        </span>
                        <button
                          onClick={() => toggle(feed)}
                          className="admin-icon-btn"
                          title={feed.enabled ? 'Disable feed' : 'Enable feed'}
                        >
                          {feed.enabled ? <ToggleRight size={18} /> : <ToggleLeft size={18} />}
                        </button>
                      </div>
                      <div className="admin-item-url">{feed.url}</div>
                      <div className="admin-item-meta">
                        <span>{feed.source_type || 'rss'}</span>
                        {feed.category ? <span>{feed.category}</span> : null}
                        <span>{feedEvents.length} event{feedEvents.length === 1 ? '' : 's'}</span>
                      </div>
                    </div>

                    <div className="admin-item-actions">
                      <button className="btn-secondary" onClick={() => beginEdit(feed)} style={{ padding: '8px 10px', fontSize: '0.8rem' }}>
                        <Pencil size={14} /> Edit
                      </button>
                      <button className="btn-secondary" onClick={() => remove(feed)} style={{ padding: '8px 10px', fontSize: '0.8rem', color: '#ff4757' }}>
                        <Trash2 size={14} /> Delete
                      </button>
                    </div>
                  </div>
                  <div className="admin-item-chips">
                    {feedEvents.length ? (
                      feedEvents.slice(0, 4).map((event) => (
                        <span key={event.id} className="admin-tag">
                          {event.name}
                        </span>
                      ))
                    ) : (
                      <span className="admin-tag muted">Unassigned</span>
                    )}
                  </div>
                </motion.div>
              );
            })}

            {!isLoadingFeeds && visibleFeeds.length === 0 && feeds.length > 0 && (
              <div className="admin-empty-state">
                <div className="admin-empty-state-icon"><Search size={18} /></div>
                <strong>No matching feeds</strong>
                <span>Try a different search term or status filter.</span>
              </div>
            )}
          </div>

          {visibleFeeds.length > 0 && (
            <div
              style={{
                marginTop: 14,
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                gap: 12,
                flexWrap: 'wrap',
                paddingTop: 12,
                borderTop: '1px solid rgba(15, 23, 42, 0.08)',
              }}
            >
              <div style={{ fontSize: '0.84rem', color: 'var(--text-light)' }}>
                Showing {(safePage - 1) * PAGE_SIZE + 1}-{Math.min(safePage * PAGE_SIZE, visibleFeeds.length)} of {visibleFeeds.length}
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <button
                  className="btn-secondary"
                  onClick={() => setCurrentPage((value) => Math.max(1, value - 1))}
                  disabled={safePage <= 1}
                  style={{ padding: '8px 10px', fontSize: '0.8rem' }}
                >
                  Previous
                </button>
                <span className="panel-chip">
                  Page {safePage} of {totalPages}
                </span>
                <button
                  className="btn-secondary"
                  onClick={() => setCurrentPage((value) => Math.min(totalPages, value + 1))}
                  disabled={safePage >= totalPages}
                  style={{ padding: '8px 10px', fontSize: '0.8rem' }}
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
