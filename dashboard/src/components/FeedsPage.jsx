import React, { useEffect, useMemo, useState } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { motion } from 'framer-motion';
import ConfirmModal from './ConfirmModal';
import {
  Rss,
  Plus,
  Pencil,
  Trash2,
  Check,
  X,
  ToggleLeft,
  ToggleRight,
  Search,
  Link2,
  CheckCircle2,
  Layers3,
} from 'lucide-react';

const emptyDraft = {
  url: '',
  name: '',
  source_type: 'rss',
  category: '',
  enabled: true,
  limited: false,
  event_ids: [],
};

const FEED_TYPE_OPTIONS = [
  { value: 'rss', label: 'RSS' },
  { value: 'web', label: 'Web' },
  { value: 'social', label: 'Social' },
  { value: 'hashtag', label: 'Hashtag' },
  { value: 'keyword', label: 'Keyword' },
  { value: 'username', label: 'Username' },
];

const TERM_FEED_TYPES = new Set(['hashtag', 'keyword', 'username']);

const TERM_FEED_PLACEHOLDERS = {
  hashtag: 'Hashtag, without # (e.g. EVSummit)',
  username: 'Username, without @ (e.g. elonmusk)',
  keyword: 'Keyword or phrase (e.g. electric vehicles)',
};

function feedTypeLabel(sourceType) {
  const match = FEED_TYPE_OPTIONS.find((option) => option.value === (sourceType || 'rss'));
  return match ? match.label : (sourceType || 'RSS');
}

const PAGE_SIZE = 3;

function normalizeDraftForCompare(value) {
  return {
    url: String(value?.url || '').trim(),
    name: String(value?.name || '').trim(),
    source_type: String(value?.source_type || 'rss').trim().toLowerCase(),
    category: String(value?.category || '').trim(),
    enabled: Boolean(value?.enabled),
    limited: Boolean(value?.limited),
    event_ids: Array.isArray(value?.event_ids)
      ? [...new Set(value.event_ids.map((item) => Number(item)).filter((item) => Number.isFinite(item)))].sort((a, b) => a - b)
      : [],
  };
}

