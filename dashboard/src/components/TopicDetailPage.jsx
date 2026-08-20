import { useEffect, useMemo, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import {
  ArrowLeft,
  Lightbulb,
  Loader2,
  AlertTriangle,
  Rss,
  ExternalLink,
  Workflow,
  FileText,
} from 'lucide-react';
const TYPE_COLORS = { praise: '#16a34a', complaint: '#e11d48', issue: '#e11d48', suggestion: '#f59e0b' };
const ARTICLE_DISPLAY_CAP = 200;

function typeColor(type) {
  return TYPE_COLORS[String(type || '').toLowerCase()] || '#64748b';
}

function formatDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleDateString();
}

function formatChartDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

// "August 18 2026" - long enough to be unambiguous without a locale comma.
function formatLongDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return `${date.toLocaleDateString(undefined, { month: 'long' })} ${date.getDate()} ${date.getFullYear()}`;
}

function sourceDate(source) {
  return source?.published || source?.createdAt || null;
}

function TypeBadge({ type }) {
  const color = typeColor(type);
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        padding: '3px 10px',
        borderRadius: 999,
        background: `${color}1f`,
        color,
        fontWeight: 600,
        textTransform: 'capitalize',
        fontSize: '0.75rem',
      }}
    >
      {type || 'issue'}
    </span>
  );
}

