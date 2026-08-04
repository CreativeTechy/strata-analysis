import { Fragment, useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  ArrowLeft,
  Database,
  Loader2,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  ShieldAlert,
  CircleAlert,
  CircleCheck,
  Rss,
  Filter,
  Save,
  Layers,
  ExternalLink,
} from 'lucide-react';

function prettyStage(stage) {
  if (!stage) return 'queued';
  if (stage === 'done') return 'completed';
  return stage;
}

function stageColor(status) {
  if (status === 'success') return '#2ed573';
  if (status === 'failed') return '#ff4757';
  if (status === 'running') return '#ffb13b';
  if (status === 'cancelled') return '#9aa0aa';
  return '#9aa0aa';
}

function formatDateTime(iso) {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleString();
}

function formatDuration(ms) {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return null;
  // Sub-second stages (cleaning is often just in-memory filtering) are real,
  // measured durations - round-tripping through whole seconds would show "0s".
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const totalSeconds = Math.round(ms / 1000);
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes < 60) return `${minutes}m ${seconds}s`;
  const hours = Math.floor(minutes / 60);
  const remMinutes = minutes % 60;
  return `${hours}h ${remMinutes}m`;
}

// Returns { text, inProgress } describing the span between two timestamps.
// Still in progress (endIso missing but startIso present) counts elapsed time against now.
function stageDuration(startIso, endIso) {
  if (!startIso) return { text: '—', inProgress: false };
  const start = new Date(startIso).getTime();
  if (!Number.isFinite(start)) return { text: '—', inProgress: false };
  const end = endIso ? new Date(endIso).getTime() : Date.now();
  const text = formatDuration(end - start);
  return { text: text || '—', inProgress: !endIso };
}

function projectNameForRun(run, projectsById) {
  if (!run) return '';
  if (run.project_name) return run.project_name;
  const project = projectsById.get(Number(run.project_id));
  if (project?.name) return project.name;
  return run.project_id != null ? `Project #${run.project_id}` : 'Unassigned';
}

const STAGE_ROWS = [
  { key: 'scrape', label: 'Scraping', startField: 'scrape_started_at', endField: 'scrape_finished_at', Icon: Rss },
  { key: 'clean', label: 'Cleaning', startField: 'clean_started_at', endField: 'clean_finished_at', Icon: Filter },
  { key: 'enrich', label: 'Enriching', startField: 'enrich_started_at', endField: 'enrich_finished_at', Icon: Layers },
];

const TOTAL_STATS = [
  { key: 'articles_scraped', label: 'Articles scraped', Icon: Rss, tint: 'rgba(255, 159, 67, 0.14)', color: 'var(--primary-color)' },
  { key: 'articles_cleaned', label: 'Articles cleaned', Icon: Filter, tint: 'rgba(46, 134, 222, 0.14)', color: '#2e86de' },
  { key: 'articles_saved', label: 'Articles saved', Icon: Save, tint: 'rgba(46, 213, 115, 0.14)', color: '#2ed573' },
  { key: 'crawl_pages', label: 'Pages crawled', Icon: Layers, tint: 'rgba(116, 125, 140, 0.14)', color: '#747d8c' },
];

// Anchor target for a source row: prefer the real configured URL recorded
// during this run's fetch diagnostics; fall back to the source name only
// when it happens to already be a URL (legacy rows predating source_url).
function sourceHref(row) {
  if (row.source_url) return row.source_url;
  if (typeof row.source === 'string' && /^https?:\/\//i.test(row.source)) return row.source;
  return null;
}

const SOURCE_COLUMNS = [
  { key: 'scraped', label: 'Scraped' },
  { key: 'duplicate', label: 'Duplicate' },
  { key: 'blocked', label: 'Blocked' },
  { key: 'date_filtered', label: 'Date filtered' },
  { key: 'kept', label: 'Kept' },
  { key: 'enriched', label: 'Enriched' },
  { key: 'saved', label: 'Saved' },
];

// A source's fetch-status badge, distinct from the "Blocked" column above
// (that one counts articles content_guard rejected AFTER a successful
// fetch - this is about whether the source's own page could be reached at
// all this run). See backend/services/pipeline/source_diagnostics.py.
function sourceStatusBadge(source) {
  if (source.network_blocked) {
    return { label: `Blocked (HTTP ${source.http_status ?? '?'})`, color: '#ff4757', Icon: ShieldAlert };
  }
  if (source.http_status) {
    return { label: `HTTP ${source.http_status}`, color: '#ff4757', Icon: CircleAlert };
  }
  if (source.fetch_note) {
    return { label: 'Issue', color: '#ffb13b', Icon: CircleAlert };
  }
  return { label: 'OK', color: '#2ed573', Icon: CircleCheck };
}

function StatusBadge({ status }) {
  const color = stageColor(status);
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        padding: '4px 12px',
        borderRadius: 999,
        background: `${color}1f`,
        color,
        fontWeight: 700,
        textTransform: 'uppercase',
        fontSize: '0.75rem',
        letterSpacing: '0.03em',
      }}
    >
      {status}
    </span>
  );
}