export default function FeedsPage({
  feeds = [],
  events = [],
  feedsSource,
  onCreateFeed,
  onUpdateFeed,
  onDeleteFeed,
  isLoadingFeeds,
}) {
  const location = useLocation();
  const navigate = useNavigate();
  const params = useParams();
  const pathname = location.pathname;
  const isCreateRoute = pathname.endsWith('/new');
  const isEditRoute = pathname.endsWith('/edit');
  const isFormRoute = isCreateRoute || isEditRoute;
  const editingId = isEditRoute ? Number(params.feedId) : null;
  const currentFeed = useMemo(
    () => (editingId != null ? feeds.find((feed) => Number(feed.id) === Number(editingId)) || null : null),
    [editingId, feeds]
  );

  const [draft, setDraft] = useState(emptyDraft);
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [typeFilter, setTypeFilter] = useState('all');
  const [reachFilter, setReachFilter] = useState('all');
  const [currentPage, setCurrentPage] = useState(1);
  const [initialDraft, setInitialDraft] = useState(emptyDraft);
  const [showCancelModal, setShowCancelModal] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);

  useEffect(() => {
    if (!isFormRoute) {
      setDraft(emptyDraft);
      setInitialDraft(emptyDraft);
      setShowCancelModal(false);
      setDeleteTarget(null);
      return;
    }

    if (isEditRoute) {
      if (!currentFeed) {
        setDraft(emptyDraft);
        setInitialDraft(emptyDraft);
        return;
      }

      const assignedEventIds = events
        .filter((event) => Array.isArray(event.feed_ids) && event.feed_ids.map(Number).includes(Number(currentFeed.id)))
        .map((event) => Number(event.id));

      setDraft({
        url: currentFeed.url || '',
        name: currentFeed.name || '',
        source_type: currentFeed.source_type || 'rss',
        category: currentFeed.category || '',
        enabled: currentFeed.enabled ?? true,
        limited: currentFeed.limited ?? false,
        event_ids: assignedEventIds,
      });
      setInitialDraft({
        url: currentFeed.url || '',
        name: currentFeed.name || '',
        source_type: currentFeed.source_type || 'rss',
        category: currentFeed.category || '',
        enabled: currentFeed.enabled ?? true,
        limited: currentFeed.limited ?? false,
        event_ids: assignedEventIds,
      });
      return;
    }

    setDraft(emptyDraft);
    setInitialDraft(emptyDraft);
  }, [currentFeed, events, isEditRoute, isFormRoute]);

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
      const matchesType = typeFilter === 'all' || (feed.source_type || 'rss') === typeFilter;
      const matchesReach =
        reachFilter === 'all' ||
        (reachFilter === 'limited' && feed.limited) ||
        (reachFilter === 'global' && !feed.limited);
      return matchesQuery && matchesStatus && matchesType && matchesReach;
    });
  }, [feeds, feedEventsById, query, statusFilter, typeFilter, reachFilter]);

  const totalPages = Math.max(1, Math.ceil(visibleFeeds.length / PAGE_SIZE));
  const safePage = Math.min(currentPage, totalPages);
  const pagedFeeds = useMemo(() => {
    const start = (safePage - 1) * PAGE_SIZE;
    return visibleFeeds.slice(start, start + PAGE_SIZE);
  }, [visibleFeeds, safePage]);

  useEffect(() => {
    setCurrentPage(1);
  }, [query, statusFilter, typeFilter, reachFilter]);

  useEffect(() => {
    if (currentPage > totalPages) {
      setCurrentPage(totalPages);
    }
  }, [currentPage, totalPages]);

  const beginEdit = (feed) => {
    navigate(`/feeds/${feed.id}/edit`);
  };

  const discardChanges = () => {
    setShowCancelModal(false);
    setDraft(emptyDraft);
    navigate('/feeds');
  };

  const submit = async () => {
    const isTermType = TERM_FEED_TYPES.has(draft.source_type);
    const payload = {
      url: isTermType ? '' : draft.url.trim(),
      name: draft.name.trim(),
      source_type: draft.source_type,
      category: draft.category.trim(),
      enabled: Boolean(draft.enabled),
      limited: Boolean(draft.limited),
      event_ids: draft.event_ids,
    };

    if (isTermType ? !payload.name : !payload.url) return;

    if (editingId) {
      await onUpdateFeed?.(editingId, payload);
    } else {
      await onCreateFeed?.(payload);
    }

    navigate('/feeds');
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
    await onDeleteFeed?.(feed.id);
    if (editingId === feed.id) {
      navigate('/feeds');
    }
  };

  const isDirty = useMemo(() => {
    return JSON.stringify(normalizeDraftForCompare(draft)) !== JSON.stringify(normalizeDraftForCompare(initialDraft));
  }, [draft, initialDraft]);

  const handleCancel = () => {
    if (isDirty) {
      setShowCancelModal(true);
      return;
    }
    discardChanges();
  };

  if (isFormRoute) {
    const heading = isEditRoute ? 'Edit Feed' : 'Create Feed';
    const buttonLabel = isEditRoute ? 'Save Feed' : 'Create Feed';
    return (
      <div className="admin-page-shell">
        <div className="admin-page-header">
          <div>
            <div className="admin-page-kicker">
              <Rss size={14} /> Source library
            </div>
            <h1 className="admin-page-title">{heading}</h1>
            <p className="admin-page-subtitle">
              {isEditRoute
                ? 'Update a tracked source and keep its event assignments in sync.'
                : 'Add a new source, classify it, and assign it to the events it should power.'}
            </p>
          </div>
          <div className="admin-page-toolbar">
            <div className="admin-page-toolbar-meta">
              <span>Mode</span>
              <strong>{isEditRoute ? 'Editing' : 'Creating'}</strong>
            </div>
            <div className="admin-page-toolbar-meta">
              <span>Events</span>
              <strong>{draft.event_ids.length.toLocaleString()}</strong>
            </div>
          </div>
        </div>

        <div className="glass-card admin-form-panel" style={{ maxWidth: 860, margin: '0 auto' }}>
          <div className="panel-header-tight">
            <strong style={{ fontSize: '1rem' }}>{heading}</strong>
            <span className="panel-chip">{isEditRoute ? 'Updating existing source' : 'Create a new source'}</span>
          </div>

          {!TERM_FEED_TYPES.has(draft.source_type) && (
            <input
              type="text"
              className="feed-input"
              placeholder="Feed URL"
              value={draft.url}
              onChange={(e) => setDraft((prev) => ({ ...prev, url: e.target.value }))}
            />
          )}
          <input
            type="text"
            className="feed-input"
            placeholder={TERM_FEED_PLACEHOLDERS[draft.source_type] || 'Display name'}
            value={draft.name}
            onChange={(e) => setDraft((prev) => ({ ...prev, name: e.target.value }))}
          />
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <select
              className="filter-select"
              value={draft.source_type}
              onChange={(e) => setDraft((prev) => ({ ...prev, source_type: e.target.value }))}
            >
              {FEED_TYPE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <input
              type="text"
              className="feed-input"
              placeholder="Category"
              value={draft.category}
              onChange={(e) => setDraft((prev) => ({ ...prev, category: e.target.value }))}
            />
          </div>
          <div
            style={{
              padding: '14px 16px',
              borderRadius: 14,
              border: '1px solid rgba(15, 23, 42, 0.08)',
              background: 'rgba(255, 255, 255, 0.7)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 12,
              flexWrap: 'wrap',
            }}
          >
            <div style={{ minWidth: 0 }}>
              <strong style={{ display: 'block', fontSize: '0.9rem', color: 'var(--text-dark)' }}>Feed status</strong>
              <span style={{ display: 'block', marginTop: 4, fontSize: '0.82rem', color: 'var(--text-light)' }}>
                Disable this feed to keep it in the library without using it in pipelines.
              </span>
            </div>
            <button
              type="button"
              onClick={() => setDraft((prev) => ({ ...prev, enabled: !prev.enabled }))}
              className={`btn-secondary ${draft.enabled ? 'active' : ''}`}
              style={{
                minWidth: 160,
                justifyContent: 'center',
                background: draft.enabled ? 'rgba(46, 213, 115, 0.12)' : 'rgba(116, 125, 140, 0.12)',
                borderColor: draft.enabled ? 'rgba(46, 213, 115, 0.24)' : 'rgba(116, 125, 140, 0.16)',
                color: draft.enabled ? '#1e9e57' : '#5f6b7a',
              }}
            >
              {draft.enabled ? <ToggleRight size={18} /> : <ToggleLeft size={18} />}
              {draft.enabled ? 'Enabled' : 'Disabled'}
            </button>
          </div>

          <div
            style={{
              padding: '14px 16px',
              borderRadius: 14,
              border: '1px solid rgba(15, 23, 42, 0.08)',
              background: 'rgba(255, 255, 255, 0.7)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 12,
              flexWrap: 'wrap',
            }}
          >
            <div style={{ minWidth: 0 }}>
              <strong style={{ display: 'block', fontSize: '0.9rem', color: 'var(--text-dark)' }}>Feed reach</strong>
              <span style={{ display: 'block', marginTop: 4, fontSize: '0.82rem', color: 'var(--text-light)' }}>
                Limited feeds stay out of the assignable list on event create/edit pages unless already attached to that event.
              </span>
            </div>
            <button
              type="button"
              onClick={() => setDraft((prev) => ({ ...prev, limited: !prev.limited }))}
              className={`btn-secondary ${draft.limited ? 'active' : ''}`}
              style={{
                minWidth: 160,
                justifyContent: 'center',
                background: draft.limited ? 'rgba(255, 159, 67, 0.14)' : 'rgba(46, 134, 222, 0.1)',
                borderColor: draft.limited ? 'rgba(255, 159, 67, 0.28)' : 'rgba(46, 134, 222, 0.24)',
                color: draft.limited ? 'var(--primary-color)' : '#2e86de',
              }}
            >
              {draft.limited ? <ToggleLeft size={18} /> : <ToggleRight size={18} />}
              {draft.limited ? 'Limited' : 'Global'}
            </button>
          </div>

          <div style={{ padding: '8px 0 2px', fontSize: '0.86rem', color: 'var(--text-light)' }}>Assign to events</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 220, overflow: 'auto' }}>
            {events.length === 0 ? (
              <div style={{ color: 'var(--text-light)', fontSize: '0.85rem' }}>No events yet. Create an event first.</div>
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
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{event.name}</span>
                </label>
              ))
            )}
          </div>

          <div style={{ display: 'flex', gap: 10, marginTop: 12 }}>
            <button className="btn-primary" onClick={submit} style={{ flex: 1 }}>
              {editingId ? (
                <>
                  <Check size={18} /> {buttonLabel}
                </>
              ) : (
                <>
                  <Plus size={18} /> {buttonLabel}
                </>
              )}
            </button>
            <button className="btn-secondary" type="button" onClick={handleCancel} style={{ flexShrink: 0 }}>
              <X size={18} /> Cancel
            </button>
          </div>
        </div>

        <ConfirmModal
          open={showCancelModal}
          title="Discard changes?"
          message="You have unsaved changes on this feed. If you cancel now, all edits on this page will be lost."
          confirmLabel="Discard changes"
          cancelLabel="Keep editing"
          onClose={() => setShowCancelModal(false)}
          onConfirm={discardChanges}
        />

      </div>
    );
  }

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
            <span>Search</span>
            <strong>{visibleFeeds.length.toLocaleString()} matches</strong>
          </div>
          <Link to="/feeds/new" className="btn-primary" style={{ textDecoration: 'none' }}>
            <Plus size={16} /> Add Feed
          </Link>
        </div>
      </div>

      <div className="admin-stats-grid">
        <div className="admin-stat-card">
          <div className="admin-stat-icon">
            <Layers3 size={18} />
          </div>
          <div>
            <span>Total feeds</span>
            <strong>{stats.total.toLocaleString()}</strong>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon" style={{ background: 'rgba(46, 213, 115, 0.12)', color: '#2ed573' }}>
            <CheckCircle2 size={18} />
          </div>
          <div>
            <span>Enabled</span>
            <strong>{stats.enabled.toLocaleString()}</strong>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon" style={{ background: 'rgba(46, 134, 222, 0.12)', color: 'var(--secondary-color)' }}>
            <Link2 size={18} />
          </div>
          <div>
            <span>Assigned</span>
            <strong>{stats.assigned.toLocaleString()}</strong>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon" style={{ background: 'rgba(255, 159, 67, 0.14)', color: 'var(--primary-color)' }}>
            <Rss size={18} />
          </div>
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

        <select className="filter-select" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
          <option value="all">All types</option>
          {FEED_TYPE_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>

        <select className="filter-select" value={reachFilter} onChange={(e) => setReachFilter(e.target.value)}>
          <option value="all">Global &amp; limited</option>
          <option value="global">Global</option>
          <option value="limited">Limited</option>
        </select>
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
              <div className="admin-empty-state-icon">
                <Rss size={18} />
              </div>
              <strong>No feeds yet</strong>
              <span>Add your first source, then attach it to one or more events.</span>
              <Link to="/feeds/new" className="btn-primary" style={{ marginTop: 8, textDecoration: 'none' }}>
                <Plus size={16} /> Add Feed
              </Link>
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
                      {feed.limited && <span className="panel-chip warning">Limited</span>}
                    </div>
                    <div className="admin-item-url">{feed.url}</div>
                    <div className="admin-item-meta">
                      <span>{feedTypeLabel(feed.source_type)}</span>
                      {feed.category ? <span>{feed.category}</span> : null}
                      <span>
                        {feedEvents.length} event{feedEvents.length === 1 ? '' : 's'}
                      </span>
                    </div>
                  </div>

                  <div className="admin-item-actions">
                    <Link
                      className="btn-secondary"
                      to={`/feeds/${feed.id}/edit`}
                      style={{ padding: '8px 10px', fontSize: '0.8rem', textDecoration: 'none' }}
                    >
                      <Pencil size={14} /> Edit
                    </Link>
                    <button
                      className="btn-secondary"
                      onClick={() => setDeleteTarget(feed)}
                      style={{ padding: '8px 10px', fontSize: '0.8rem', color: '#ff4757' }}
                    >
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
              <div className="admin-empty-state-icon">
                <Search size={18} />
              </div>
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

        <ConfirmModal
          open={Boolean(deleteTarget)}
          title={`Delete feed "${deleteTarget?.name || deleteTarget?.url || ''}"?`}
          message="This will permanently remove the feed and detach it from any linked events."
          confirmLabel="Delete feed"
          cancelLabel="Keep feed"
          confirmButtonStyle={{
            background: 'linear-gradient(135deg, #ff4757, #e03131)',
            boxShadow: '0 4px 15px rgba(255, 71, 87, 0.28)',
          }}
          onClose={() => setDeleteTarget(null)}
          onConfirm={async () => {
            if (!deleteTarget) return;
            const target = deleteTarget;
            setDeleteTarget(null);
            await remove(target);
          }}
        />
      </div>
    </div>
  );
}
