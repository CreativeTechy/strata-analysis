import React, { useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import { CalendarDays, Plus, Pencil, Trash2, Check, X, Search, Flag, Clock3, Layers3, Link2, RefreshCw } from 'lucide-react';

const emptyDraft = {
  name: '',
  status: 'draft',
  description: '',
  location: '',
  target_audience: '',
  hashtags: '',
  keywords: '',
  start_date: '',
  end_date: '',
  feed_ids: [],
};

const STATUS_OPTIONS = ['draft', 'active', 'archived'];

function toDateInput(value) {
  if (!value) return '';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '';
  return parsed.toISOString().slice(0, 10);
}

function toListInput(values) {
  if (!Array.isArray(values)) return '';
  return values.join(', ');
}

function parseListInput(value) {
  return [...new Set(
    String(value || '')
      .split(/[\n,]/)
      .map((item) => item.trim())
      .filter(Boolean)
  )];
}

export default function EventsPage({
  events = [],
  feeds = [],
  onCreateEvent,
  onUpdateEvent,
  onDeleteEvent,
  isLoadingEvents,
}) {
  const [draft, setDraft] = useState(emptyDraft);
  const [editingId, setEditingId] = useState(null);
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [isSaving, setIsSaving] = useState(false);
  const [lastDiscovery, setLastDiscovery] = useState(null);

  const feedNameById = useMemo(() => {
    const map = new Map();
    feeds.forEach((feed) => {
      map.set(Number(feed.id), feed.name || feed.url || `Feed ${feed.id}`);
    });
    return map;
  }, [feeds]);

  const stats = useMemo(() => {
    const total = events.length;
    const active = events.filter((event) => (event.status || '').toLowerCase() === 'active').length;
    const draftCount = events.filter((event) => (event.status || '').toLowerCase() === 'draft').length;
    const archived = events.filter((event) => (event.status || '').toLowerCase() === 'archived').length;
    const assignedFeeds = new Set(events.flatMap((event) => (event.feed_ids || []).map(Number))).size;
    return { total, active, draftCount, archived, assignedFeeds };
  }, [events]);

  const visibleEvents = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return events.filter((event) => {
      const feedNames = (event.feed_ids || []).map((feedId) => feedNameById.get(Number(feedId))).filter(Boolean);
      const hashtagNames = (event.hashtags || []).map((value) => String(value).trim()).filter(Boolean);
      const keywordNames = (event.keywords || []).map((value) => String(value).trim()).filter(Boolean);
      const matchesQuery =
        !needle ||
        [
          event.name,
          event.status,
          event.description,
          event.location,
          event.target_audience,
          event.start_date,
          event.end_date,
          ...hashtagNames,
          ...keywordNames,
          ...feedNames,
        ]
          .filter(Boolean)
          .some((value) => String(value).toLowerCase().includes(needle));
      const matchesStatus = statusFilter === 'all' || (event.status || 'draft').toLowerCase() === statusFilter;
      return matchesQuery && matchesStatus;
    });
  }, [events, feedNameById, query, statusFilter]);

  useEffect(() => {
    if (!editingId) return;
    const current = events.find((event) => Number(event.id) === Number(editingId));
    if (!current) {
      setEditingId(null);
      setDraft(emptyDraft);
      return;
    }

    setDraft({
      name: current.name || '',
      status: current.status || 'draft',
      description: current.description || '',
      location: current.location || '',
      target_audience: current.target_audience || '',
      hashtags: toListInput(current.hashtags),
      keywords: toListInput(current.keywords),
      start_date: toDateInput(current.start_date),
      end_date: toDateInput(current.end_date),
      feed_ids: Array.isArray(current.feed_ids) ? current.feed_ids.map(Number) : [],
    });
  }, [events, editingId]);

  const beginEdit = (event) => {
    setEditingId(event.id);
    setLastDiscovery(null);
    setDraft({
      name: event.name || '',
      status: event.status || 'draft',
      description: event.description || '',
      location: event.location || '',
      target_audience: event.target_audience || '',
      hashtags: toListInput(event.hashtags),
      keywords: toListInput(event.keywords),
      start_date: toDateInput(event.start_date),
      end_date: toDateInput(event.end_date),
      feed_ids: Array.isArray(event.feed_ids) ? event.feed_ids.map(Number) : [],
    });
  };

  const reset = () => {
    setEditingId(null);
    setDraft(emptyDraft);
  };

  const toggleFeed = (feedId) => {
    const id = Number(feedId);
    setDraft((prev) => ({
      ...prev,
      feed_ids: prev.feed_ids.includes(id)
        ? prev.feed_ids.filter((value) => value !== id)
        : [...prev.feed_ids, id],
    }));
  };

  const submit = async () => {
    if (isSaving) return;

    const payload = {
      name: draft.name.trim(),
      status: draft.status,
      description: draft.description.trim(),
      location: draft.location.trim(),
      target_audience: draft.target_audience.trim(),
      hashtags: parseListInput(draft.hashtags),
      keywords: parseListInput(draft.keywords),
      start_date: draft.start_date || null,
      end_date: draft.end_date || null,
      feed_ids: draft.feed_ids,
    };

    if (!payload.name) return;

    setIsSaving(true);
    try {
      let result = null;
      if (editingId) {
        result = await onUpdateEvent?.(editingId, payload);
      } else {
        result = await onCreateEvent?.(payload);
      }
      setLastDiscovery(result?.discovery ?? null);
      reset();
    } finally {
      setIsSaving(false);
    }
  };

  const remove = async (event) => {
    const confirmed = window.confirm(`Delete event "${event.name}"?`);
    if (!confirmed) return;
    await onDeleteEvent?.(event.id);
    if (editingId === event.id) reset();
  };

  return (
    <div className="admin-page-shell">
      <div className="admin-page-header">
        <div>
          <div className="admin-page-kicker">
            <CalendarDays size={14} /> Event planner
          </div>
          <h1 className="admin-page-title">Events</h1>
          <p className="admin-page-subtitle">
            Shape each news cycle as its own workspace, attach shared feeds, and keep every scrape tied to a named event.
          </p>
        </div>
        <div className="admin-page-toolbar">
          <div className="admin-page-toolbar-meta">
            <span>Status</span>
            <strong>{events.length ? 'Configured' : 'Empty'}</strong>
          </div>
          <div className="admin-page-toolbar-meta">
            <span>Forms</span>
            <strong>{editingId ? 'Editing' : 'Creating'}</strong>
          </div>
        </div>
      </div>

      <div className="admin-stats-grid">
        <div className="admin-stat-card">
          <div className="admin-stat-icon"><Layers3 size={18} /></div>
          <div>
            <span>Total events</span>
            <strong>{stats.total.toLocaleString()}</strong>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon" style={{ background: 'rgba(46, 213, 115, 0.12)', color: '#2ed573' }}><Flag size={18} /></div>
          <div>
            <span>Active</span>
            <strong>{stats.active.toLocaleString()}</strong>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon" style={{ background: 'rgba(255, 159, 67, 0.14)', color: 'var(--primary-color)' }}><Clock3 size={18} /></div>
          <div>
            <span>Draft</span>
            <strong>{stats.draftCount.toLocaleString()}</strong>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon" style={{ background: 'rgba(116, 125, 140, 0.14)', color: '#747d8c' }}><Link2 size={18} /></div>
          <div>
            <span>Unique feeds in use</span>
            <strong>{stats.assignedFeeds.toLocaleString()}</strong>
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
            placeholder="Search events, dates, statuses, or assigned feeds"
          />
        </label>

        <select className="filter-select" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="all">All statuses</option>
          {STATUS_OPTIONS.map((status) => (
            <option key={status} value={status}>
              {status[0].toUpperCase() + status.slice(1)}
            </option>
          ))}
        </select>
      </div>

      <div className="admin-split-layout">
        <div className="glass-card admin-form-panel">
          <div className="panel-header-tight">
            <strong style={{ fontSize: '1rem' }}>{editingId ? 'Edit Event' : 'Add Event'}</strong>
            <span className="panel-chip">{editingId ? 'Update this event scope' : 'Create a new event scope'}</span>
          </div>
            <input
              type="text"
              className="feed-input"
              placeholder="Event name"
              value={draft.name}
              onChange={(e) => setDraft((prev) => ({ ...prev, name: e.target.value }))}
              disabled={isSaving}
            />
            <textarea
              className="feed-input"
              placeholder="Event description"
              rows={3}
              value={draft.description}
              onChange={(e) => setDraft((prev) => ({ ...prev, description: e.target.value }))}
              style={{ resize: 'vertical', minHeight: 92 }}
              disabled={isSaving}
            />
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              <input
                type="text"
                className="feed-input"
                placeholder="Location"
                value={draft.location}
                onChange={(e) => setDraft((prev) => ({ ...prev, location: e.target.value }))}
                disabled={isSaving}
              />
              <input
                type="text"
                className="feed-input"
                placeholder="Target audience"
                value={draft.target_audience}
                onChange={(e) => setDraft((prev) => ({ ...prev, target_audience: e.target.value }))}
                disabled={isSaving}
              />
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              <textarea
                className="feed-input"
                placeholder="Hashtags, comma or newline separated"
                rows={3}
                value={draft.hashtags}
                onChange={(e) => setDraft((prev) => ({ ...prev, hashtags: e.target.value }))}
                style={{ resize: 'vertical', minHeight: 92 }}
                disabled={isSaving}
              />
              <textarea
                className="feed-input"
                placeholder="Keywords, comma or newline separated"
                rows={3}
                value={draft.keywords}
                onChange={(e) => setDraft((prev) => ({ ...prev, keywords: e.target.value }))}
                style={{ resize: 'vertical', minHeight: 92 }}
                disabled={isSaving}
              />
            </div>
            <select
              className="filter-select"
              value={draft.status}
              onChange={(e) => setDraft((prev) => ({ ...prev, status: e.target.value }))}
              disabled={isSaving}
            >
              {STATUS_OPTIONS.map((status) => (
                <option key={status} value={status}>
                  {status[0].toUpperCase() + status.slice(1)}
                </option>
              ))}
            </select>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              <input
                type="date"
                className="feed-input"
                value={draft.start_date}
                onChange={(e) => setDraft((prev) => ({ ...prev, start_date: e.target.value }))}
                disabled={isSaving}
              />
              <input
                type="date"
                className="feed-input"
                value={draft.end_date}
                onChange={(e) => setDraft((prev) => ({ ...prev, end_date: e.target.value }))}
                disabled={isSaving}
              />
            </div>

            <div style={{ padding: '10px 0 2px', fontSize: '0.86rem', color: 'var(--text-light)' }}>
              Assign feeds
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 260, overflow: 'auto' }}>
              {feeds.length === 0 ? (
                <div style={{ color: 'var(--text-light)', fontSize: '0.85rem' }}>
                  No feeds yet. Add feeds first, then attach them to events.
                </div>
              ) : (
                feeds.map((feed) => (
                  <label
                    key={feed.id}
                    style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.85rem', color: 'var(--text-dark)' }}
                  >
                    <input
                      type="checkbox"
                      checked={draft.feed_ids.includes(Number(feed.id))}
                      onChange={() => toggleFeed(feed.id)}
                      disabled={isSaving}
                    />
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {feed.name || feed.url}
                    </span>
                  </label>
                ))
              )}
            </div>

          <div className="admin-form-hint">
            Selected feeds stay reusable across events. This page only controls the event envelope.
            {isSaving && (draft.hashtags.trim() || draft.keywords.trim())
              ? ' Finding feeds from your hashtags and keywords...'
              : ''}
          </div>

          {lastDiscovery && (
            <div
              style={{
                marginTop: 12,
                padding: 14,
                borderRadius: 16,
                background: 'rgba(255,255,255,0.72)',
                border: '1px solid rgba(15, 23, 42, 0.08)',
                display: 'flex',
                flexDirection: 'column',
                gap: 10,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
                <strong style={{ fontSize: '0.92rem', color: 'var(--text-dark)' }}>Discovery results</strong>
                <span className="panel-chip">
                  {(lastDiscovery.resolved_urls || []).length} source{(lastDiscovery.resolved_urls || []).length === 1 ? '' : 's'}
                </span>
              </div>

              {(lastDiscovery.resolved_urls || []).length > 0 ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {(lastDiscovery.resolved_urls || []).map((url) => (
                    <a
                      key={url}
                      href={url}
                      target="_blank"
                      rel="noreferrer"
                      style={{
                        fontSize: '0.84rem',
                        color: 'var(--text-dark)',
                        textDecoration: 'none',
                        padding: '10px 12px',
                        borderRadius: 12,
                        background: 'rgba(15, 23, 42, 0.04)',
                        wordBreak: 'break-word',
                      }}
                    >
                      {url}
                    </a>
                  ))}
                </div>
              ) : (
                <div style={{ fontSize: '0.84rem', color: 'var(--text-light)' }}>
                  No valid URLs were resolved from the hashtags and keywords for this save.
                </div>
              )}
            </div>
          )}

          <div style={{ display: 'flex', gap: 10 }}>
            <button className="btn-primary" onClick={submit} style={{ flex: 1 }} disabled={isSaving}>
              {isSaving ? (
                <>
                  <RefreshCw size={18} className="spin" />
                  {draft.hashtags.trim() || draft.keywords.trim() ? 'Finding feeds...' : 'Saving...'}
                </>
              ) : editingId ? (
                <>
                  <Check size={18} /> Save
                </>
              ) : (
                <>
                  <Plus size={18} /> Add
                </>
              )}
            </button>
            {editingId && !isSaving && (
              <button className="btn-secondary" onClick={reset} style={{ flexShrink: 0 }}>
                <X size={18} />
              </button>
            )}
          </div>
        </div>

        <div className="glass-card admin-list-panel">
          <div className="panel-header-tight">
            <strong style={{ fontSize: '1rem' }}>Tracked Events</strong>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              {isLoadingEvents && <span style={{ fontSize: '0.72rem', color: 'var(--text-light)' }}>Loading...</span>}
              <span className="panel-chip">{visibleEvents.length} visible</span>
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {events.length === 0 && !isLoadingEvents && (
              <div className="admin-empty-state">
                <div className="admin-empty-state-icon"><CalendarDays size={18} /></div>
                <strong>No events yet</strong>
                <span>Create your first event on the left to start scoping feeds and results.</span>
              </div>
            )}

            {visibleEvents.map((event, index) => {
              const assignedFeeds = (event.feed_ids || []).map((feedId) => feedNameById.get(Number(feedId))).filter(Boolean);
              const isActive = (event.status || '').toLowerCase() === 'active';
              return (
                <motion.div
                  key={event.id}
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.03 }}
                  className="admin-item-card"
                >
                  <div className="admin-item-top">
                    <div style={{ minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8, flexWrap: 'wrap' }}>
                        <strong className="admin-item-title">{event.name}</strong>
                        <span className={`panel-chip ${isActive ? 'success' : event.status === 'archived' ? 'muted' : 'warning'}`}>
                          {(event.status || 'draft').toUpperCase()}
                        </span>
                      </div>
                      <div className="admin-item-meta">
                        <span>{event.start_date || 'No start date'}</span>
                        <span>{event.end_date || 'No end date'}</span>
                        {event.location && <span>{event.location}</span>}
                        {event.target_audience && <span>{event.target_audience}</span>}
                        <span>{assignedFeeds.length} feed{assignedFeeds.length === 1 ? '' : 's'}</span>
                      </div>
                      <div className="admin-item-chips">
                        {(event.hashtags || []).slice(0, 4).map((tag) => (
                          <span key={`hash-${tag}`} className="admin-tag">
                            {tag}
                          </span>
                        ))}
                        {(event.keywords || []).slice(0, 4).map((tag) => (
                          <span key={`kw-${tag}`} className="admin-tag muted">
                            {tag}
                          </span>
                        ))}
                      </div>
                      {event.description && (
                        <div style={{ marginTop: 10, color: 'var(--text-light)', fontSize: '0.88rem', lineHeight: 1.5 }}>
                          {event.description}
                        </div>
                      )}
                      <div className="admin-item-chips">
                        {assignedFeeds.length ? (
                          assignedFeeds.slice(0, 4).map((name) => (
                            <span key={name} className="admin-tag">
                              {name}
                            </span>
                          ))
                        ) : (
                          <span className="admin-tag muted">No feeds assigned</span>
                        )}
                      </div>
                    </div>

                    <div className="admin-item-actions">
                      <button className="btn-secondary" onClick={() => beginEdit(event)} style={{ padding: '8px 10px', fontSize: '0.8rem' }}>
                        <Pencil size={14} /> Edit
                      </button>
                      <button className="btn-secondary" onClick={() => remove(event)} style={{ padding: '8px 10px', fontSize: '0.8rem', color: '#ff4757' }}>
                        <Trash2 size={14} /> Delete
                      </button>
                    </div>
                  </div>
                </motion.div>
              );
            })}

            {!isLoadingEvents && visibleEvents.length === 0 && events.length > 0 && (
              <div className="admin-empty-state">
                <div className="admin-empty-state-icon"><Search size={18} /></div>
                <strong>No matching events</strong>
                <span>Try another search term or switch the status filter.</span>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