function SummaryField({ label, children }) {
  return (
    <div>
      <div style={{ fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--text-light)', marginBottom: 2 }}>
        {label}
      </div>
      <div style={{ fontSize: '0.9rem', color: 'var(--text-dark)', wordBreak: 'break-word' }}>{children}</div>
    </div>
  );
}

export default function PipelineRunDetailPage({ projects = [] }) {
  const { runId } = useParams();
  const [run, setRun] = useState(null);
  const [sources, setSources] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [expandedSources, setExpandedSources] = useState(() => new Set());

  const projectsById = useMemo(() => {
    const map = new Map();
    projects.forEach((project) => map.set(Number(project.id), project));
    return map;
  }, [projects]);

  useEffect(() => {
    if (!runId) return undefined;

    let cancelled = false;
    setLoading(true);
    setError('');
    setRun(null);
    setSources([]);

    fetch(`/api/pipeline-runs/${runId}`)
      .then(async (res) => {
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data?.detail || data?.error || `Failed to load run (${res.status})`);
        if (cancelled) return;
        setRun(data?.run || null);
        setSources(Array.isArray(data?.sources) ? data.sources : []);
      })
      .catch((err) => {
        if (!cancelled) setError(err?.message || 'Failed to load run details.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [runId]);

  const toggleSource = (key) => {
    setExpandedSources((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const total = run ? stageDuration(run.started_at, run.finished_at) : null;
  const projectName = projectNameForRun(run, projectsById);

  return (
    <div className="admin-page-shell">
      <div className="admin-page-header">
        <div>
          <div className="admin-page-kicker">
            <Database size={14} /> Pipeline history
          </div>
          <h1 className="admin-page-title">Pipeline Run Details</h1>
          {projectName ? <p className="admin-page-subtitle">{projectName}</p> : null}
        </div>
        <div className="admin-page-toolbar">
          <Link to="/pipeline-runs" className="btn-secondary" style={{ textDecoration: 'none' }}>
            <ArrowLeft size={16} /> Back to Pipeline Runs
          </Link>
        </div>
      </div>

      {loading ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-light)', padding: '24px 0' }}>
          <Loader2 size={18} className="spin" /> Loading run details...
        </div>
      ) : error ? (
        <div className="glass-card" style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#b42318', borderLeft: '4px solid #ff4757' }}>
          <AlertTriangle size={18} /> {error}
        </div>
      ) : !run ? null : (
        <>
          <div className="admin-stats-grid">
            {TOTAL_STATS.map(({ key, label, Icon, tint, color }) => (
              <div className="admin-stat-card" key={key}>
                <div className="admin-stat-icon" style={{ background: tint, color }}>
                  <Icon size={18} />
                </div>
                <div>
                  <span>{label}</span>
                  <strong>{(run[key] || 0).toLocaleString()}</strong>
                </div>
              </div>
            ))}
          </div>

          <div className="glass-card run-detail-summary-grid" style={{ marginBottom: 18 }}>
            <SummaryField label="Run ID">
              <code style={{ fontSize: '0.8rem' }}>{run.id}</code>
            </SummaryField>
            <SummaryField label="Project">{projectName}</SummaryField>
            <SummaryField label="Status">
              <StatusBadge status={run.status} />
            </SummaryField>
            <SummaryField label="Current stage">{prettyStage(run.stage)}</SummaryField>
            <SummaryField label="Started at">{formatDateTime(run.started_at)}</SummaryField>
            <SummaryField label="Finished at">{formatDateTime(run.finished_at)}</SummaryField>
            <SummaryField label="Total duration">
              {total.text}
              {total.inProgress ? ' (in progress)' : ''}
            </SummaryField>
            <SummaryField label="Message">{run.message || '—'}</SummaryField>
            {run.error ? <SummaryField label="Error">{run.error}</SummaryField> : null}
          </div>

          <div className="glass-card" style={{ marginBottom: 18 }}>
            <h3 className="run-detail-section-title">Per-stage timings</h3>
            {!run.has_detail ? (
              <div className="run-detail-fallback">
                Details unavailable for legacy run — this run finished before per-stage timing was tracked.
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {STAGE_ROWS.map(({ key, label, startField, endField, Icon }) => {
                  const duration = stageDuration(run[startField], run[endField]);
                  return (
                    <div
                      key={key}
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        padding: '10px 14px',
                        borderRadius: 12,
                        background: 'rgba(0,0,0,0.03)',
                      }}
                    >
                      <span style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.85rem', fontWeight: 600 }}>
                        <Icon size={15} style={{ color: 'var(--primary-color)' }} /> {label}
                      </span>
                      <span style={{ fontSize: '0.85rem', color: 'var(--text-light)', fontWeight: duration.inProgress ? 700 : 400 }}>
                        {duration.text}
                        {duration.inProgress ? ' (in progress)' : ''}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          <div className="glass-card">
            <h3 className="run-detail-section-title">Per-source breakdown</h3>
            {!run.has_detail ? (
              <div className="run-detail-fallback">
                Details unavailable for legacy run — this run finished before per-source stats were tracked.
              </div>
            ) : sources.length === 0 ? (
              <div className="run-detail-fallback">No per-source data recorded for this run yet.</div>
            ) : (
              <div className="table-scroll">
                <table className="run-detail-source-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
                  <thead>
                    <tr style={{ textAlign: 'left', background: 'var(--glass-bg)' }}>
                      <th style={{ padding: '8px 10px', width: 28 }} />
                      <th style={{ padding: '8px 10px' }}>Source</th>
                      <th style={{ padding: '8px 10px' }}>Fetch status</th>
                      {SOURCE_COLUMNS.map((col) => (
                        <th key={col.key} style={{ padding: '8px 10px', textAlign: 'right' }}>
                          {col.label}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {sources.map((row) => {
                      const key = row.source;
                      const isExpanded = expandedSources.has(key);
                      const badge = sourceStatusBadge(row);
                      const hasDetails = Boolean(row.fetch_note);
                      const href = sourceHref(row);
                      const showNameSeparately = href && row.source && row.source !== href;
                      return (
                        <Fragment key={key}>
                          <tr style={{ borderTop: '1px solid rgba(0,0,0,0.06)' }}>
                            <td style={{ padding: '8px 10px' }}>
                              {hasDetails ? (
                                <button
                                  type="button"
                                  onClick={() => toggleSource(key)}
                                  aria-label={isExpanded ? 'Collapse details' : 'Expand details'}
                                  style={{
                                    background: 'none',
                                    border: 'none',
                                    cursor: 'pointer',
                                    padding: 0,
                                    display: 'flex',
                                    alignItems: 'center',
                                    color: 'var(--text-light)',
                                  }}
                                >
                                  {isExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                                </button>
                              ) : null}
                            </td>
                            <td style={{ padding: '8px 10px', wordBreak: 'break-word', maxWidth: 280 }}>
                              {showNameSeparately ? (
                                <div style={{ fontWeight: 600, marginBottom: 2 }}>{row.source}</div>
                              ) : null}
                              {href ? (
                                <a
                                  href={href}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  title={`Visit ${href}`}
                                  style={{
                                    display: 'inline-flex',
                                    alignItems: 'flex-start',
                                    gap: 4,
                                    color: 'var(--primary-color)',
                                    textDecoration: 'none',
                                    fontWeight: showNameSeparately ? 400 : 600,
                                    wordBreak: 'break-all',
                                  }}
                                >
                                  {href}
                                  <ExternalLink size={11} style={{ flexShrink: 0, marginTop: 2 }} />
                                </a>
                              ) : (
                                row.source
                              )}
                            </td>
                            <td style={{ padding: '8px 10px' }}>
                              <span
                                style={{
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  gap: 4,
                                  padding: '3px 9px',
                                  borderRadius: 999,
                                  background: `${badge.color}1f`,
                                  color: badge.color,
                                  fontWeight: 600,
                                  fontSize: '0.75rem',
                                  whiteSpace: 'nowrap',
                                }}
                              >
                                <badge.Icon size={13} /> {badge.label}
                              </span>
                            </td>
                            {SOURCE_COLUMNS.map((col) => (
                              <td key={col.key} style={{ padding: '8px 10px', textAlign: 'right' }}>
                                {row[col.key] ?? 0}
                              </td>
                            ))}
                          </tr>
                          {isExpanded && hasDetails ? (
                            <tr style={{ background: 'rgba(0,0,0,0.02)' }}>
                              <td />
                              <td colSpan={SOURCE_COLUMNS.length + 2} style={{ padding: '8px 10px 12px', fontSize: '0.8rem', color: 'var(--text-dark)' }}>
                                {row.fetch_note}
                              </td>
                            </tr>
                          ) : null}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
