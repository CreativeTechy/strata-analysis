import { useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { motion } from 'framer-motion';
import ConfirmModal from './ConfirmModal';
import {
  ArrowLeft,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  Hash,
  Link2,
  MapPin,
  AtSign,
  Tag,
  Pencil,
  Trash2,
} from 'lucide-react';

const FEEDS_PAGE_SIZE = 3;

function formatDate(value) {
  if (!value) return 'Not set';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return parsed.toLocaleDateString();
}

function normalizeList(value) {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item || '').trim()).filter(Boolean);
}

export default function EventDetailPage({
  events = [],
  feeds = [],
  onDeleteEvent,
}) {
  const navigate = useNavigate();
  const params = useParams();
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [feedsPage, setFeedsPage] = useState(1);

  const event = useMemo(
    () => events.find((item) => Number(item.id) === Number(params.eventId)) || null,
    [events, params.eventId]
  );

  const assignedFeeds = useMemo(() => {
    if (!event) return [];
    const feedIds = new Set((event.feed_ids || []).map((value) => Number(value)));
    return feeds.filter((feed) => feedIds.has(Number(feed.id)));
  }, [event, feeds]);

  const totalFeedsPages = Math.max(1, Math.ceil(assignedFeeds.length / FEEDS_PAGE_SIZE));
  const safeFeedsPage = Math.min(feedsPage, totalFeedsPages);
  const pagedAssignedFeeds = useMemo(() => {
    const start = (safeFeedsPage - 1) * FEEDS_PAGE_SIZE;
    return assignedFeeds.slice(start, start + FEEDS_PAGE_SIZE);
  }, [assignedFeeds, safeFeedsPage]);

  const hashtagList = normalizeList(event?.hashtags);
  const keywordList = normalizeList(event?.keywords);
  const usernameList = normalizeList(event?.usernames);

  const status = String(event?.status || 'draft').toLowerCase();
  const isActive = status === 'active';
  const isArchived = status === 'archived';
  const statusLabel = status.toUpperCase();

  if (!event) {
    return (
      <div className="admin-page-shell">
        <div className="glass-card" style={{ maxWidth: 760, margin: '0 auto' }}>
          <div className="admin-empty-state" style={{ padding: '34px 20px' }}>
            <div className="admin-empty-state-icon">
              <CalendarDays size={18} />
            </div>
            <strong>Event not found</strong>
            <span>The event may have been removed or the link is outdated.</span>
            <Link to="/events" className="btn-primary" style={{ marginTop: 8, textDecoration: 'none' }}>
              <ArrowLeft size={16} /> Back to Events
            </Link>
          </div>
        </div>
      </div>
    );
  }

  const handleDelete = async () => {
    if (!onDeleteEvent) return;
    await onDeleteEvent(event.id);
    navigate('/events');
  };

  return (
    <div className="admin-page-shell">
      <div className="admin-page-header">
        <div>
          <div className="admin-page-kicker">
            <CalendarDays size={14} /> Event details
          </div>
          <h1 className="admin-page-title">{event.name}</h1>
          <p className="admin-page-subtitle">
            Review the feeds, tags, and metadata attached to this event. This page is the best place to inspect the working scope before running the pipeline.
          </p>
        </div>

        <div className="admin-page-toolbar">
          <div className="admin-page-toolbar-meta">
            <span>Status</span>
            <strong>{statusLabel}</strong>
          </div>
          <div className="admin-page-toolbar-meta">
            <span>Assigned feeds</span>
            <strong>{assignedFeeds.length.toLocaleString()}</strong>
          </div>
          <Link to={`/events/${event.id}/edit`} className="btn-secondary" style={{ textDecoration: 'none' }}>
            <Pencil size={16} /> Edit Event
          </Link>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => setDeleteOpen(true)}
            style={{ color: '#ff4757' }}
          >
            <Trash2 size={16} /> Delete
          </button>
        </div>
      </div>

      <div className="event-detail-layout">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35 }}
          className="glass-card"
          style={{ display: 'flex', flexDirection: 'column', gap: 16 }}
        >
          <div className="panel-header-tight">
            <strong style={{ fontSize: '1rem' }}>Overview</strong>
            <span className={`panel-chip ${isActive ? 'success' : isArchived ? 'muted' : 'warning'}`}>{statusLabel}</span>
          </div>

          <div className="event-detail-summary-grid">
            <div className="admin-item-card" style={{ margin: 0 }}>
              <div className="admin-item-meta" style={{ marginBottom: 8 }}>
                <span><CalendarDays size={12} /> Start</span>
                <span><CalendarDays size={12} /> End</span>
              </div>
              <strong style={{ fontSize: '0.98rem' }}>{formatDate(event.start_date)}</strong>
              <div style={{ color: 'var(--text-light)', fontSize: '0.84rem', marginTop: 4 }}>{formatDate(event.end_date)}</div>
            </div>

            <div className="admin-item-card" style={{ margin: 0 }}>
              <div className="admin-item-meta" style={{ marginBottom: 8 }}>
                <span><MapPin size={12} /> Location</span>
                <span><Tag size={12} /> Audience</span>
              </div>
              <strong style={{ fontSize: '0.98rem' }}>{event.location || 'Not set'}</strong>
              <div style={{ color: 'var(--text-light)', fontSize: '0.84rem', marginTop: 4 }}>{event.target_audience || 'No audience specified'}</div>
            </div>
          </div>

          <div className="admin-item-card" style={{ margin: 0 }}>
            <div className="panel-header-tight" style={{ marginBottom: 10 }}>
              <strong style={{ fontSize: '0.94rem' }}>Description</strong>
            </div>
            <div style={{ color: 'var(--text-light)', lineHeight: 1.7, whiteSpace: 'pre-wrap' }}>
              {event.description || 'No description has been added for this event yet.'}
            </div>
          </div>

          <div className="admin-item-card" style={{ margin: 0 }}>
            <div className="panel-header-tight" style={{ marginBottom: 10 }}>
              <strong style={{ fontSize: '0.94rem' }}>Discovery Signals</strong>
            </div>
            <div style={{ display: 'grid', gap: 12 }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, color: 'var(--text-light)', fontSize: '0.8rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  <Hash size={14} /> Hashtags
                </div>
                <div className="admin-item-chips">
                  {hashtagList.length ? hashtagList.map((item) => (
                    <span key={item} className="admin-tag">{item}</span>
                  )) : <span className="admin-tag muted">No hashtags</span>}
                </div>
              </div>

              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, color: 'var(--text-light)', fontSize: '0.8rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  <AtSign size={14} /> Usernames
                </div>
                <div className="admin-item-chips">
                  {usernameList.length ? usernameList.map((item) => (
                    <span key={item} className="admin-tag muted">{item}</span>
                  )) : <span className="admin-tag muted">No usernames</span>}
                </div>
              </div>

              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, color: 'var(--text-light)', fontSize: '0.8rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  <Link2 size={14} /> Keywords
                </div>
                <div className="admin-item-chips">
                  {keywordList.length ? keywordList.map((item) => (
                    <span key={item} className="admin-tag muted">{item}</span>
                  )) : <span className="admin-tag muted">No keywords</span>}
                </div>
              </div>
            </div>
          </div>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, delay: 0.05 }}
          className="glass-card"
          style={{ display: 'flex', flexDirection: 'column', gap: 16 }}
        >
          <div className="panel-header-tight">
            <strong style={{ fontSize: '1rem' }}>Assigned Feeds</strong>
            <span className="panel-chip">{assignedFeeds.length} linked</span>
          </div>

          {assignedFeeds.length === 0 ? (
            <div className="admin-empty-state" style={{ padding: '20px 12px' }}>
              <div className="admin-empty-state-icon">
                <Link2 size={18} />
              </div>
              <strong>No feeds assigned</strong>
              <span>Use Edit Event to attach feeds to this event.</span>
            </div>
          ) : (
            <>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {pagedAssignedFeeds.map((feed) => (
                <div key={feed.id} className="admin-item-card" style={{ margin: 0 }}>
                  <div className="admin-item-top">
                    <div style={{ minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 6 }}>
                        <strong className="admin-item-title">{feed.name || feed.url}</strong>
                        <span className={`panel-chip ${feed.enabled ? 'success' : 'muted'}`}>
                          {feed.enabled ? 'Enabled' : 'Disabled'}
                        </span>
                      </div>
                      <div className="admin-item-url">{feed.url}</div>
                      <div className="admin-item-meta">
                        <span>{feed.source_type || 'rss'}</span>
                        {feed.category ? <span>{feed.category}</span> : null}
                      </div>
                    </div>
                  </div>
                </div>
                ))}
              </div>

              {assignedFeeds.length > FEEDS_PAGE_SIZE && (
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    gap: 12,
                    flexWrap: 'wrap',
                    paddingTop: 6,
                    borderTop: '1px solid rgba(15, 23, 42, 0.08)',
                  }}
                >
                  <div style={{ fontSize: '0.84rem', color: 'var(--text-light)' }}>
                    Showing {(safeFeedsPage - 1) * FEEDS_PAGE_SIZE + 1}-{Math.min(safeFeedsPage * FEEDS_PAGE_SIZE, assignedFeeds.length)} of {assignedFeeds.length}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={() => setFeedsPage((value) => Math.max(1, value - 1))}
                      disabled={safeFeedsPage <= 1}
                      style={{ padding: '8px 10px', fontSize: '0.8rem' }}
                    >
                      <ChevronLeft size={14} /> Previous
                    </button>
                    <span className="panel-chip">
                      Page {safeFeedsPage} of {totalFeedsPages}
                    </span>
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={() => setFeedsPage((value) => Math.min(totalFeedsPages, value + 1))}
                      disabled={safeFeedsPage >= totalFeedsPages}
                      style={{ padding: '8px 10px', fontSize: '0.8rem' }}
                    >
                      Next <ChevronRight size={14} />
                    </button>
                  </div>
                </div>
              )}
            </>
          )}

          <div className="admin-item-card" style={{ margin: 0 }}>
            <div className="panel-header-tight" style={{ marginBottom: 10 }}>
              <strong style={{ fontSize: '0.94rem' }}>Quick Facts</strong>
            </div>
            <div style={{ display: 'grid', gap: 10 }}>
              <div className="admin-item-meta">
                <span>Created {formatDate(event.created_at)}</span>
                <span>Updated {formatDate(event.updated_at)}</span>
              </div>
              <div className="admin-item-meta">
                <span>{assignedFeeds.length} linked feed{assignedFeeds.length === 1 ? '' : 's'}</span>
                <span>{hashtagList.length} hashtag{hashtagList.length === 1 ? '' : 's'}</span>
              </div>
            </div>
          </div>
        </motion.div>
      </div>

      <ConfirmModal
        open={deleteOpen}
        title={`Delete event "${event.name}"?`}
        message="This will permanently remove the event and detach it from any linked feeds."
        confirmLabel="Delete event"
        cancelLabel="Keep event"
        confirmButtonStyle={{
          background: 'linear-gradient(135deg, #ff4757, #e03131)',
          boxShadow: '0 4px 15px rgba(255, 71, 87, 0.28)',
        }}
        onClose={() => setDeleteOpen(false)}
        onConfirm={handleDelete}
      />
    </div>
  );
}
