import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { ScanSearch, RefreshCw, AlertTriangle, CheckCircle2, ChevronLeft, ChevronRight } from 'lucide-react';
import { useAuth } from '../auth/useAuth.js';
import { getAnalysisStatus, listAnalysisErrors, reprocessArticle, analyzeArticles } from '../api/articlesApi.js';

const STATUS_ORDER = ['success', 'failed', 'processing', 'pending', 'partial'];
const STATUS_COLORS = {
  success: '#2ed573',
  failed: '#ff4757',
  processing: '#ffb13b',
  pending: '#9aa0aa',
  partial: '#f59e0b',
};

const PAGE_SIZE = 20;

function formatDateTime(value) {
  if (!value) return 'Not yet';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString();
}

export default function AnalysisPage({ projects = [] }) {
  const { hasPermission } = useAuth();
  const canReprocess = hasPermission('pipeline.run');

  const [projectFilter, setProjectFilter] = useState('all');
  const [offset, setOffset] = useState(0);
  const [reloadToken, setReloadToken] = useState(0);

  const [statusCounts, setStatusCounts] = useState(null);
  const [statusLoading, setStatusLoading] = useState(true);
  const [statusError, setStatusError] = useState('');

  const [errorsPage, setErrorsPage] = useState({ errors: [], total: 0, limit: PAGE_SIZE, offset: 0 });
  const [errorsLoading, setErrorsLoading] = useState(true);
  const [errorsError, setErrorsError] = useState('');

  const [selectedIds, setSelectedIds] = useState([]);
  const [reprocessingIds, setReprocessingIds] = useState([]);
  const [actionError, setActionError] = useState('');

  useEffect(() => {
    setOffset(0);
    setSelectedIds([]);
  }, [projectFilter]);

  useEffect(() => {
    const controller = new AbortController();
    async function loadStatus() {
      setStatusLoading(true);
      setStatusError('');
      try {
        const data = await getAnalysisStatus(
          { project_id: projectFilter !== 'all' ? projectFilter : undefined },
          controller.signal,
        );
        setStatusCounts(data?.counts || {});
      } catch (err) {
        if (err?.name !== 'AbortError') {
          setStatusCounts(null);
          setStatusError(err?.message || 'Failed to load analysis status.');
        }
      } finally {
        setStatusLoading(false);
      }
    }
    loadStatus();
    return () => controller.abort();
  }, [projectFilter, reloadToken]);

  useEffect(() => {
    const controller = new AbortController();
    async function loadErrors() {
      setErrorsLoading(true);
      setErrorsError('');
      try {
        const data = await listAnalysisErrors(
          { limit: PAGE_SIZE, offset, project_id: projectFilter !== 'all' ? projectFilter : undefined },
          controller.signal,
        );
        setErrorsPage({
          errors: Array.isArray(data?.errors) ? data.errors : [],
          total: Number(data?.total) || 0,
          limit: Number(data?.limit) || PAGE_SIZE,
          offset: Number(data?.offset) || 0,
        });
      } catch (err) {
        if (err?.name !== 'AbortError') {
          setErrorsPage({ errors: [], total: 0, limit: PAGE_SIZE, offset: 0 });
          setErrorsError(err?.message || 'Failed to load analysis errors.');
        }
      } finally {
        setErrorsLoading(false);
      }
    }
    loadErrors();
    return () => controller.abort();
  }, [projectFilter, offset, reloadToken]);

  const total = errorsPage.total;
  const start = total === 0 ? 0 : offset + 1;
  const end = Math.min(offset + errorsPage.errors.length, total);
  const hasPrev = offset > 0;
  const hasNext = offset + PAGE_SIZE < total;

  const toggleSelected = (id) => {
    setSelectedIds((current) => (current.includes(id) ? current.filter((value) => value !== id) : [...current, id]));
  };

  const reprocessOne = async (articleId) => {
    setActionError('');
    setReprocessingIds((current) => [...current, articleId]);
    try {
      await reprocessArticle(articleId);
    } catch (err) {
      setActionError(err?.message || 'Failed to reprocess article.');
    } finally {
      setReprocessingIds((current) => current.filter((id) => id !== articleId));
      setSelectedIds((current) => current.filter((id) => id !== articleId));
      setReloadToken((value) => value + 1);
    }
  };

  const reprocessSelected = async () => {
    if (selectedIds.length === 0) return;
    setActionError('');
    const targetIds = selectedIds;
    setReprocessingIds((current) => [...new Set([...current, ...targetIds])]);
    try {
      await analyzeArticles({ article_ids: targetIds, force: true });
    } catch (err) {
      setActionError(err?.message || 'Failed to reprocess selected articles.');
    } finally {
      setReprocessingIds((current) => current.filter((id) => !targetIds.includes(id)));
      setSelectedIds([]);
      setReloadToken((value) => value + 1);
    }
  };

  const statusEntries = useMemo(() => {
    if (!statusCounts) return [];
    const known = STATUS_ORDER.filter((key) => statusCounts[key] != null);
    const extra = Object.keys(statusCounts).filter((key) => !STATUS_ORDER.includes(key));
    return [...known, ...extra].map((key) => ({ key, count: Number(statusCounts[key]) || 0 }));
  }, [statusCounts]);

  const totalAnalyzed = statusEntries.reduce((sum, entry) => sum + entry.count, 0);

  return (
    <div className="admin-page-shell">
      <div className="admin-page-header">
        <div>
          <div className="admin-page-kicker">
            <ScanSearch size={14} /> Performance pipeline
          </div>
          <h1 className="admin-page-title">Performance Logs</h1>
          <p className="admin-page-subtitle">
            Processing status, failures, and reprocessing for the article analysis pipeline.
          </p>
        </div>

        <div className="admin-page-toolbar">
          <button className="btn-secondary" onClick={() => setReloadToken((value) => value + 1)} disabled={statusLoading || errorsLoading}>
            <RefreshCw size={16} /> Refresh
          </button>
          <Link to="/dashboard" className="btn-secondary" style={{ textDecoration: 'none' }}>
            Back to Dashboard
          </Link>
        </div>
      </div>

      <div className="admin-toolbar-row">
        <select className="filter-select" value={projectFilter} onChange={(e) => setProjectFilter(e.target.value)}>
          <option value="all">All projects</option>
          {projects.map((project) => (
            <option key={project.id} value={String(project.id)}>
              {project.name}
            </option>
          ))}
        </select>
      </div>

      {statusError ? (
        <div className="glass-card" style={{ color: '#b42318', borderLeft: '4px solid #ff4757', marginBottom: 18 }}>
          Couldn't load analysis status: {statusError}
        </div>
      ) : null}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 12, marginBottom: 24 }}>
        {statusLoading && !statusCounts ? (
          Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="glass-card" style={{ minHeight: 84, opacity: 0.7, animation: 'pulse 1.3s infinite' }} />
          ))
        ) : statusEntries.length === 0 ? (
          <div className="glass-card admin-empty-state" style={{ gridColumn: '1 / -1' }}>
            <strong>No analysis data yet</strong>
            <span>Run the pipeline to see processing status here.</span>
          </div>
        ) : (
          statusEntries.map((entry) => (
            <div key={entry.key} className="glass-card" style={{ padding: '14px 16px' }}>
              <div
                style={{
                  fontSize: '0.72rem',
                  textTransform: 'uppercase',
                  letterSpacing: '0.04em',
                  color: STATUS_COLORS[entry.key] || 'var(--text-light)',
                  fontWeight: 700,
                }}
              >
                {entry.key}
              </div>
              <strong style={{ fontSize: '1.6rem', display: 'block' }}>{entry.count.toLocaleString()}</strong>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-light)' }}>
                {totalAnalyzed ? `${Math.round((entry.count / totalAnalyzed) * 100)}% of ${totalAnalyzed.toLocaleString()}` : ''}
              </div>
            </div>
          ))
        )}
      </div>

      <div className="admin-toolbar-row" style={{ justifyContent: 'space-between', flexWrap: 'wrap', gap: 10 }}>
        <div>
          <h2 style={{ fontSize: '1.05rem', margin: 0 }}>Failed analysis</h2>
          <p className="subtitle" style={{ margin: '4px 0 0' }}>
            {errorsLoading ? 'Loading...' : `${total.toLocaleString()} article${total === 1 ? '' : 's'} need attention${total ? `, showing ${start}-${end}` : ''}`}
          </p>
        </div>
        {canReprocess ? (
          <button className="btn-secondary" onClick={reprocessSelected} disabled={selectedIds.length === 0 || reprocessingIds.length > 0}>
            {reprocessingIds.length > 0 && selectedIds.length === 0 ? 'Reprocessing...' : `Reprocess selected (${selectedIds.length})`}
          </button>
        ) : null}
      </div>

      {actionError ? (
        <div className="glass-card" style={{ color: '#b42318', borderLeft: '4px solid #ff4757', marginTop: 12, marginBottom: 18 }}>
          {actionError}
        </div>
      ) : null}

      {errorsError ? (
        <div className="glass-card" style={{ color: '#b42318', borderLeft: '4px solid #ff4757', marginTop: 12, marginBottom: 18 }}>
          {errorsError}
        </div>
      ) : null}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 12 }}>
        {errorsLoading ? (
          Array.from({ length: 4 }).map((_, i) => <div key={i} className="glass-card" style={{ minHeight: 76, opacity: 0.7, animation: 'pulse 1.3s infinite' }} />)
        ) : errorsPage.errors.length === 0 ? (
          <div className="admin-empty-state">
            <div className="admin-empty-state-icon">
              <CheckCircle2 size={18} />
            </div>
            <strong>No analysis failures</strong>
            <span>Every analyzed article in this scope completed successfully.</span>
          </div>
        ) : (
          errorsPage.errors.map((row) => (
            <motion.div
              key={row.id}
              className="glass-card"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              style={{ display: 'flex', flexDirection: 'column', gap: 8 }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10, flexWrap: 'wrap' }}>
                <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
                  {canReprocess ? (
                    <input
                      type="checkbox"
                      checked={selectedIds.includes(row.id)}
                      onChange={() => toggleSelected(row.id)}
                      style={{ marginTop: 4 }}
                      aria-label={`Select ${row.title || row.url}`}
                    />
                  ) : null}
                  <div>
                    <strong style={{ fontSize: '0.95rem' }}>{row.title || row.url || `Article #${row.id}`}</strong>
                    <div style={{ fontSize: '0.78rem', color: 'var(--text-light)' }}>{row.source || 'Unknown source'}</div>
                  </div>
                </div>
                {canReprocess ? (
                  <button
                    className="btn-secondary"
                    onClick={() => reprocessOne(row.id)}
                    disabled={reprocessingIds.includes(row.id)}
                    style={{ padding: '6px 10px', fontSize: '0.75rem' }}
                  >
                    {reprocessingIds.includes(row.id) ? 'Reprocessing...' : 'Reprocess'}
                  </button>
                ) : null}
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.8rem', color: '#b42318' }}>
                <AlertTriangle size={14} /> {row.analysis_error || 'Unknown error'}
              </div>
              <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', fontSize: '0.75rem', color: 'var(--text-light)' }}>
                <span>Attempts: {row.analysis_attempt_count ?? 0}</span>
                <span>Last attempt: {formatDateTime(row.analysis_finished_at || row.analysis_started_at)}</span>
              </div>
            </motion.div>
          ))
        )}
      </div>

      {total > PAGE_SIZE ? (
        <div className="admin-toolbar-row" style={{ justifyContent: 'flex-end', marginTop: 16 }}>
          <button className="btn-secondary" onClick={() => setOffset((prev) => Math.max(0, prev - PAGE_SIZE))} disabled={!hasPrev || errorsLoading}>
            <ChevronLeft size={16} /> Previous
          </button>
          <button className="btn-secondary" onClick={() => setOffset((prev) => prev + PAGE_SIZE)} disabled={!hasNext || errorsLoading}>
            Next <ChevronRight size={16} />
          </button>
        </div>
      ) : null}
    </div>
  );
}
