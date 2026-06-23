import React, { useState, useEffect, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Globe, AtSign, Share2, Link2, Type, Plus,
  ArrowRight, DownloadCloud, Sparkles, Database,
  CheckCircle2, RefreshCw
} from 'lucide-react';
import '../Workflow.css';

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

export default function WorkflowPage({ articles = [], isScraping = false, onRunScraper, feeds = [], pipelineRuns = [] }) {
  // Source rows reflect the real configured feeds (from /api/feeds).
  const seedRows = (list) =>
    (list.length ? list : ['https://www.bmwblog.com/feed/']).map((url, i) => ({
      id: i + 1, platform: 'web', type: 'link', value: url,
    }));

  const [rows, setRows] = useState(() => seedRows(feeds));

  useEffect(() => {
    if (feeds.length) setRows(seedRows(feeds));
  }, [feeds]);

  // State is driven by the REAL pipeline, not a timer.
  const hasData = articles.length > 0;
  const workflowState = isScraping ? 'cleaning' : (hasData ? 'ready' : 'idle');

  // Stats computed from the REAL Supabase rows.
  const stats = useMemo(() => {
    const total = articles.length;
    const positive = articles.filter(
      (a) => (a.sentiment || '').toLowerCase() === 'positive'
    ).length;
    const sources = new Set(articles.map((a) => a.source).filter(Boolean)).size;
    const avg = total
      ? (articles.reduce((s, a) => s + (Number(a.relevance_score) || 0), 0) / total).toFixed(1)
      : '0.0';
    return { total, positive, sources, avg };
  }, [articles]);

  const addRow = () => {
    setRows([...rows, { id: Date.now(), platform: 'web', type: 'keywords', value: '' }]);
  };

  const updateRow = (id, field, value) => {
    setRows(rows.map((r) => (r.id === id ? { ...r, [field]: value } : r)));
  };

  const prettyStage = (stage) => {
    if (!stage) return 'queued';
    if (stage === 'done') return 'completed';
    return stage;
  };

  const stageColor = (status) => {
    if (status === 'success') return '#2ed573';
    if (status === 'failed') return '#ff4757';
    if (status === 'running') return '#ffb13b';
    return '#9aa0aa';
  };

  return (
    <div className="workflow-layout">
      <div className="bg-pattern"></div>

      <div className="miro-board">

        {/* BLOCK 1: GET */}
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

          <button className="add-row-btn" onClick={addRow}>
            <Plus size={18} /> Add Source
          </button>

          <button
            className="btn-primary"
            style={{ marginTop: '15px', opacity: isScraping ? 0.7 : 1 }}
            onClick={onRunScraper}
            disabled={isScraping}
          >
            {isScraping ? (<><RefreshCw size={16} className="spin" /> Running…</>) : 'Run Extractor'}
          </button>
          <p style={{ fontSize: '0.72rem', color: 'var(--text-light)', marginTop: '8px', textAlign: 'center' }}>
            Sources are managed in Supabase. Editing rows here is a preview.
          </p>
        </motion.div>

        {/* ARROW 1 */}
        <div className="workflow-arrow">
          <ArrowRight size={32} />
        </div>

        {/* BLOCK 2: CLEANUP */}
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
                {['Parsing Raw HTML content', 'DeepSeek AI Sentiment Analysis', 'Extracting Car Models & Brands'].map((label, i) => (
                  <motion.div key={label} className="status-item" initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.4 }}>
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
                    Running on GitHub Actions — new rows land in ~3 min.
                  </p>
                )}
              </>
            )}
          </div>
        </motion.div>

        {/* ARROW 2 */}
        <div className="workflow-arrow">
          <ArrowRight size={32} />
        </div>

        {/* BLOCK 3: SAVE */}
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

        <motion.div
          className="workflow-block"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3 }}
        >
          <div className="block-header">
            <div className="block-icon save">
              <Database size={20} />
            </div>
            <div className="block-title">Recent Runs</div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {pipelineRuns.length === 0 ? (
              <div style={{ textAlign: 'center', color: 'var(--text-light)' }}>
                No recorded runs yet.
              </div>
            ) : (
              pipelineRuns.map((run) => (
                <div
                  key={run.id}
                  style={{
                    border: '1px solid rgba(0,0,0,0.06)',
                    borderRadius: '12px',
                    padding: '10px 12px',
                    background: 'rgba(255,255,255,0.5)',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: '10px', marginBottom: '6px' }}>
                    <strong style={{ fontSize: '0.88rem' }}>{prettyStage(run.stage)}</strong>
                    <span style={{ color: stageColor(run.status), fontSize: '0.78rem', textTransform: 'uppercase', fontWeight: 700 }}>
                      {run.status}
                    </span>
                  </div>
                  <div style={{ fontSize: '0.78rem', color: 'var(--text-light)', marginBottom: '6px' }}>
                    {run.message || 'No message'}
                  </div>
                  <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', fontSize: '0.72rem', color: 'var(--text-light)' }}>
                    <span>Scraped: {run.articles_scraped || 0}</span>
                    <span>Cleaned: {run.articles_cleaned || 0}</span>
                    <span>Saved: {run.articles_saved || 0}</span>
                  </div>
                </div>
              ))
            )}
          </div>
        </motion.div>

      </div>
    </div>
  );
}
