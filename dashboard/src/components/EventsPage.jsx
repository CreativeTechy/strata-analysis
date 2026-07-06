import React, { useEffect, useMemo, useState } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { motion } from 'framer-motion';
import ConfirmModal from './ConfirmModal';
import {
  CalendarDays,
  Eye,
  Plus,
  Check,
  X,
  Search,
  Flag,
  Clock3,
  Layers3,
  Link2,
  RefreshCw,
  Sparkles,
} from 'lucide-react';

const emptyDraft = {
  name: '',
  status: 'draft',
  description: '',
  location: '',
  target_audience: '',
  usernames: '',
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
  return [
    ...new Set(
      String(value || '')
        .split(/[\n,]/)
        .map((item) => item.trim())
        .filter(Boolean)
    ),
  ];
}

function normalizeDraftForCompare(value) {
  return {
    name: String(value?.name || '').trim(),
    status: String(value?.status || 'draft').trim().toLowerCase(),
    description: String(value?.description || '').trim(),
    location: String(value?.location || '').trim(),
    target_audience: String(value?.target_audience || '').trim(),
    usernames: String(value?.usernames || '').trim(),
    hashtags: String(value?.hashtags || '').trim(),
    keywords: String(value?.keywords || '').trim(),
    start_date: String(value?.start_date || ''),
    end_date: String(value?.end_date || ''),
    feed_ids: Array.isArray(value?.feed_ids)
      ? [...new Set(value.feed_ids.map((item) => Number(item)).filter((item) => Number.isFinite(item)))].sort((a, b) => a - b)
      : [],
  };
}

