import React, { useState, useEffect, useMemo, useRef } from 'react';
import { Link } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { useAuth } from '../auth/useAuth.js';
import {
  Globe,
  AtSign,
  Share2,
  Link2,
  Type,
  Plus,
  ArrowRight,
  DownloadCloud,
  Sparkles,
  Database,
  CheckCircle2,
  RefreshCw,
  Clock3,
  Flag,
  ShieldCheck,
  Layers3,
  BadgeCheck,
  FileText,
  TrendingUp,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Square,
} from 'lucide-react';
import '../styles/Workflow.css';

const PlatformIcon = ({ platform }) => {
  if (platform === 'web') return <Globe size={18} />;
  if (platform === 'x') return <AtSign size={18} />;
  if (platform === 'facebook') return <Share2 size={18} />;
  return <Globe size={18} />;
};

const TypeIcon = ({ type }) => {
  if (type === 'link') return <Link2 size={18} />;
  if (type === 'keywords') return <Type size={18} />;
  return <Link2 size={18} />;
};

function prettyStage(stage) {
  if (!stage) return 'queued';
  if (stage === 'done') return 'completed';
  return stage;
}

function statusTone(status) {
  if (status === 'success') return 'success';
  if (status === 'failed') return 'danger';
  if (status === 'running') return 'warning';
  return 'muted';
}

