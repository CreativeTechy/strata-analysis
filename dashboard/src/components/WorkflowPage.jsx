import React, { useState, useEffect, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
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

export default function WorkflowPage({ articles = [], isScraping = false, onRunScraper, feeds = [] }) {
  const seedRows = (list) =>
    (list.length ? list : []).map((url, i) => ({
      id: i + 1,
      platform: 'web',
      type: 'link',
      value: url,
    }));

  const [rows, setRows] = useState(() => seedRows(feeds));
  const [runs, setRuns] = useState([]);
  const [runsLoading, setRunsLoading] = useState(false);
  const [runsError, setRunsError] = useState('');

  useEffect(() => {
    if (feeds.length) setRows(seedRows(feeds));
  }, [feeds]);

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
    return () => {
      alive = false;
    };
  }, [isScraping]);

  const hasData = articles.length > 0;
  const workflowState = isScraping ? 'cleaning' : (hasData ? 'ready' : 'idle');

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

  const formatWhen = (value) => {
    if (!value) return 'just now';
    try {
      return new Date(value).toLocaleString();
    } catch {
      return String(value);
    }
  };

  const updateRow = (id, field, value) => {
    setRows(rows.map((r) => (r.id === id ? { ...r, [field]: value } : r)));
  };

  return (
    <div className="workflow-layout">
      <div className="bg-pattern"></div>

      <div className="workflow-shell">
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

              <div className="get-rows">
                <AnimatePresence>
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
                </AnimatePresence>
              </div>

              <Link
                to="/feeds"
                className="add-row-btn"
                style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px', textDecoration: 'none' }}
              >
                <Plus size={18} /> Add Source
              </Link>

              <button
                className="btn-primary"
                style={{ marginTop: '15px', opacity: isScraping ? 0.7 : 1 }}
                onClick={onRunScraper}
                disabled={isScraping}
              >
                {isScraping ? (<><RefreshCw size={16} className="spin" /> Running...</>) : 'Run Extractor'}
              </button>
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
                {workflowState === 'idle' && (
                  <div style={{ textAlign: 'center', color: 'var(--text-light)' }}>
                    Waiting for extraction...
                  </div>
                )}

                {(workflowState === 'cleaning' || workflowState === 'ready') && (
                  <>
                    {['Parsing raw content', 'Validating AI JSON output', 'Extracting entities, topics, and sentiment'].map((label, i) => (
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
                <span className="panel-pill neutral">live</span>
              </div>

              <div className="result-grid">
                <div className="result-card">
                  <FileText size={16} />
                  <span className="result-label">Articles</span>
                  <strong>{stats.total.toLocaleString()}</strong>
                </div>
                <div className="result-card">
                  <Layers3 size={16} />
                  <span className="result-label">Sources</span>
                  <strong>{stats.sources.toLocaleString()}</strong>
                </div>
                <div className="result-card">
                  <BadgeCheck size={16} />
                  <span className="result-label">Positive</span>
                  <strong>{stats.positive.toLocaleString()}</strong>
                </div>
                <div className="result-card">
                  <Flag size={16} />
                  <span className="result-label">Negative</span>
                  <strong>{stats.negative.toLocaleString()}</strong>
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
                      </div>
                      <div className="article-preview-title">{article.title || article.url}</div>
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
