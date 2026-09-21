import { Fragment, useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  ArrowLeft,
  Database,
  Loader2,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  FileText,
  ListChecks,
  ScanSearch,
  Sparkles,
  ShieldCheck,
} from 'lucide-react';
import { getPipelineRun, setArticleRelevanceOverride } from '../api/pipelineRunsApi.js';
import { useAuth } from '../auth/useAuth.js';

function prettyStage(stage) {
  if (!stage) return 'queued';
  if (stage === 'done') return 'completed';
  if (stage === 'prepare') return 'selecting articles';
  if (stage === 'analyze') return 'analyzing';
  if (stage === 'no_work') return 'no analysis required';
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
  // Sub-second stages (selecting articles is a single query) are real, measured
  // durations - round-tripping through whole seconds would show "0s".
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

// A run has exactly two stages: work out what to analyze, then analyze it.
// Nearly all of the wall clock is the second one - it is one model pass per
// article - so showing them separately is what tells "the query is slow" apart
// from "the model is slow".
const STAGE_ROWS = [
  { key: 'prepare', label: 'Selecting articles', startField: 'prepare_started_at', endField: 'prepare_finished_at', Icon: ListChecks },
  { key: 'analyze', label: 'Analyzing', startField: 'analysis_started_at', endField: 'analysis_finished_at', Icon: Sparkles },
];

const TOTAL_STATS = [
  { key: 'articles_selected', label: 'Articles selected', Icon: ListChecks, tint: 'rgba(46, 134, 222, 0.14)', color: '#2e86de' },
  { key: 'articles_analyzed', label: 'Articles analyzed', Icon: ScanSearch, tint: 'rgba(46, 213, 115, 0.14)', color: '#2ed573' },
  { key: 'articles_failed', label: 'Articles failed', Icon: CircleAlert, tint: 'rgba(255, 71, 87, 0.14)', color: '#ff4757' },
];

const DOCUMENT_COLUMNS = [
  { key: 'selected', label: 'Selected' },
  { key: 'analyzed', label: 'Analyzed' },
  { key: 'failed', label: 'Failed' },
];

function documentStatusBadge(row) {
  if (row.failed) {
    return { label: `${row.failed} failed`, color: '#ff4757', Icon: CircleAlert };
  }
  if (row.analyzed < row.selected) {
    return { label: 'In progress', color: '#ffb13b', Icon: Loader2 };
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
  const { hasPermission } = useAuth();
  const canReview = hasPermission('projects.update');
  const [run, setRun] = useState(null);
  const [documents, setDocuments] = useState([]);
  const [screenings, setScreenings] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [expandedDocuments, setExpandedDocuments] = useState(() => new Set());
  const [overrideDraft, setOverrideDraft] = useState(null);
  const [overrideSaving, setOverrideSaving] = useState(false);
  const [overrideMessage, setOverrideMessage] = useState('');

  const projectsById = useMemo(() => {
    const map = new Map();
    projects.forEach((project) => map.set(Number(project.id), project));
    return map;
  }, [projects]);

  useEffect(() => {
    if (!runId) return undefined;

    let cancelled = false;
    let intervalId = null;

    const load = ({ showLoading = false } = {}) => {
      if (showLoading) {
        setLoading(true);
        setError('');
      }
      return getPipelineRun(runId)
        .then((data) => {
          if (cancelled) return null;
          setRun(data?.run || null);
          setDocuments(Array.isArray(data?.documents) ? data.documents : []);
          setScreenings(Array.isArray(data?.screenings) ? data.screenings : []);
          return data?.run || null;
        })
        .catch((err) => {
          if (!cancelled) setError(err?.message || 'Failed to load run details.');
          return null;
        })
        .finally(() => {
          if (!cancelled && showLoading) setLoading(false);
        });
    };

    load({ showLoading: true }).then((loadedRun) => {
      if (cancelled) return;
      const status = (loadedRun?.status || '').toLowerCase();
      if (status !== 'queued' && status !== 'running') return;
      // Per-document rows fill in live while the run is active (the pipeline
      // writes them per article) - poll until the run reaches a terminal
      // status instead of leaving this static.
      intervalId = setInterval(() => {
        load().then((polledRun) => {
          const polledStatus = (polledRun?.status || '').toLowerCase();
          if (polledRun && polledStatus !== 'queued' && polledStatus !== 'running' && intervalId) {
            clearInterval(intervalId);
            intervalId = null;
          }
        });
      }, 3000);
    });

    return () => {
      cancelled = true;
      if (intervalId) clearInterval(intervalId);
    };
  }, [runId]);

  const toggleDocument = (key) => {
    setExpandedDocuments((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const total = run ? stageDuration(run.started_at, run.finished_at) : null;
  const projectName = projectNameForRun(run, projectsById);

  const saveOverride = async () => {
    if (!overrideDraft || !overrideDraft.reason.trim()) return;
    setOverrideSaving(true);
    setOverrideMessage('');
    try {
      await setArticleRelevanceOverride(run.project_id, overrideDraft.articleId, {
        decision: overrideDraft.decision,
        reason: overrideDraft.reason.trim(),
      });
      setOverrideMessage(`Saved. The article will be ${overrideDraft.decision === 'include' ? 'included' : 'excluded'} on the next analysis run.`);
      setOverrideDraft(null);
    } catch (err) {
      setOverrideMessage(err?.message || 'Unable to save the relevance override.');
    } finally {
      setOverrideSaving(false);
    }
  };

  return (
    <div className="admin-page-shell">
      <div className="admin-page-header">
        <div>
          <div className="admin-page-kicker">
            <Database size={14} /> Analysis history
          </div>
          <h1 className="admin-page-title">Analysis Run Details</h1>
          {projectName ? <p className="admin-page-subtitle">{projectName}</p> : null}
        </div>
        <div className="admin-page-toolbar">
          <Link to="/pipeline-runs" className="btn-secondary" style={{ textDecoration: 'none' }}>
            <ArrowLeft size={16} /> Back to Analysis Runs
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

          <div className="glass-card" style={{ marginBottom: 18 }}>
            <div className="run-detail-summary-grid">
              <SummaryField label="Project">{projectName}</SummaryField>
              <SummaryField label="Status">
                <StatusBadge status={run.status} />
              </SummaryField>
              <SummaryField label="Current stage">{prettyStage(run.stage)}</SummaryField>
              <SummaryField label="Dashboard dataset">{run.analytics_eligible ? `${run.analysis_result_count} saved article result(s)` : 'Not used for analytics'}</SummaryField>
              <SummaryField label="Started at">{formatDateTime(run.started_at)}</SummaryField>
              <SummaryField label="Finished at">{formatDateTime(run.finished_at)}</SummaryField>
              <SummaryField label="Total duration">
                {total.text}
                {total.inProgress ? ' (in progress)' : ''}
              </SummaryField>
            </div>

            {/* Message/error text can run long (a full sentence, or a
                provider error's raw detail) - kept in their own full-width
                containers below the small-field grid instead of as cells in
                it, so one long value can't stretch or misalign the rest. */}
            {run.message ? (
              <div className="run-detail-message-box">
                <div className="run-detail-box-label">Message</div>
                <div className="run-detail-message-text">{run.message}</div>
              </div>
            ) : null}

            {run.error ? (
              <div className="run-detail-error-box">
                <div className="run-detail-box-label">
                  <AlertTriangle size={13} /> Error
                </div>
                <pre className="run-detail-error-text">{run.error}</pre>
              </div>
            ) : null}
          </div>

          <div className="glass-card" style={{ marginBottom: 18 }}>
            <h3 className="run-detail-section-title">Timing</h3>
            {!run.has_detail ? (
              <div className="run-detail-fallback">
                Details unavailable for this run — it finished before per-stage timing was tracked.
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

          {run.articles_screened > 0 || screenings.length > 0 ? (
            <div className="glass-card" style={{ marginBottom: 18 }}>
              <div className="run-detail-relevance-header">
                <div>
                  <h3 className="run-detail-section-title">Article relevance screening</h3>
                  <p className="run-detail-relevance-copy">
                    Embeddings admit clear matches, reject clear misses, and send borderline articles to a small batched check.
                    {run.screening_mode === 'observe' ? ' Observation mode records decisions while still analyzing every article.' : ''}
                  </p>
                </div>
                <span className="run-detail-mode-badge"><ShieldCheck size={14} /> {run.screening_mode || 'off'}</span>
              </div>

              <div className="run-detail-relevance-stats">
                <SummaryField label="Screened">{run.articles_screened || 0}</SummaryField>
                <SummaryField label="Included">{run.articles_included || 0}</SummaryField>
                <SummaryField label="Marked unrelated">{run.articles_excluded || 0}</SummaryField>
                <SummaryField label="Needs review">{run.articles_needs_review || 0}</SummaryField>
              </div>

              {overrideMessage ? <div className="run-detail-override-message">{overrideMessage}</div> : null}
              {screenings.length ? (
                <div className="table-scroll run-detail-screening-scroll">
                  <table className="run-detail-source-table run-detail-screening-table">
                    <thead>
                      <tr>
                        <th>Article</th>
                        <th>Decision</th>
                        <th>Similarity</th>
                        <th>Method</th>
                        <th>Reason</th>
                        {canReview ? <th>Override next run</th> : null}
                      </tr>
                    </thead>
                    <tbody>
                      {screenings.map((item) => (
                        <tr key={item.article_id}>
                          <td><strong>{item.title || `Article #${item.article_id}`}</strong><small>{item.source || ''}</small></td>
                          <td><span className={`run-detail-decision run-detail-decision-${item.decision}`}>{item.decision.replace('_', ' ')}</span></td>
                          <td>{item.similarity_score == null ? '—' : Number(item.similarity_score).toFixed(3)}</td>
                          <td>{item.decision_source || '—'}</td>
                          <td>{item.explanation || '—'}</td>
                          {canReview ? (
                            <td>
                              <div className="run-detail-override-actions">
                                <button type="button" className="btn-secondary" onClick={() => setOverrideDraft({ articleId: item.article_id, title: item.title, decision: 'include', reason: '' })}>Include</button>
                                <button type="button" className="btn-secondary" onClick={() => setOverrideDraft({ articleId: item.article_id, title: item.title, decision: 'exclude', reason: '' })}>Exclude</button>
                              </div>
                            </td>
                          ) : null}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : <div className="run-detail-fallback">Screening details have not been recorded yet.</div>}
            </div>
          ) : null}

          <div className="glass-card">
            <h3 className="run-detail-section-title">Per-document breakdown</h3>
            {!run.has_detail ? (
              <div className="run-detail-fallback">
                Details unavailable for this run — it finished before per-document stats were tracked.
              </div>
            ) : documents.length === 0 ? (
              <div className="run-detail-fallback">No per-document data recorded for this run yet.</div>
            ) : (
              <div className="table-scroll">
                <table className="run-detail-source-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
                  <thead>
                    <tr style={{ textAlign: 'left', background: 'var(--glass-bg)' }}>
                      <th style={{ padding: '8px 10px', width: 28 }} />
                      <th style={{ padding: '8px 10px' }}>Document</th>
                      <th style={{ padding: '8px 10px' }}>Status</th>
                      {DOCUMENT_COLUMNS.map((col) => (
                        <th key={col.key} style={{ padding: '8px 10px', textAlign: 'right' }}>
                          {col.label}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {documents.map((row) => {
                      const key = row.document;
                      const isExpanded = expandedDocuments.has(key);
                      const badge = documentStatusBadge(row);
                      const hasDetails = Boolean(row.note);
                      return (
                        <Fragment key={key}>
                          <tr style={{ borderTop: '1px solid rgba(0,0,0,0.06)' }}>
                            <td style={{ padding: '8px 10px' }}>
                              {hasDetails ? (
                                <button
                                  type="button"
                                  onClick={() => toggleDocument(key)}
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
                              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontWeight: 600 }}>
                                <FileText size={13} style={{ flexShrink: 0, color: 'var(--text-light)' }} />
                                {row.document}
                              </span>
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
                            {DOCUMENT_COLUMNS.map((col) => (
                              <td key={col.key} style={{ padding: '8px 10px', textAlign: 'right' }}>
                                {row[col.key] ?? 0}
                              </td>
                            ))}
                          </tr>
                          {isExpanded && hasDetails ? (
                            <tr style={{ background: 'rgba(0,0,0,0.02)' }}>
                              <td />
                              <td colSpan={DOCUMENT_COLUMNS.length + 2} style={{ padding: '8px 10px 12px', fontSize: '0.8rem', color: 'var(--text-dark)' }}>
                                {row.note}
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

          {overrideDraft ? (
            <div className="confirm-modal-backdrop" role="presentation" onMouseDown={() => !overrideSaving && setOverrideDraft(null)}>
              <div className="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="relevance-override-title" onMouseDown={(event) => event.stopPropagation()}>
                <h3 id="relevance-override-title">{overrideDraft.decision === 'include' ? 'Include' : 'Exclude'} this article next run?</h3>
                <p>{overrideDraft.title || `Article #${overrideDraft.articleId}`}</p>
                <label className="run-detail-override-label" htmlFor="relevance-override-reason">Reason</label>
                <textarea id="relevance-override-reason" rows={4} value={overrideDraft.reason} onChange={(event) => setOverrideDraft((draft) => ({ ...draft, reason: event.target.value }))} placeholder="Explain why this article belongs in or outside the project scope." />
                <div className="confirm-modal-actions">
                  <button type="button" className="btn-secondary" disabled={overrideSaving} onClick={() => setOverrideDraft(null)}>Cancel</button>
                  <button type="button" className="btn-primary" disabled={overrideSaving || !overrideDraft.reason.trim()} onClick={saveOverride}>
                    {overrideSaving ? 'Saving…' : 'Save for next run'}
                  </button>
                </div>
              </div>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