export default function WorkflowPage({
  articles = [],
  isScraping = false,
  onRunScraper,
  sources = [],
  events = [],
  selectedEvents = [],
  selectedEventIds = [],
  onChangeSelectedEventIds = () => {},
  activeRun = null,
  onStopRun = () => {},
}) {
  const { hasRole } = useAuth();
  const canRunScraper = hasRole('operator');

  const seedRows = (list) =>
    (list.length ? list : []).map((url, i) => ({
      id: i + 1,
      platform: 'web',
      type: 'link',
      value: url,
    }));

  const [rows, setRows] = useState(() => seedRows(sources));
  const [runs, setRuns] = useState([]);
  const [runsLoading, setRunsLoading] = useState(false);
  const [runsError, setRunsError] = useState('');
  const [workflowStartedAt, setWorkflowStartedAt] = useState(null);
  const [workflowElapsed, setWorkflowElapsed] = useState(0);
  const [isSourceListCollapsed, setIsSourceListCollapsed] = useState(false);
  const [isStopping, setIsStopping] = useState(false);
  const wasScrapingRef = useRef(false);

  const handleStopRun = async () => {
    if (!activeRun?.id) return;
    setIsStopping(true);
    try {
      await onStopRun(activeRun.id);
    } catch (error) {
      console.error('Failed to stop pipeline run:', error);
    } finally {
      setIsStopping(false);
    }
  };

  useEffect(() => {
    if (sources.length) setRows(seedRows(sources));
  }, [sources]);

  useEffect(() => {
    if (isScraping && !wasScrapingRef.current) {
      setWorkflowStartedAt(Date.now());
      setWorkflowElapsed(0);
    }

    if (!isScraping && wasScrapingRef.current && workflowStartedAt) {
      setWorkflowElapsed((Date.now() - workflowStartedAt) / 1000);
    }

    wasScrapingRef.current = isScraping;
  }, [isScraping, workflowStartedAt]);

  useEffect(() => {
    if (!isScraping || !workflowStartedAt) return undefined;

    const timer = setInterval(() => {
      setWorkflowElapsed((Date.now() - workflowStartedAt) / 1000);
    }, 200);

    return () => clearInterval(timer);
  }, [isScraping, workflowStartedAt]);

  useEffect(() => {
    let alive = true;
    const loadRuns = async () => {
      setRunsLoading(true);
      setRunsError('');
      try {
        const res = await fetch('/api/pipeline-runs?limit=6');
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data?.error || `Failed to load pipeline runs (${res.status})`);
        if (alive) setRuns(Array.isArray(data?.runs) ? data.runs : []);
      } catch (error) {
        if (alive) {
          setRuns([]);
          setRunsError(error?.message || 'Failed to load pipeline runs.');
        }
      } finally {
        if (alive) setRunsLoading(false);
      }
    };
    loadRuns();
    const interval = isScraping ? setInterval(loadRuns, 3000) : null;
    return () => {
      alive = false;
      if (interval) clearInterval(interval);
    };
  }, [isScraping]);

  const hasData = articles.length > 0;
  const workflowState = isScraping ? 'cleaning' : (hasData ? 'ready' : 'idle');
  const selectedEventCount = selectedEventIds.length;
  const eventLabel = useMemo(() => {
    if (selectedEvents.length === 0) return events.length ? 'select one or more events' : 'no events available';
    if (selectedEvents.length === 1) return selectedEvents[0].name || '1 event';
    return `${selectedEvents.length} selected events`;
  }, [events.length, selectedEvents]);
  const selectedEventNames = useMemo(
    () => selectedEvents.map((event) => event.name).filter(Boolean).slice(0, 4),
    [selectedEvents]
  );
  const hasMultipleEvents = events.length > 1;

  const formatMatchScore = (value) => {
    const score = Number(value);
    if (!Number.isFinite(score)) return '';
    return score.toFixed(2);
  };

  const stats = useMemo(() => {
    const total = articles.length;
    const positive = articles.filter((a) => (a.sentiment || '').toLowerCase() === 'positive').length;
    const negative = articles.filter((a) => (a.sentiment || '').toLowerCase() === 'negative').length;
    const neutral = articles.filter((a) => (a.sentiment || '').toLowerCase() === 'neutral' || !a.sentiment).length;
    const sources = new Set(articles.map((a) => a.source).filter(Boolean)).size;
    const avg = total
      ? (articles.reduce((s, a) => s + (Number(a.relevance_score) || 0), 0) / total).toFixed(1)
      : '0.0';
    const topSources = Object.entries(
      articles.reduce((acc, a) => {
        if (!a.source) return acc;
        acc[a.source] = (acc[a.source] || 0) + 1;
        return acc;
      }, {})
    )
      .sort((a, b) => b[1] - a[1])
      .slice(0, 4)
      .map(([source, count]) => ({ source, count }));

    return { total, positive, negative, neutral, sources, avg, topSources };
  }, [articles]);

  const latestArticles = useMemo(
    () => [...articles].filter((a) => a?.title || a?.source).slice(0, 5),
    [articles]
  );

  const currentRun = runs[0] || null;
  const completedRuns = runs.slice(1);
  const pipelineStats = useMemo(() => ({
    pages: Number(currentRun?.crawl_pages) || 0,
    scraped: Number(currentRun?.articles_scraped) || 0,
    cleaned: Number(currentRun?.articles_cleaned) || 0,
    saved: Number(currentRun?.articles_saved) || 0,
  }), [currentRun]);

  const formatWhen = (value) => {
    if (!value) return 'just now';
    try {
      return new Date(value).toLocaleString();
    } catch {
      return String(value);
    }
  };

  const formatElapsed = (seconds) => {
    const total = Math.max(0, Math.floor(seconds || 0));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const secs = total % 60;
    return [
      hours ? String(hours).padStart(2, '0') : null,
      String(minutes).padStart(2, '0'),
      String(secs).padStart(2, '0'),
    ].filter(Boolean).join(':');
  };

  const updateRow = (id, field, value) => {
    setRows(rows.map((r) => (r.id === id ? { ...r, [field]: value } : r)));
  };

  const cleanupProgressLabel = useMemo(() => {
    const scraped = Math.max(0, Number(currentRun?.articles_scraped) || 0);
    const cleaned = Math.max(0, Number(currentRun?.articles_cleaned) || 0);
    const saved = Math.max(0, Number(currentRun?.articles_saved) || 0);
    if (!currentRun) return '';
    if ((currentRun.status || '').toLowerCase() !== 'running') {
      if ((currentRun.stage || '').toLowerCase() === 'done') {
        return scraped > 0 ? `Enriched ${Math.min(cleaned || scraped, scraped)}/${scraped} articles` : 'Pipeline complete';
      }
      return currentRun.message || '';
    }
    if ((currentRun.stage || '').toLowerCase() === 'enrich') {
      if (scraped > 0) return `Cleaning articles ${Math.min(Math.max(cleaned, 0), scraped)}/${scraped}`;
      return 'Cleaning articles...';
    }
    if ((currentRun.stage || '').toLowerCase() === 'scrape') {
      return scraped > 0 ? `Scraping sources ${Math.max(1, currentRun.crawl_pages || 0)} pages / ${scraped} articles` : 'Scraping sources...';
    }
    if ((currentRun.stage || '').toLowerCase() === 'done') {
      return saved > 0 ? `Saved ${saved} articles` : 'Pipeline complete';
    }
    return currentRun.message || '';
  }, [currentRun]);

  const toggleSelectedEvent = (eventId) => {
    const id = Number(eventId);
    if (!Number.isFinite(id)) return;

    const isSelected = selectedEventIds.includes(id);
    if (isSelected && selectedEventIds.length === 1) {
      return;
    }

    const nextIds = isSelected
      ? selectedEventIds.filter((value) => Number(value) !== id)
      : [...selectedEventIds, id];
    onChangeSelectedEventIds([...new Set(nextIds)]);
  };

  const selectAllEvents = () => {
    onChangeSelectedEventIds([...new Set(events.map((event) => Number(event.id)).filter((id) => Number.isFinite(id)))]);
  };

  const runLabel = selectedEventCount > 1
    ? `Run Extractor for ${selectedEventCount} Events`
    : selectedEventCount === 1
      ? 'Run Extractor for Event'
      : 'Select Events to Run';

  return (
    <div className="workflow-layout">
      <div className="bg-pattern"></div>

      <div className="workflow-shell">
        <motion.div
          className="workflow-panel glass-card"
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          style={{ marginBottom: '18px' }}
        >
          <div className="panel-header" style={{ marginBottom: 0 }}>
            <div>
              <div className="panel-kicker"><Clock3 size={14} /> Live stopwatch</div>
              <h2>Workflow elapsed time</h2>
              <div style={{ color: 'var(--text-light)', fontSize: '0.85rem', marginTop: 6 }}>
                Running scope: {eventLabel}
              </div>
            </div>
            <span className={`panel-pill ${isScraping ? 'warning' : workflowStartedAt ? 'success' : 'neutral'}`}>
              {isScraping ? 'running' : workflowStartedAt ? 'stopped' : 'idle'}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '12px', flexWrap: 'wrap' }}>
            <div style={{ fontSize: '2.4rem', fontWeight: 800, letterSpacing: '-0.04em', color: 'var(--text-dark)' }}>
              {workflowStartedAt ? formatElapsed(workflowElapsed) : '00:00'}
            </div>
            <div style={{ color: 'var(--text-light)', fontSize: '0.9rem' }}>
              {isScraping
                ? 'Timer is counting while the extractor runs.'
                : workflowStartedAt
                  ? `Last run started at ${formatWhen(workflowStartedAt)}.`
                  : 'Start the extractor to begin timing the workflow.'}
            </div>
          </div>
        </motion.div>

        <div className="workflow-main-grid">
          <div className="miro-board">
            <motion.div
              className="workflow-block"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
            >
              <div className="miro-badge top-right">
                <Sparkles size={14} /> Sources
              </div>

              <div className="block-header">
                <div className="block-icon get">
                  <DownloadCloud size={20} />
                </div>
                <div className="block-title">Get Data</div>
              </div>

              <div className="workflow-event-picker">
                <div className="workflow-event-picker-header">
                  <div>
                    <div className="workflow-event-picker-kicker">Scope</div>
                    <strong>Choose one or more events to extract</strong>
                  </div>
                  <div className="workflow-event-picker-summary">
                    <span className="panel-chip">{selectedEventCount} selected</span>
                    <span className="panel-chip muted">{events.length} total</span>
                  </div>
                </div>

                <div className="workflow-event-picker-note">
                  The extractor will run once for each selected event, then the results below will merge the latest articles into a single view.
                </div>

                {events.length === 0 ? (
                  <div className="panel-empty" style={{ marginTop: 8 }}>
                    <ShieldCheck size={16} />
                    <span>No events yet. Create an event first, then come back to run the workflow.</span>
                  </div>
                ) : (
                  <>
                    <div className="workflow-event-picker-actions">
                      <button
                        type="button"
                        className="btn-secondary"
                        onClick={selectAllEvents}
                        disabled={!hasMultipleEvents || selectedEventCount === events.length}
                        style={{ padding: '8px 10px', fontSize: '0.78rem' }}
                      >
                        Select all
                      </button>
                    </div>

                    <div className="workflow-event-list">
                      {events.map((event) => {
                        const isSelected = selectedEventIds.includes(Number(event.id));
                        return (
                          <label key={event.id} className={`workflow-event-item ${isSelected ? 'selected' : ''}`}>
                            <input
                              type="checkbox"
                              checked={isSelected}
                              onChange={() => toggleSelectedEvent(event.id)}
                              disabled={isScraping}
                            />
                            <div className="workflow-event-copy">
                              <div className="workflow-event-topline">
                                <strong>{event.name}</strong>
                                <span className={`panel-chip ${isSelected ? 'success' : 'muted'}`}>
                                  {isSelected ? 'Selected' : 'Unselected'}
                                </span>
                              </div>
                              <div className="workflow-event-meta">
                                <span>{event.status || 'draft'}</span>
                                {event.location ? <span>{event.location}</span> : null}
                                {(event.source_ids || []).length ? <span>{event.source_ids.length} source{event.source_ids.length === 1 ? '' : 's'}</span> : <span>No sources</span>}
                              </div>
                            </div>
                          </label>
                        );
                      })}
                    </div>
                  </>
                )}
              </div>

              {selectedEventNames.length ? (
                <div className="workflow-event-pills">
                  {selectedEventNames.map((name) => (
                    <span key={name} className="workflow-event-pill">{name}</span>
                  ))}
                  {selectedEvents.length > selectedEventNames.length ? (
                    <span className="workflow-event-pill muted">+{selectedEvents.length - selectedEventNames.length} more</span>
                  ) : null}
                </div>
              ) : null}

              <div className="get-rows-header">
                <div className="get-rows-header-copy">
                  <strong>Sources</strong>
                  <span>Paste URLs here or switch a row to keywords</span>
                </div>
                <button
                  type="button"
                  className="workflow-event-toggle"
                  onClick={() => setIsSourceListCollapsed((current) => !current)}
                  aria-expanded={!isSourceListCollapsed}
                  aria-controls="workflow-source-list"
                >
                  {isSourceListCollapsed ? (
                    <>
                      Expand sources <ChevronDown size={14} />
                    </>
                  ) : (
                    <>
                      Collapse sources <ChevronUp size={14} />
                    </>
                  )}
                </button>
              </div>

              <AnimatePresence initial={false}>
                {!isSourceListCollapsed ? (
                  <motion.div
                    key="workflow-source-list"
                    id="workflow-source-list"
                    className="get-rows"
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: 'auto' }}
                    exit={{ opacity: 0, height: 0 }}
                    transition={{ duration: 0.2 }}
                  >
                    {rows.map((row) => (
                      <motion.div
                        key={row.id}
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: 'auto' }}
                        exit={{ opacity: 0, height: 0 }}
                        className="get-row"
                      >
                        <div style={{ position: 'relative', width: '24px', height: '24px', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                          <div style={{ position: 'absolute', pointerEvents: 'none', color: 'var(--text-light)' }}>
                            <PlatformIcon platform={row.platform} />
                          </div>
                          <select
                            value={row.platform}
                            onChange={(e) => updateRow(row.id, 'platform', e.target.value)}
                            style={{ opacity: 0, width: '100%', height: '100%', cursor: 'pointer', position: 'absolute', left: 0, top: 0 }}
                          >
                            <option value="web">Web RSS</option>
                            <option value="x">X (Twitter)</option>
                            <option value="facebook">Facebook</option>
                          </select>
                        </div>

                        <div className="row-input-wrapper">
                          <input
                            type="text"
                            className="row-input"
                            placeholder={row.type === 'link' ? 'Paste URL...' : 'Enter keywords...'}
                            value={row.value}
                            onChange={(e) => updateRow(row.id, 'value', e.target.value)}
                          />
                        </div>

                        <div style={{ position: 'relative', width: '24px', height: '24px', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                          <div style={{ position: 'absolute', pointerEvents: 'none', color: 'var(--text-light)' }}>
                            <TypeIcon type={row.type} />
                          </div>
                          <select
                            value={row.type}
                            onChange={(e) => updateRow(row.id, 'type', e.target.value)}
                            style={{ opacity: 0, width: '100%', height: '100%', cursor: 'pointer', position: 'absolute', left: 0, top: 0 }}
                          >
                            <option value="link">Link</option>
                            <option value="keywords">Keywords</option>
                          </select>
                        </div>
                      </motion.div>
                    ))}
                  </motion.div>
                ) : (
                  <motion.div
                    key="workflow-source-list-collapsed"
                    className="workflow-event-list-collapsed"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                  >
                    Source URLs are collapsed. Expand them to edit or review the source list.
                  </motion.div>
                )}
              </AnimatePresence>

              <Link
                to="/sources"
                className="add-row-btn"
                style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px', textDecoration: 'none' }}
              >
                <Plus size={18} /> Add Source
              </Link>

              <div style={{ display: 'flex', gap: '10px', marginTop: '15px' }}>
                <button
                  className="btn-primary"
                  style={{ opacity: isScraping ? 0.7 : 1, flex: 1 }}
                  onClick={() => onRunScraper?.(selectedEventIds)}
                  disabled={isScraping || selectedEventCount === 0 || !canRunScraper}
                  title={canRunScraper ? undefined : 'Requires the operator or admin role.'}
                >
                  {isScraping ? (
                    <><RefreshCw size={16} className="spin" /> Running...</>
                  ) : (
                    runLabel
                  )}
                </button>

                {activeRun ? (
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={handleStopRun}
                    disabled={isStopping || !canRunScraper}
                    title={canRunScraper ? undefined : 'Requires the operator or admin role.'}
                  >
                    {isStopping ? (
                      <><RefreshCw size={16} className="spin" /> Stopping...</>
                    ) : (
                      <><Square size={16} /> Stop</>
                    )}
                  </button>
                ) : null}
              </div>
            </motion.div>

            <div className="workflow-arrow">
              <ArrowRight size={32} />
            </div>

            <motion.div
              className="workflow-block"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1 }}
              style={{ opacity: workflowState === 'idle' ? 0.5 : 1 }}
            >
              <div className="miro-badge bottom-left" style={{ color: 'var(--primary-color)' }}>
                <RefreshCw size={14} /> {isScraping ? 'Pipeline Running' : 'Pipeline Active'}
              </div>

              <div className="block-header">
                <div className="block-icon clean">
                  <Sparkles size={20} />
                </div>
                <div className="block-title">Cleanup & Enrich</div>
              </div>

              <div className="cleanup-status">
                {cleanupProgressLabel ? (
                  <div className="cleanup-progress">
                    {cleanupProgressLabel}
                  </div>
                ) : null}

                {workflowState === 'idle' && (
                  <div style={{ textAlign: 'center', color: 'var(--text-light)' }}>
                    Waiting for extraction...
                  </div>
                )}

                {(workflowState === 'cleaning' || workflowState === 'ready') && (
                  <>
                    {['Parsing raw content', 'Validating AI JSON output', 'Extracting structured article insights'].map((label, i) => (
                      <motion.div
                        key={label}
                        className="status-item"
                        initial={{ opacity: 0, x: -20 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: i * 0.35 }}
                      >
                        <div className="status-spinner">
                          {workflowState === 'cleaning'
                            ? <RefreshCw size={18} className="spin" />
                            : <CheckCircle2 size={18} color="#2ed573" />}
                        </div>
                        <div className="status-text">{label}</div>
                      </motion.div>
                    ))}
                    {isScraping && (
                      <p style={{ fontSize: '0.72rem', color: 'var(--text-light)', marginTop: '10px', textAlign: 'center' }}>
                        Running on GitHub Actions - new rows land in about 3 minutes.
                      </p>
                    )}
                  </>
                )}
              </div>
            </motion.div>

            <div className="workflow-arrow">
              <ArrowRight size={32} />
            </div>

            <motion.div
              className="workflow-block"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.2 }}
              style={{ opacity: workflowState === 'idle' ? 0.5 : 1 }}
            >
              <div className="block-header">
                <div className="block-icon save">
                  <Database size={20} />
                </div>
                <div className="block-title">Save & Store</div>
              </div>

              <div className="save-summary">
                {!hasData ? (
                  <div style={{ textAlign: 'center', color: 'var(--text-light)' }}>
                    Awaiting enriched data...
                  </div>
                ) : (
                  <>
                    <div className="summary-stat">
                      <span className="summary-label">Total Rows Stored</span>
                      <span className="summary-value">{stats.total} Rows</span>
                    </div>
                    <div className="summary-stat">
                      <span className="summary-label">Positive Sentiment</span>
                      <span className="summary-value" style={{ color: '#2ed573' }}>{stats.positive} Articles</span>
                    </div>
                    <div className="summary-stat">
                      <span className="summary-label">Negative Sentiment</span>
                      <span className="summary-value" style={{ color: '#ff6b6b' }}>{stats.negative} Articles</span>
                    </div>
                    <div className="summary-stat">
                      <span className="summary-label">Neutral Sentiment</span>
                      <span className="summary-value" style={{ color: '#9aa0aa' }}>{stats.neutral} Articles</span>
                    </div>
                    <div className="summary-stat">
                      <span className="summary-label">Unique Sources</span>
                      <span className="summary-value" style={{ color: 'var(--secondary-color)' }}>{stats.sources} Found</span>
                    </div>
                    <div className="summary-stat">
                      <span className="summary-label">Average Relevance</span>
                      <span className="summary-value" style={{ color: 'var(--primary-color)' }}>{stats.avg} / 10</span>
                    </div>

                    <div className="save-btn" style={{ cursor: 'default', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px' }}>
                      <CheckCircle2 size={18} /> Synced to Supabase
                    </div>
                  </>
                )}
              </div>
            </motion.div>
          </div>
        </div>

        <div className="workflow-bottom-grid">
          <motion.div
            className="workflow-panel glass-card"
            initial={{ opacity: 0, y: 18 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
          >
              <div className="panel-header">
                <div>
                  <div className="panel-kicker"><Clock3 size={14} /> Run log</div>
                  <h2>Latest pipeline activity</h2>
                </div>
                <span className={`panel-pill ${statusTone(currentRun?.status)}`}>
                  {currentRun ? currentRun.status : 'idle'}
                </span>
              </div>

              {runsError ? (
                <div className="panel-empty danger">
                  <AlertTriangle size={16} />
                  <span>{runsError}</span>
                </div>
              ) : null}

              <div className="log-list">
                {runsLoading ? (
                  Array.from({ length: 4 }).map((_, i) => (
                    <div key={i} className="log-item skeleton">
                      <div className="log-dot"></div>
                      <div className="log-copy">
                        <div className="skeleton-line short"></div>
                        <div className="skeleton-line"></div>
                      </div>
                    </div>
                  ))
                ) : currentRun ? (
                  <>
                    <div className="log-item active">
                      <div className="log-dot"></div>
                      <div className="log-copy">
                        <div className="log-title">Current run</div>
                        <div className="log-body">{currentRun.message || 'Pipeline in progress.'}</div>
                        <div className="log-meta">
                          <span>{prettyStage(currentRun.stage)}</span>
                          <span>{currentRun.status}</span>
                          <span>{formatWhen(currentRun.created_at)}</span>
                        </div>
                      </div>
                    </div>

                    {completedRuns.map((run) => (
                      <div key={run.id} className="log-item">
                        <div className={`log-dot ${run.status || ''}`}></div>
                        <div className="log-copy">
                          <div className="log-title">{prettyStage(run.stage)}</div>
                          <div className="log-body">{run.message || 'No message'}</div>
                          <div className="log-meta">
                            <span>{run.status || 'queued'}</span>
                            <span>{formatWhen(run.finished_at || run.created_at)}</span>
                          </div>
                        </div>
                      </div>
                    ))}
                  </>
                ) : (
                  <div className="panel-empty">
                    <ShieldCheck size={16} />
                    <span>No pipeline runs yet. Launch the extractor to generate activity.</span>
                  </div>
                )}
              </div>
          </motion.div>

          <motion.div
            className="workflow-panel glass-card"
            initial={{ opacity: 0, y: 18 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.15 }}
          >
              <div className="panel-header">
                <div>
                  <div className="panel-kicker"><TrendingUp size={14} /> Results</div>
                  <h2>Current output snapshot</h2>
                </div>
                <span className={`panel-pill ${statusTone(currentRun?.status || (isScraping ? 'running' : 'success'))}`}>
                  {currentRun ? currentRun.status : (isScraping ? 'running' : 'live')}
                </span>
              </div>

              <div className="result-grid">
                <div className="result-card">
                  <FileText size={16} />
                  <span className="result-label">Pages Crawled</span>
                  <strong>{pipelineStats.pages.toLocaleString()}</strong>
                </div>
                <div className="result-card">
                  <Layers3 size={16} />
                  <span className="result-label">Articles Scraped</span>
                  <strong>{pipelineStats.scraped.toLocaleString()}</strong>
                </div>
                <div className="result-card">
                  <BadgeCheck size={16} />
                  <span className="result-label">Cleaned</span>
                  <strong>{pipelineStats.cleaned.toLocaleString()}</strong>
                </div>
                <div className="result-card">
                  <Flag size={16} />
                  <span className="result-label">Saved</span>
                  <strong>{pipelineStats.saved.toLocaleString()}</strong>
                </div>
              </div>

              <div className="source-mini-list" style={{ marginTop: '16px' }}>
                <div className="mini-list-title">Live article quality</div>
                <div className="mini-list-row">
                  <span>Positive</span>
                  <strong style={{ color: '#2ed573' }}>{stats.positive.toLocaleString()}</strong>
                </div>
                <div className="mini-list-row">
                  <span>Negative</span>
                  <strong style={{ color: '#ff6b6b' }}>{stats.negative.toLocaleString()}</strong>
                </div>
                <div className="mini-list-row">
                  <span>Neutral</span>
                  <strong style={{ color: '#9aa0aa' }}>{stats.neutral.toLocaleString()}</strong>
                </div>
                <div className="mini-list-row">
                  <span>Unique Sources</span>
                  <strong style={{ color: 'var(--secondary-color)' }}>{stats.sources.toLocaleString()}</strong>
                </div>
                <div className="mini-list-row">
                  <span>Average Relevance</span>
                  <strong style={{ color: 'var(--primary-color)' }}>{stats.avg} / 10</strong>
                </div>
              </div>

              <div className="source-mini-list">
                <div className="mini-list-title">Top sources</div>
                {stats.topSources.length ? (
                  stats.topSources.map((item) => (
                    <div key={item.source} className="mini-list-row">
                      <span>{item.source}</span>
                      <strong>{item.count}</strong>
                    </div>
                  ))
                ) : (
                  <div className="mini-empty">No sources yet.</div>
                )}
              </div>

              <div className="article-preview-list">
                <div className="mini-list-title">Recent articles</div>
                {latestArticles.length ? (
                  latestArticles.map((article) => (
                    <div key={article.url} className="article-preview-row">
                    <div className="article-preview-top">
                      <span className="article-preview-source">{article.source || 'Unknown source'}</span>
                      <span className={`badge ${article.sentiment?.toLowerCase() || 'neutral'}`}>
                        {article.sentiment || 'Neutral'}
                      </span>
                      {article.event_similarity_score != null && (
                        <span className="badge score">Match {formatMatchScore(article.event_similarity_score)}</span>
                      )}
                    </div>
                      <div className="article-preview-title">{article.title || article.url}</div>
                      <div style={{ fontSize: '0.72rem', color: 'var(--text-light)', marginTop: 4 }}>
                        {article.article_category || article.category || 'general_article'}
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="mini-empty">No recent articles to preview.</div>
                )}
              </div>
          </motion.div>
        </div>
      </div>
    </div>
  );
}