export default function EventsPage({
  events = [],
  feeds = [],
  onCreateEvent,
  onUpdateEvent,
  isLoadingEvents,
}) {
  const location = useLocation();
  const navigate = useNavigate();
  const params = useParams();
  const pathname = location.pathname;
  const isCreateRoute = pathname.endsWith('/new');
  const isEditRoute = pathname.endsWith('/edit');
  const isFormRoute = isCreateRoute || isEditRoute;
  const editingId = isEditRoute ? Number(params.eventId) : null;
  const currentEvent = useMemo(
    () => (editingId != null ? events.find((event) => Number(event.id) === Number(editingId)) || null : null),
    [editingId, events]
  );

  const [draft, setDraft] = useState(emptyDraft);
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [isSaving, setIsSaving] = useState(false);
  const [lastDiscovery, setLastDiscovery] = useState(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [feedAssignQuery, setFeedAssignQuery] = useState('');
  const [initialDraft, setInitialDraft] = useState(emptyDraft);
  const [showCancelModal, setShowCancelModal] = useState(false);
  const [wizardStep, setWizardStep] = useState(1);
  const [fillMode, setFillMode] = useState('');
  const [isGeneratingMetadata, setIsGeneratingMetadata] = useState(false);
  const [isDiscoveringFeeds, setIsDiscoveringFeeds] = useState(false);
  const [metadataError, setMetadataError] = useState('');

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
      const hashtagNames = (event.hashtags || []).map((value) => String(value).trim()).filter(Boolean);
      const keywordNames = (event.keywords || []).map((value) => String(value).trim()).filter(Boolean);
      const usernameNames = (event.usernames || []).map((value) => String(value).trim()).filter(Boolean);
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
          ...usernameNames,
        ]
          .filter(Boolean)
          .some((value) => String(value).toLowerCase().includes(needle));
      const matchesStatus = statusFilter === 'all' || (event.status || 'draft').toLowerCase() === statusFilter;
      return matchesQuery && matchesStatus;
    });
  }, [events, query, statusFilter]);

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
    if (!isFormRoute) {
      setDraft(emptyDraft);
      setLastDiscovery(null);
      setInitialDraft(emptyDraft);
      setShowCancelModal(false);
      setWizardStep(1);
      setFillMode('');
      setIsGeneratingMetadata(false);
      setMetadataError('');
      return;
    }

    if (isEditRoute) {
      if (!currentEvent) {
        setDraft(emptyDraft);
        setInitialDraft(emptyDraft);
        return;
      }

      setDraft({
        name: currentEvent.name || '',
        status: currentEvent.status || 'draft',
        description: currentEvent.description || '',
        location: currentEvent.location || '',
        target_audience: currentEvent.target_audience || '',
        usernames: toListInput(currentEvent.usernames),
        hashtags: toListInput(currentEvent.hashtags),
        keywords: toListInput(currentEvent.keywords),
        start_date: toDateInput(currentEvent.start_date),
        end_date: toDateInput(currentEvent.end_date),
        feed_ids: Array.isArray(currentEvent.feed_ids) ? currentEvent.feed_ids.map(Number) : [],
      });
      setFeedAssignQuery('');
      setLastDiscovery(null);
      setInitialDraft({
        name: currentEvent.name || '',
        status: currentEvent.status || 'draft',
        description: currentEvent.description || '',
        location: currentEvent.location || '',
        target_audience: currentEvent.target_audience || '',
        usernames: toListInput(currentEvent.usernames),
        hashtags: toListInput(currentEvent.hashtags),
        keywords: toListInput(currentEvent.keywords),
        start_date: toDateInput(currentEvent.start_date),
        end_date: toDateInput(currentEvent.end_date),
        feed_ids: Array.isArray(currentEvent.feed_ids) ? currentEvent.feed_ids.map(Number) : [],
      });
      return;
    }

    setDraft(emptyDraft);
    setFeedAssignQuery('');
    setLastDiscovery(null);
    setInitialDraft(emptyDraft);
    setWizardStep(1);
    setFillMode('');
    setIsGeneratingMetadata(false);
    setMetadataError('');
  }, [currentEvent, isEditRoute, isFormRoute]);

  const discardChanges = () => {
    setShowCancelModal(false);
    setFeedAssignQuery('');
    setDraft(emptyDraft);
    setLastDiscovery(null);
    navigate('/events');
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
      feed_ids: Array.from(new Set([...prev.feed_ids, ...visibleAssignableFeeds.map((feed) => Number(feed.id))])),
    }));
  };

  const clearVisibleFeeds = () => {
    const visibleIds = new Set(visibleAssignableFeeds.map((feed) => Number(feed.id)));
    setDraft((prev) => ({
      ...prev,
      feed_ids: prev.feed_ids.filter((id) => !visibleIds.has(Number(id))),
    }));
  };

  const generateMetadataFromAi = async () => {
    const name = draft.name.trim();
    const description = draft.description.trim();
    if (!name || !description || isGeneratingMetadata) return;

    setIsGeneratingMetadata(true);
    setMetadataError('');
    try {
      const res = await fetch('/api/events/suggest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, description }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data?.error) {
        throw new Error(data?.detail || data?.error || `Failed to generate event metadata (${res.status})`);
      }

      const suggestions = data?.suggestions || {};
      setDraft((prev) => ({
        ...prev,
        target_audience: suggestions.target_audience || prev.target_audience,
        usernames: Array.isArray(suggestions.usernames) ? suggestions.usernames.join(', ') : prev.usernames,
        hashtags: Array.isArray(suggestions.hashtags) ? suggestions.hashtags.join(', ') : prev.hashtags,
        keywords: Array.isArray(suggestions.keywords) ? suggestions.keywords.join(', ') : prev.keywords,
      }));
      return suggestions;
    } catch (error) {
      setMetadataError(error?.message || 'Failed to generate AI suggestions.');
      throw error;
    } finally {
      setIsGeneratingMetadata(false);
    }
  };

  const discoverFeedsFromDraft = async (nextDraft = draft) => {
    const payload = {
      name: nextDraft.name.trim(),
      description: nextDraft.description.trim(),
      location: nextDraft.location.trim(),
      target_audience: nextDraft.target_audience.trim(),
      usernames: parseListInput(nextDraft.usernames),
      hashtags: parseListInput(nextDraft.hashtags),
      keywords: parseListInput(nextDraft.keywords),
      feed_ids: Array.isArray(nextDraft.feed_ids) ? nextDraft.feed_ids : [],
    };

    if (!payload.name) return null;

    setIsDiscoveringFeeds(true);
    setMetadataError('');
    try {
      const res = await fetch('/api/events/discover', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data?.error) {
        throw new Error(data?.detail || data?.error || `Failed to discover feeds (${res.status})`);
      }

      const discovery = data?.discovery || {};
      const discoveredFeedIds = Array.isArray(discovery.feed_ids)
        ? [...new Set(discovery.feed_ids.map((value) => Number(value)).filter((value) => Number.isFinite(value)))]
        : [];
      if (discoveredFeedIds.length) {
        setDraft((prev) => ({
          ...prev,
          feed_ids: Array.from(new Set([...prev.feed_ids, ...discoveredFeedIds])),
        }));
      }
      setLastDiscovery(discovery);
      return discovery;
    } catch (error) {
      setMetadataError(error?.message || 'Failed to prefill feeds.');
      return null;
    } finally {
      setIsDiscoveringFeeds(false);
    }
  };

  const chooseManualFill = () => {
    setMetadataError('');
    setFillMode('manual');
    setWizardStep(2);
  };

  const chooseAiFill = async () => {
    setFillMode('ai');
    setWizardStep(2);
    try {
      await generateMetadataFromAi();
    } catch {
      // The UI already stores the error state for the user.
    }
  };

  const submit = async () => {
    if (isSaving) return;

    const payload = {
      name: draft.name.trim(),
      status: draft.status,
      description: draft.description.trim(),
      location: draft.location.trim(),
      target_audience: draft.target_audience.trim(),
      usernames: parseListInput(draft.usernames),
      hashtags: parseListInput(draft.hashtags),
      keywords: parseListInput(draft.keywords),
      start_date: draft.start_date || null,
      end_date: draft.end_date || null,
      feed_ids: draft.feed_ids,
    };

    if (!payload.name) return;

    setIsSaving(true);
    try {
      if (editingId) {
        await onUpdateEvent?.(editingId, payload);
      } else {
        await onCreateEvent?.(payload);
        setLastDiscovery(null);
      }
      if (editingId) {
        navigate(`/events/${editingId}`);
      } else {
        navigate('/events');
      }
    } finally {
      setIsSaving(false);
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

  if (isCreateRoute) {
    const step1Complete = draft.name.trim() && draft.description.trim();
    const step2Complete = fillMode === 'manual' || fillMode === 'ai';
    const canContinueFromStep2 = step2Complete && !isGeneratingMetadata;

    return (
      <div className="admin-page-shell">
        <div className="admin-page-header">
          <div>
            <div className="admin-page-kicker">
              <CalendarDays size={14} /> Event planner
            </div>
            <h1 className="admin-page-title">Create Event</h1>
            <p className="admin-page-subtitle">
              Build the event in three steps. Start with the basics, choose how to fill metadata, then review feeds and create the workspace.
            </p>
          </div>
          <div className="admin-page-toolbar">
            <div className="admin-page-toolbar-meta">
              <span>Step</span>
              <strong>{wizardStep} of 3</strong>
            </div>
            <div className="admin-page-toolbar-meta">
              <span>Mode</span>
              <strong>{fillMode ? fillMode.toUpperCase() : 'Choose one'}</strong>
            </div>
          </div>
        </div>

        <div className="glass-card" style={{ maxWidth: 1080, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 10 }}>
            {[
              { label: 'Event basics', detail: 'Name and description' },
              { label: 'Metadata', detail: 'Manual or AI fill' },
              { label: 'Create', detail: 'Review and generate feeds' },
            ].map((item, index) => {
              const step = index + 1;
              const active = wizardStep === step;
              const done = wizardStep > step;
              return (
                <button
                  key={item.label}
                  type="button"
                  onClick={() => {
                    if (step === 1 || (step === 2 && step1Complete) || (step === 3 && step1Complete && step2Complete)) {
                      setWizardStep(step);
                    }
                  }}
                  className="btn-secondary"
                  style={{
                    justifyContent: 'flex-start',
                    padding: '14px 16px',
                    borderColor: active ? 'rgba(46, 134, 222, 0.28)' : 'rgba(0,0,0,0.08)',
                    background: active ? 'rgba(46, 134, 222, 0.08)' : 'rgba(255,255,255,0.72)',
                  }}
                >
                  <span className="panel-chip" style={{ marginRight: 10 }}>
                    {done ? 'Done' : `0${step}`}
                  </span>
                  <span style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 2 }}>
                    <strong style={{ fontSize: '0.92rem' }}>{item.label}</strong>
                    <span style={{ fontSize: '0.74rem', color: 'var(--text-light)', textTransform: 'none', letterSpacing: 0 }}>
                      {item.detail}
                    </span>
                  </span>
                </button>
              );
            })}
          </div>

          {wizardStep === 1 && (
          <div className="glass-card" style={{ padding: 18, boxShadow: 'none', background: 'rgba(255,255,255,0.55)' }}>
            <div className="panel-header-tight" style={{ marginBottom: 12 }}>
              <strong style={{ fontSize: '1rem' }}>Step 1. Event basics</strong>
              <span className="panel-chip">{step1Complete ? 'Ready' : 'Required'}</span>
            </div>
            <div style={{ display: 'grid', gap: 10 }}>
              <label style={{ display: 'grid', gap: 6 }}>
                <span style={{ fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-light)' }}>Event name</span>
                <input
                  type="text"
                  className="feed-input"
                  placeholder="Event name"
                  value={draft.name}
                  onChange={(e) => setDraft((prev) => ({ ...prev, name: e.target.value }))}
                  disabled={isSaving}
                />
              </label>
              <label style={{ display: 'grid', gap: 6 }}>
                <span style={{ fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-light)' }}>Description</span>
                <textarea
                  className="feed-input"
                  placeholder="Event description"
                  rows={4}
                  value={draft.description}
                  onChange={(e) => setDraft((prev) => ({ ...prev, description: e.target.value }))}
                  style={{ resize: 'vertical', minHeight: 110 }}
                  disabled={isSaving}
                />
              </label>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap' }}>
                <span style={{ color: 'var(--text-light)', fontSize: '0.85rem', lineHeight: 1.5 }}>
                  Use a clear working title and a short description. We’ll use these to seed the AI suggestions and feed discovery.
                </span>
                <button
                  type="button"
                  className="btn-primary"
                  onClick={() => setWizardStep(2)}
                  disabled={!step1Complete || isSaving}
                  style={{ minWidth: 180 }}
                >
                  Continue
                </button>
              </div>
            </div>
          </div>
          )}

          {wizardStep === 2 && (
          <div
            className="glass-card"
            style={{
              padding: 18,
              boxShadow: 'none',
              background: 'rgba(255,255,255,0.55)',
              opacity: step1Complete ? 1 : 0.7,
            }}
          >
            <div className="panel-header-tight" style={{ marginBottom: 12 }}>
              <strong style={{ fontSize: '1rem' }}>Step 2. Metadata fill</strong>
              <span className="panel-chip">{fillMode ? fillMode.toUpperCase() : 'Choose a method'}</span>
            </div>

            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 12 }}>
              <button
                type="button"
                className={`btn-secondary ${fillMode === 'manual' ? 'active' : ''}`}
                onClick={chooseManualFill}
                disabled={!step1Complete || isSaving}
              >
                Fill manually
              </button>
              <button
                type="button"
                className={`btn-secondary ${fillMode === 'ai' ? 'active' : ''}`}
                onClick={chooseAiFill}
                disabled={!step1Complete || isSaving || isGeneratingMetadata}
              >
                {isGeneratingMetadata ? 'Generating with AI...' : 'Fill by AI'}
              </button>
            </div>

            {!step2Complete ? (
              <div className="admin-empty-state" style={{ padding: '16px 10px' }}>
                <div className="admin-empty-state-icon">
                  <Sparkles size={18} />
                </div>
                <strong>Choose a fill method</strong>
                <span>AI will draft usernames, hashtags, keywords, and a target audience. Manual mode lets you enter them yourself.</span>
              </div>
            ) : (
              <div style={{ display: 'grid', gap: 12 }}>
                {metadataError && (
                  <div
                    style={{
                      padding: '12px 14px',
                      borderRadius: 14,
                      background: 'rgba(255, 71, 87, 0.08)',
                      border: '1px solid rgba(255, 71, 87, 0.16)',
                      color: '#b42318',
                      fontSize: '0.84rem',
                      lineHeight: 1.5,
                    }}
                  >
                    {metadataError}
                  </div>
                )}

                <div style={{ display: 'grid', gap: 8 }}>
                  <label style={{ fontSize: '0.82rem', color: 'var(--text-light)' }}>Target audience</label>
                  <input
                    type="text"
                    className="feed-input"
                    placeholder="Target audience"
                    value={draft.target_audience}
                    onChange={(e) => setDraft((prev) => ({ ...prev, target_audience: e.target.value }))}
                    disabled={isSaving || isGeneratingMetadata}
                  />
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 10 }}>
                  <div style={{ display: 'grid', gap: 8 }}>
                    <label style={{ fontSize: '0.82rem', color: 'var(--text-light)' }}>Usernames</label>
                    <textarea
                      className="feed-input"
                      placeholder="Usernames, comma or newline separated"
                      rows={4}
                      value={draft.usernames}
                      onChange={(e) => setDraft((prev) => ({ ...prev, usernames: e.target.value }))}
                      style={{ resize: 'vertical', minHeight: 108 }}
                      disabled={isSaving || isGeneratingMetadata}
                    />
                  </div>
                  <div style={{ display: 'grid', gap: 8 }}>
                    <label style={{ fontSize: '0.82rem', color: 'var(--text-light)' }}>Hashtags</label>
                    <textarea
                      className="feed-input"
                      placeholder="Hashtags, comma or newline separated"
                      rows={4}
                      value={draft.hashtags}
                      onChange={(e) => setDraft((prev) => ({ ...prev, hashtags: e.target.value }))}
                      style={{ resize: 'vertical', minHeight: 108 }}
                      disabled={isSaving || isGeneratingMetadata}
                    />
                  </div>
                  <div style={{ display: 'grid', gap: 8 }}>
                    <label style={{ fontSize: '0.82rem', color: 'var(--text-light)' }}>Keywords</label>
                    <textarea
                      className="feed-input"
                      placeholder="Keywords, comma or newline separated"
                      rows={4}
                      value={draft.keywords}
                      onChange={(e) => setDraft((prev) => ({ ...prev, keywords: e.target.value }))}
                      style={{ resize: 'vertical', minHeight: 108 }}
                      disabled={isSaving || isGeneratingMetadata}
                    />
                  </div>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
                  <span style={{ color: 'var(--text-light)', fontSize: '0.85rem', lineHeight: 1.5, maxWidth: 480 }}>
                    The AI step gives you a starting point. You can still reshape handles, tags, and keywords before creating the event.
                  </span>
                  <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={() => setWizardStep(1)}
                      disabled={isSaving || isGeneratingMetadata}
                      style={{ minWidth: 120 }}
                    >
                      Back
                    </button>
                    <button
                      type="button"
                      className="btn-primary"
                      onClick={() => setWizardStep(3)}
                      disabled={!canContinueFromStep2 || isSaving}
                      style={{ minWidth: 180 }}
                    >
                      Continue
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
          )}

          {wizardStep === 3 && (
          <div
            className="glass-card"
            style={{
              padding: 18,
              boxShadow: 'none',
              background: 'rgba(255,255,255,0.55)',
              opacity: step1Complete && step2Complete ? 1 : 0.7,
            }}
          >
            <div className="panel-header-tight" style={{ marginBottom: 12 }}>
              <strong style={{ fontSize: '1rem' }}>Step 3. Review and create</strong>
              <span className="panel-chip">{selectedFeedCount} selected feeds</span>
            </div>

            <div style={{ display: 'grid', gap: 14 }}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                <label style={{ display: 'grid', gap: 6 }}>
                  <span style={{ fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-light)' }}>Status</span>
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
                </label>
                <label style={{ display: 'grid', gap: 6 }}>
                  <span style={{ fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-light)' }}>Location</span>
                  <input
                    type="text"
                    className="feed-input"
                    placeholder="Location"
                    value={draft.location}
                    onChange={(e) => setDraft((prev) => ({ ...prev, location: e.target.value }))}
                    disabled={isSaving}
                  />
                </label>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                <label style={{ display: 'grid', gap: 6 }}>
                  <span style={{ fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-light)' }}>Start date</span>
                  <input
                    type="date"
                    className="feed-input"
                    value={draft.start_date}
                    onChange={(e) => setDraft((prev) => ({ ...prev, start_date: e.target.value }))}
                    disabled={isSaving}
                  />
                </label>
                <label style={{ display: 'grid', gap: 6 }}>
                  <span style={{ fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-light)' }}>End date</span>
                  <input
                    type="date"
                    className="feed-input"
                    value={draft.end_date}
                    onChange={(e) => setDraft((prev) => ({ ...prev, end_date: e.target.value }))}
                    disabled={isSaving}
                  />
                </label>
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
                        <label key={feed.id} className={`assign-feed-item ${isSelected ? 'selected' : ''}`}>
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
                              <span>
                                {eventCount} event{eventCount === 1 ? '' : 's'}
                              </span>
                            </div>
                          </div>
                        </label>
                      );
                    })
                  )}
                </div>
              </div>

              {metadataError && (
                <div
                  style={{
                    padding: '12px 14px',
                    borderRadius: 14,
                    background: 'rgba(255, 71, 87, 0.08)',
                    border: '1px solid rgba(255, 71, 87, 0.16)',
                    color: '#b42318',
                    fontSize: '0.84rem',
                    lineHeight: 1.5,
                  }}
                >
                  {metadataError}
                </div>
              )}

              <div className="admin-form-hint">
                Use AI to prefill feeds from the final usernames, hashtags, and keywords, then create the event row.
              </div>

              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                <button className="btn-secondary" type="button" onClick={() => setWizardStep(2)} disabled={isSaving} style={{ flexShrink: 0 }}>
                  Back
                </button>
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => discoverFeedsFromDraft()}
                  disabled={!step1Complete || !step2Complete || isSaving || isDiscoveringFeeds || isGeneratingMetadata}
                  style={{ flex: 1, minWidth: 220 }}
                >
                  {isDiscoveringFeeds ? (
                    <>
                      <RefreshCw size={18} className="spin" /> Prefilling feeds...
                    </>
                  ) : (
                    <>
                      <Sparkles size={18} /> Prefill feeds with AI
                    </>
                  )}
                </button>
                <button className="btn-primary" onClick={submit} style={{ flex: 1, minWidth: 220 }} disabled={isSaving || !step1Complete}>
                  {isSaving ? (
                    <>
                      <RefreshCw size={18} className="spin" />
                      Saving...
                    </>
                  ) : (
                    <>
                      <Plus size={18} /> Create Event
                    </>
                  )}
                </button>
                <button className="btn-secondary" type="button" onClick={handleCancel} style={{ flexShrink: 0 }}>
                  <X size={18} /> Cancel
                </button>
              </div>
            </div>
          </div>
          )}
        </div>

        <ConfirmModal
          open={showCancelModal}
          title="Discard changes?"
          message="You have unsaved changes on this event. If you cancel now, all edits on this page will be lost."
          confirmLabel="Discard changes"
          cancelLabel="Keep editing"
          onClose={() => setShowCancelModal(false)}
          onConfirm={discardChanges}
        />
      </div>
    );
  }

  if (isFormRoute) {
    const heading = isEditRoute ? 'Edit Event' : 'Create Event';
    return (
      <div className="admin-page-shell">
        <div className="admin-page-header">
          <div>
            <div className="admin-page-kicker">
              <CalendarDays size={14} /> Event planner
            </div>
            <h1 className="admin-page-title">{heading}</h1>
            <p className="admin-page-subtitle">
              {isEditRoute
                ? 'Update the event envelope, then keep the linked feeds and discovery terms in sync.'
                : 'Create a new event scope, attach feeds, and let discovery suggest sources from usernames, hashtags, and keywords.'}
            </p>
          </div>
          <div className="admin-page-toolbar">
            <div className="admin-page-toolbar-meta">
              <span>Mode</span>
              <strong>{isEditRoute ? 'Editing' : 'Creating'}</strong>
            </div>
            <div className="admin-page-toolbar-meta">
              <span>Feeds</span>
              <strong>{selectedFeedCount.toLocaleString()}</strong>
            </div>
          </div>
        </div>

        <div className="glass-card admin-form-panel" style={{ maxWidth: 980, margin: '0 auto' }}>
          <div className="panel-header-tight">
            <strong style={{ fontSize: '1rem' }}>{heading}</strong>
            <span className="panel-chip">{isEditRoute ? 'Updating existing scope' : 'Create a fresh scope'}</span>
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
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 10 }}>
            <textarea
              className="feed-input"
              placeholder="Usernames, comma or newline separated"
              rows={3}
              value={draft.usernames}
              onChange={(e) => setDraft((prev) => ({ ...prev, usernames: e.target.value }))}
              style={{ resize: 'vertical', minHeight: 92 }}
              disabled={isSaving}
            />
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
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <label style={{ display: 'grid', gap: 6 }}>
              <span style={{ fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-light)' }}>Status</span>
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
            </label>
            <label style={{ display: 'grid', gap: 6 }}>
              <span style={{ fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-light)' }}>Location</span>
              <input
                type="text"
                className="feed-input"
                placeholder="Location"
                value={draft.location}
                onChange={(e) => setDraft((prev) => ({ ...prev, location: e.target.value }))}
                disabled={isSaving}
              />
            </label>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <label style={{ display: 'grid', gap: 6 }}>
              <span style={{ fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-light)' }}>Start date</span>
              <input
                type="date"
                className="feed-input"
                value={draft.start_date}
                onChange={(e) => setDraft((prev) => ({ ...prev, start_date: e.target.value }))}
                disabled={isSaving}
              />
            </label>
            <label style={{ display: 'grid', gap: 6 }}>
              <span style={{ fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-light)' }}>End date</span>
              <input
                type="date"
                className="feed-input"
                value={draft.end_date}
                onChange={(e) => setDraft((prev) => ({ ...prev, end_date: e.target.value }))}
                disabled={isSaving}
              />
            </label>
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
                    <label key={feed.id} className={`assign-feed-item ${isSelected ? 'selected' : ''}`}>
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
                          <span>
                            {eventCount} event{eventCount === 1 ? '' : 's'}
                          </span>
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
            {isSaving && (draft.usernames.trim() || draft.hashtags.trim() || draft.keywords.trim()) ? ' Finding feeds from your usernames, hashtags, and keywords...' : ''}
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
                  No valid URLs were resolved from the usernames, hashtags, and keywords for this save.
                </div>
              )}
            </div>
          )}

          <div style={{ display: 'flex', gap: 10, marginTop: 12, flexWrap: 'wrap' }}>
            <button className="btn-secondary" type="button" onClick={() => setWizardStep(2)} disabled={isSaving} style={{ flexShrink: 0 }}>
              Back
            </button>
            <button className="btn-primary" onClick={() => submit()} style={{ flex: 1, minWidth: 220 }} disabled={isSaving || isDiscoveringFeeds}>
              {isSaving ? (
                <>
                  <RefreshCw size={18} className="spin" /> Saving...
                </>
              ) : (
                <>
                  <Plus size={18} /> {isEditRoute ? 'Update Event' : 'Create Event'}
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
          message="You have unsaved changes on this event. If you cancel now, all edits on this page will be lost."
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
            <span>Search</span>
            <strong>{visibleEvents.length.toLocaleString()} matches</strong>
          </div>
          <Link to="/events/new" className="btn-primary" style={{ textDecoration: 'none' }}>
            <Plus size={16} /> Add Event
          </Link>
        </div>
      </div>

      <div className="admin-stats-grid">
        <div className="admin-stat-card">
          <div className="admin-stat-icon">
            <Layers3 size={18} />
          </div>
          <div>
            <span>Total events</span>
            <strong>{stats.total.toLocaleString()}</strong>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon" style={{ background: 'rgba(46, 213, 115, 0.12)', color: '#2ed573' }}>
            <Flag size={18} />
          </div>
          <div>
            <span>Active</span>
            <strong>{stats.active.toLocaleString()}</strong>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon" style={{ background: 'rgba(255, 159, 67, 0.14)', color: 'var(--primary-color)' }}>
            <Clock3 size={18} />
          </div>
          <div>
            <span>Draft</span>
            <strong>{stats.draftCount.toLocaleString()}</strong>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon" style={{ background: 'rgba(116, 125, 140, 0.14)', color: '#747d8c' }}>
            <Link2 size={18} />
          </div>
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
              <div className="admin-empty-state-icon">
                <CalendarDays size={18} />
              </div>
              <strong>No events yet</strong>
              <span>Start by creating an event, then assign feeds and run the scraper against that scope.</span>
              <Link to="/events/new" className="btn-primary" style={{ marginTop: 8, textDecoration: 'none' }}>
                <Plus size={16} /> Add Event
              </Link>
            </div>
          )}

          {pagedEvents.map((event, index) => {
            const assignedFeedCount = Array.isArray(event.feed_ids) ? event.feed_ids.length : 0;
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
                      <span>
                        {assignedFeedCount} feed{assignedFeedCount === 1 ? '' : 's'}
                      </span>
                    </div>
                    <div style={{ marginTop: 10, color: 'var(--text-light)', fontSize: '0.88rem', lineHeight: 1.5 }}>
                      {event.description || 'Open the event to see assigned feeds, tags, and metadata.'}
                    </div>
                  </div>

                  <div className="admin-item-actions">
                    <Link
                      className="btn-secondary"
                      to={`/events/${event.id}`}
                      style={{ padding: '8px 10px', fontSize: '0.8rem', textDecoration: 'none' }}
                    >
                      <Eye size={14} /> View
                    </Link>
                  </div>
                </div>
              </motion.div>
            );
          })}

          {!isLoadingEvents && visibleEvents.length === 0 && events.length > 0 && (
            <div className="admin-empty-state">
              <div className="admin-empty-state-icon">
                <Search size={18} />
              </div>
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
  );
}