export default function TopicDetailPage() {
  const location = useLocation();
  const state = location.state;
  const sources = useMemo(() => (Array.isArray(state?.sources) ? state.sources : []), [state]);

  const distinctRunIds = useMemo(
    () => [...new Set(sources.map((source) => source.pipelineRunId).filter(Boolean))],
    [sources]
  );
  const unattributedCount = sources.length - sources.filter((source) => source.pipelineRunId).length;

  const [runDetails, setRunDetails] = useState({});

  useEffect(() => {
    if (!distinctRunIds.length) return undefined;
    let cancelled = false;
    distinctRunIds.forEach((runId) => {
      setRunDetails((prev) => ({ ...prev, [runId]: { ...(prev[runId] || {}), loading: true } }));
      fetch(`/api/pipeline-runs/${runId}`)
        .then(async (res) => {
          const data = await res.json().catch(() => ({}));
          if (!res.ok) throw new Error(data?.detail || data?.error || `Failed to load run (${res.status})`);
          if (!cancelled) setRunDetails((prev) => ({ ...prev, [runId]: { run: data?.run || null, loading: false, error: '' } }));
        })
        .catch((err) => {
          if (!cancelled) {
            setRunDetails((prev) => ({ ...prev, [runId]: { run: null, loading: false, error: err?.message || 'Pipeline details unavailable.' } }));
          }
        });
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [distinctRunIds.join(',')]);

  const { seriesData, undatedCount } = useMemo(() => {
    const counts = new Map();
    let undated = 0;
    sources.forEach((source) => {
      const raw = sourceDate(source);
      const day = raw ? String(raw).slice(0, 10) : null;
      if (!day || Number.isNaN(new Date(day).getTime())) {
        undated += 1;
        return;
      }
      counts.set(day, (counts.get(day) || 0) + 1);
    });
    const dates = [...counts.keys()].sort();
    return { seriesData: dates.map((date) => ({ date, count: counts.get(date) })), undatedCount: undated };
  }, [sources]);

  const sortedSources = useMemo(
    () => [...sources].sort((a, b) => new Date(sourceDate(b) || 0).getTime() - new Date(sourceDate(a) || 0).getTime()),
    [sources]
  );
  const displayedSources = sortedSources.slice(0, ARTICLE_DISPLAY_CAP);

  // Every displayed article's full analysis (summary/sentiment), fetched up
  // front and shown inline - no click/modal needed to read it.
  const [articleDetails, setArticleDetails] = useState({});
  const displayedArticleIds = useMemo(
    () => displayedSources.map((source) => source.id).filter((id) => id != null),
    [displayedSources]
  );

  useEffect(() => {
    if (!displayedArticleIds.length) return undefined;
    let cancelled = false;
    displayedArticleIds.forEach((id) => {
      setArticleDetails((prev) => ({ ...prev, [id]: { ...(prev[id] || {}), loading: true } }));
      fetch(`/api/articles/${id}/analysis`)
        .then(async (res) => {
          const data = await res.json().catch(() => ({}));
          if (!res.ok) throw new Error(data?.detail || data?.error || `Failed to load article (${res.status})`);
          if (!cancelled) setArticleDetails((prev) => ({ ...prev, [id]: { data: data?.analysis || null, loading: false, error: '' } }));
        })
        .catch((err) => {
          if (!cancelled) setArticleDetails((prev) => ({ ...prev, [id]: { data: null, loading: false, error: err?.message || 'Failed to load article.' } }));
        });
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [displayedArticleIds.join(',')]);

  const totalMentions = sources.length || Number(state?.frequencyEstimate || 0);
  const firstSeen = sortedSources.length ? sourceDate(sortedSources[sortedSources.length - 1]) : null;
  const lastSeen = sortedSources.length ? sourceDate(sortedSources[0]) : null;

  const backTo = state?.backTo || '/dashboard';
  const backLabel = state?.backLabel || 'Back to Dashboard';

  if (!state || !sources.length) {
    return (
      <div className="admin-page-shell">
        <div className="glass-card admin-empty-state">
          <div className="admin-empty-state-icon">
            <Lightbulb size={18} />
          </div>
          <strong>No topic selected</strong>
          <span>Open this page by clicking a topic from the dashboard, reports, or a project's frequent ideas.</span>
          <Link to={backTo} className="btn-secondary" style={{ textDecoration: 'none', marginTop: 12 }}>
            <ArrowLeft size={16} /> {backLabel}
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="admin-page-shell">
      <div className="admin-page-header">
        <div>
          <div className="admin-page-kicker">
            <Lightbulb size={14} /> Topic insights
          </div>
          <h1 className="admin-page-title">{state.idea}</h1>
          <p className="admin-page-subtitle" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <TypeBadge type={state.type} />
            {state.category ? <span className="admin-tag muted">{state.category}</span> : null}
          </p>
        </div>
        <div className="admin-page-toolbar">
          <Link to={backTo} className="btn-secondary" style={{ textDecoration: 'none' }}>
            <ArrowLeft size={16} /> {backLabel}
          </Link>
        </div>
      </div>

      <div className="admin-stats-grid">
        <div className="admin-stat-card">
          <div className="admin-stat-icon" style={{ background: 'rgba(37, 99, 235, 0.14)', color: '#2563eb' }}>
            <Lightbulb size={18} />
          </div>
          <div>
            <span>Mentions</span>
            <strong>{totalMentions.toLocaleString()}</strong>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon" style={{ background: 'rgba(46, 213, 115, 0.14)', color: '#2ed573' }}>
            <Rss size={18} />
          </div>
          <div>
            <span>First seen</span>
            <strong>{formatDate(firstSeen)}</strong>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon" style={{ background: 'rgba(255, 159, 67, 0.14)', color: 'var(--primary-color)' }}>
            <Rss size={18} />
          </div>
          <div>
            <span>Last seen</span>
            <strong>{formatDate(lastSeen)}</strong>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon" style={{ background: 'rgba(116, 125, 140, 0.14)', color: '#747d8c' }}>
            <Workflow size={18} />
          </div>
          <div>
            <span>Pipeline runs</span>
            <strong>{distinctRunIds.length.toLocaleString()}</strong>
          </div>
        </div>
      </div>

      <div className="glass-card" style={{ marginBottom: 18 }}>
        <h3 className="run-detail-section-title">Extracted by</h3>
        {distinctRunIds.length === 0 ? (
          <div className="run-detail-fallback">No pipeline run is recorded for these articles.</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {distinctRunIds.map((runId) => {
              const detail = runDetails[runId];
              return (
                <div
                  key={runId}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    padding: '10px 14px',
                    borderRadius: 12,
                    background: 'rgba(0,0,0,0.03)',
                    gap: 10,
                  }}
                >
                  {detail?.loading ? (
                    <span style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-light)', fontSize: '0.85rem' }}>
                      <Loader2 size={14} className="spin" /> Loading pipeline run…
                    </span>
                  ) : detail?.error ? (
                    <span style={{ display: 'flex', alignItems: 'center', gap: 6, color: '#b42318', fontSize: '0.85rem' }}>
                      <AlertTriangle size={14} /> {detail.error}
                    </span>
                  ) : (
                    <>
                      <span style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.85rem', fontWeight: 600 }}>
                        <Workflow size={15} style={{ color: 'var(--primary-color)' }} />
                        {detail?.run?.sequence_number ? `Pipeline #${detail.run.sequence_number}` : 'Pipeline run'}
                      </span>
                      <span style={{ fontSize: '0.8rem', color: 'var(--text-light)' }}>
                        {formatLongDate(detail?.run?.started_at)}
                      </span>
                    </>
                  )}
                </div>
              );
            })}
            {unattributedCount > 0 ? (
              <span style={{ fontSize: '0.78rem', color: 'var(--text-light)' }}>
                {unattributedCount.toLocaleString()} article{unattributedCount === 1 ? '' : 's'} with no recorded pipeline run (manual import or reanalysis).
              </span>
            ) : null}
          </div>
        )}
      </div>

      <div className="glass-card" style={{ marginBottom: 18 }}>
        <h3 className="run-detail-section-title">Mentions over time</h3>
        {seriesData.length === 0 ? (
          <div className="run-detail-fallback">No dated articles to plot yet.</div>
        ) : (
          <>
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={seriesData}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(15,23,42,.09)" />
                <XAxis dataKey="date" tickFormatter={formatChartDate} minTickGap={24} />
                <YAxis allowDecimals={false} />
                <Tooltip labelFormatter={formatChartDate} formatter={(value) => [`${value}`, 'Mentions']} />
                <Line type="monotone" dataKey="count" name="Mentions" stroke="#2563eb" strokeWidth={2.5} dot={false} />
              </LineChart>
            </ResponsiveContainer>
            {undatedCount > 0 ? (
              <span style={{ fontSize: '0.78rem', color: 'var(--text-light)' }}>
                {undatedCount.toLocaleString()} article{undatedCount === 1 ? '' : 's'} without a date not shown above.
              </span>
            ) : null}
          </>
        )}
      </div>

      <div className="glass-card">
        <h3 className="run-detail-section-title">Articles ({sources.length.toLocaleString()})</h3>
        {displayedSources.length === 0 ? (
          <div className="run-detail-fallback">No representative articles found.</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {displayedSources.map((source) => {
              const detail = source.id != null ? articleDetails[source.id] : null;
              const sentiment = detail?.data?.sentiment || source.sentiment;
              const url = detail?.data?.url || source.url;
              return (
                <div
                  key={source.id ?? source.url}
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 8,
                    padding: '12px 14px',
                    borderRadius: 10,
                    background: 'rgba(0,0,0,0.02)',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, fontSize: '0.84rem' }}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0, fontWeight: 600 }}>
                      {source.title || source.url} <FileText size={12} style={{ opacity: 0.5, flexShrink: 0 }} />
                    </span>
                    <span style={{ display: 'flex', alignItems: 'center', gap: 10, color: 'var(--text-light)', flexShrink: 0 }}>
                      {source.source ? <span>{source.source}</span> : null}
                      {sentiment ? <span className="admin-tag muted">{sentiment}</span> : null}
                      <span>{formatDate(sourceDate(source))}</span>
                    </span>
                  </div>
                  {detail?.loading ? (
                    <p className="subtitle" style={{ margin: 0 }}>Loading summary…</p>
                  ) : detail?.error ? (
                    <p style={{ margin: 0, color: '#b42318', fontSize: '0.82rem' }}>{detail.error}</p>
                  ) : detail?.data?.summary ? (
                    <p style={{ margin: 0, lineHeight: 1.5, fontSize: '0.84rem' }}>{detail.data.summary}</p>
                  ) : (
                    <p className="subtitle" style={{ margin: 0 }}>No summary available for this article.</p>
                  )}
                  {url ? (
                    <a
                      href={url}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ display: 'inline-flex', alignItems: 'center', gap: 5, alignSelf: 'flex-start', fontSize: '0.8rem', color: 'var(--primary-color)', textDecoration: 'none' }}
                    >
                      View original article <ExternalLink size={12} />
                    </a>
                  ) : null}
                </div>
              );
            })}
            {sources.length > displayedSources.length ? (
              <span style={{ fontSize: '0.78rem', color: 'var(--text-light)' }}>
                Showing {displayedSources.length.toLocaleString()} of {sources.length.toLocaleString()} articles.
              </span>
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
}
