import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Database, RefreshCw } from 'lucide-react';

function prettyStage(stage) {
  if (!stage) return 'queued';
  if (stage === 'done') return 'completed';
  return stage;
}

function stageColor(status) {
  if (status === 'success') return '#2ed573';
  if (status === 'failed') return '#ff4757';
  if (status === 'running') return '#ffb13b';
  return '#9aa0aa';
}

export default function PipelineRunsPage() {
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const loadRuns = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await fetch('/api/pipeline-runs?limit=25');
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.error || `Failed to load pipeline runs (${res.status})`);
      setRuns(Array.isArray(data?.runs) ? data.runs : []);
    } catch (err) {
      setError(err?.message || 'Failed to load pipeline runs.');
      setRuns([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadRuns();
  }, []);

  return (
    <div style={{ minHeight: '100vh', padding: '32px 28px 40px' }}>
      <div style={{ maxWidth: 1200, margin: '0 auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', marginBottom: 20 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 6 }}>
              <Database size={26} color="#ff6b35" />
              <h1 style={{ fontSize: '1.9rem', fontWeight: 800, margin: 0 }}>Pipeline Runs</h1>
            </div>
            <p style={{ color: 'var(--text-light)', margin: 0 }}>
              Independent history view for scraper and enrich jobs.
            </p>
          </div>

          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <button className="btn-secondary" onClick={loadRuns} disabled={loading}>
              <RefreshCw size={16} /> Refresh
            </button>
            <Link to="/dashboard" className="btn-secondary" style={{ textDecoration: 'none' }}>
              Back to Dashboard
            </Link>
          </div>
        </div>

        {error ? (
          <div className="glass-card" style={{ color: '#b42318', borderLeft: '4px solid #ff4757', marginBottom: 18 }}>
            {error}
          </div>
        ) : null}

        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {loading ? (
            Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="glass-card" style={{ minHeight: 92, opacity: 0.7, animation: 'pulse 1.3s infinite' }} />
            ))
          ) : runs.length === 0 ? (
            <div className="glass-card" style={{ textAlign: 'center', padding: 40, color: 'var(--text-light)' }}>
              No recorded runs yet.
            </div>
          ) : (
            runs.map((run, i) => (
              <motion.div
                key={run.id}
                className="glass-card"
                initial={{ opacity: 0, y: 14 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.03 }}
                style={{ display: 'flex', flexDirection: 'column', gap: 10 }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap' }}>
                  <strong style={{ fontSize: '0.98rem' }}>{prettyStage(run.stage)}</strong>
                  <span style={{ color: stageColor(run.status), fontSize: '0.8rem', textTransform: 'uppercase', fontWeight: 700 }}>
                    {run.status}
                  </span>
                </div>
                <div style={{ fontSize: '0.88rem', color: 'var(--text-dark)' }}>
                  {run.message || 'No message'}
                </div>
                <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', fontSize: '0.75rem', color: 'var(--text-light)' }}>
                  <span>Scraped: {run.articles_scraped || 0}</span>
                  <span>Cleaned: {run.articles_cleaned || 0}</span>
                  <span>Saved: {run.articles_saved || 0}</span>
                  <span>Pages: {run.crawl_pages || 0}</span>
                </div>
                <div style={{ fontSize: '0.75rem', color: 'var(--text-light)' }}>
                  {run.created_at ? `Created ${new Date(run.created_at).toLocaleString()}` : ''}
                  {run.finished_at ? ` • Finished ${new Date(run.finished_at).toLocaleString()}` : ''}
                </div>
              </motion.div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
