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
const PAGE_SIZE = 10;

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
  const [currentPage, setCurrentPage] = useState(1);
  const [feedAssignQuery, setFeedAssignQuery] = useState('');

  const feedNameById = useMemo(() => {
    const map = new Map();
    feeds.forEach((feed) => {
      map.set(Number(feed.id), feed.name || feed.url || `Feed ${feed.id}`);
    });
    return map;
  }, [feeds]);

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

  const visibleAssignableFeeds = useMemo(() => {
    const needle = feedAssignQuery.trim().toLowerCase();
    if (!needle) return feeds;

    return feeds.filter((feed) => {
      const searchable = [
        feed.name,
        feed.url,
        feed.category,
        feed.source_type,
        feed.enabled ? 'enabled' : 'disabled',
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(needle));
      return searchable;
    });
  }, [feeds, feedAssignQuery]);

  const selectedFeedCount = draft.feed_ids.length;
  const visibleSelectedCount = visibleAssignableFeeds.filter((feed) => draft.feed_ids.includes(Number(feed.id))).length;
  const allVisibleSelected = visibleAssignableFeeds.length > 0 && visibleSelectedCount === visibleAssignableFeeds.length;

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

  const totalPages = Math.max(1, Math.ceil(visibleEvents.length / PAGE_SIZE));
  const safePage = Math.min(currentPage, totalPages);
  const pagedEvents = useMemo(() => {
    const start = (safePage - 1) * PAGE_SIZE;
    return visibleEvents.slice(start, start + PAGE_SIZE);
  }, [visibleEvents, safePage]);

  useEffect(() => {
    setCurrentPage(1);
  }, [query, statusFilter]);

  useEffect(() => {
    if (currentPage > totalPages) {
      setCurrentPage(totalPages);
    }
  }, [currentPage, totalPages]);

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
    setFeedAssignQuery('');
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
    setFeedAssignQuery('');
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

  const selectAllVisibleFeeds = () => {
    setDraft((prev) => ({
      ...prev,
      feed_ids: Array.from(
        new Set([
          ...prev.feed_ids,
          ...visibleAssignableFeeds.map((feed) => Number(feed.id)),
        ])
      ),
    }));
  };

  const clearVisibleFeeds = () => {
    const visibleIds = new Set(visibleAssignableFeeds.map((feed) => Number(feed.id)));
    setDraft((prev) => ({
      ...prev,
      feed_ids: prev.feed_ids.filter((id) => !visibleIds.has(Number(id))),
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

            <div className="assign-feeds-panel">
              <div className="assign-feeds-header">
                <div>
                  <div className="assign-feeds-kicker">Assign feeds</div>
                  <strong className="assign-feeds-title">Choose the sources that should power this event</strong>
                </div>
                <div className="assign-feeds-summary">
                  <span className="panel-chip">{selectedFeedCount} selected</span>
                  <span className="panel-chip muted">{visibleAssignableFeeds.length} shown</span>
                </div>
              </div>

              <div className="assign-feeds-toolbar">
                <label className="assign-feeds-search">
                  <Search size={14} />
                  <input
                    type="text"
                    value={feedAssignQuery}
                    onChange={(e) => setFeedAssignQuery(e.target.value)}
                    placeholder="Filter feeds by name, URL, or category"
                    disabled={isSaving}
                  />
                </label>

                <div className="assign-feeds-actions">
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={selectAllVisibleFeeds}
                    disabled={isSaving || visibleAssignableFeeds.length === 0 || allVisibleSelected}
                    style={{ padding: '8px 10px', fontSize: '0.78rem' }}
                  >
                    Select visible
                  </button>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={clearVisibleFeeds}
                    disabled={isSaving || visibleSelectedCount === 0}
                    style={{ padding: '8px 10px', fontSize: '0.78rem' }}
                  >
                    Clear visible
                  </button>
                </div>
              </div>

              <div className="assign-feeds-list">
                {feeds.length === 0 ? (
                  <div style={{ color: 'var(--text-light)', fontSize: '0.85rem' }}>
                    No feeds yet. Add feeds first, then attach them to events.
                  </div>
                ) : visibleAssignableFeeds.length === 0 ? (
                  <div className="admin-empty-state" style={{ padding: '16px 10px' }}>
                    <div className="admin-empty-state-icon" style={{ width: 36, height: 36 }}>
                      <Search size={16} />
                    </div>
                    <strong>No matching feeds</strong>
                    <span>Try a different search term in this assignment box.</span>
                  </div>
                ) : (
                  visibleAssignableFeeds.map((feed) => {
                    const feedId = Number(feed.id);
                    const isSelected = draft.feed_ids.includes(feedId);
                    const eventCount = (feedEventsById.get(feedId) || []).length;
                    return (
                      <label
                        key={feed.id}
                        className={`assign-feed-item ${isSelected ? 'selected' : ''}`}
                      >
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleFeed(feed.id)}
                          disabled={isSaving}
                        />
                        <div className="assign-feed-copy">
                          <div className="assign-feed-topline">
                            <strong className="assign-feed-name">{feed.name || feed.url}</strong>
                            <span className={`panel-chip ${feed.enabled ? 'success' : 'muted'}`}>
                              {feed.enabled ? 'Enabled' : 'Disabled'}
                            </span>
                          </div>
                          <div className="assign-feed-url">{feed.url}</div>
                          <div className="assign-feed-meta">
                            <span>{feed.source_type || 'rss'}</span>
                            {feed.category ? <span>{feed.category}</span> : null}
                            <span>{eventCount} event{eventCount === 1 ? '' : 's'}</span>
                          </div>
                        </div>
                      </label>
                    );
                  })
                )}
              </div>
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

            {pagedEvents.map((event, index) => {
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

          {visibleEvents.length > 0 && (
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
                Showing {(safePage - 1) * PAGE_SIZE + 1}-{Math.min(safePage * PAGE_SIZE, visibleEvents.length)} of {visibleEvents.length}
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
