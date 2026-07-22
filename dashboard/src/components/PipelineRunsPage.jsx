import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Database, RefreshCw, CalendarClock } from 'lucide-react';
import PipelineRunDetailModal from './PipelineRunDetailModal';

const POLL_INTERVAL_MS = 5000;
// Only surface an upcoming repeating run as a placeholder when it's within this
// many minutes of firing - otherwise every scheduled project would clutter the page.
const UPCOMING_WINDOW_MINUTES = 30;

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

const ACTIVE_STATUSES = ['queued', 'running'];

const STATUS_FILTER_OPTIONS = ['all', 'queued', 'running', 'success', 'failed', 'cancelled'];

function projectNameForRun(run, projectsById) {
  if (run.project_name) return run.project_name;
  const project = projectsById.get(Number(run.project_id));
  if (project?.name) return project.name;
  return run.project_id != null ? `Project #${run.project_id}` : 'Unassigned';
}

function findNearestUpcomingRun(projects, runs) {
  const now = Date.now();
  const windowMs = UPCOMING_WINDOW_MINUTES * 60 * 1000;
  const projectIdsWithActiveRun = new Set(
    runs
      .filter((run) => ACTIVE_STATUSES.includes(run.status))
      .map((run) => Number(run.project_id))
      .filter((id) => Number.isFinite(id))
  );

  const candidates = projects
    .filter((project) => project.repeat_enabled && project.next_run_at)
    .filter((project) => !projectIdsWithActiveRun.has(Number(project.id)))
    .map((project) => ({ project, nextRunAt: new Date(project.next_run_at).getTime() }))
    .filter(({ nextRunAt }) => Number.isFinite(nextRunAt) && nextRunAt - now <= windowMs)
    .sort((a, b) => a.nextRunAt - b.nextRunAt);

  return candidates[0] || null;
}

function formatCountdown(targetMs) {
  const diffMs = targetMs - Date.now();
  if (diffMs <= 0) return 'starting shortly';
  const minutes = Math.round(diffMs / 60000);
  if (minutes < 1) return 'in under a minute';
  if (minutes === 1) return 'in 1 minute';
  if (minutes < 60) return `in ${minutes} minutes`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return `in ${hours}h ${remainingMinutes}m`;
}

export default function PipelineRunsPage({ projects = [] }) {
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [stoppingId, setStoppingId] = useState(null);
  const [statusFilter, setStatusFilter] = useState('all');
  const [projectFilter, setProjectFilter] = useState('all');
  const [viewingRun, setViewingRun] = useState(null);

  const loadRuns = async ({ silent = false } = {}) => {
    if (!silent) setLoading(true);
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
      if (!silent) setLoading(false);
    }
  };

  useEffect(() => {
    loadRuns();
    const interval = setInterval(() => loadRuns({ silent: true }), POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, []);

  const stopRun = async (runId) => {
    setStoppingId(runId);
    try {
      const res = await fetch(`/api/pipeline-runs/${runId}/stop`, { method: 'POST' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.error || `Failed to stop run (${res.status})`);
      await loadRuns();
    } catch (err) {
      setError(err?.message || 'Failed to stop pipeline run.');
    } finally {
      setStoppingId(null);
    }
  };

  const projectsById = useMemo(() => {
    const map = new Map();
    projects.forEach((project) => map.set(Number(project.id), project));
    return map;
  }, [projects]);

  const projectFilterOptions = useMemo(() => {
    const idsInRuns = new Set(runs.map((run) => Number(run.project_id)).filter((id) => Number.isFinite(id)));
    return projects
      .filter((project) => idsInRuns.has(Number(project.id)))
      .map((project) => ({ id: Number(project.id), name: project.name || `Project #${project.id}` }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [projects, runs]);

  const statusOptionsInRuns = useMemo(() => {
    const present = new Set(runs.map((run) => run.status).filter(Boolean));
    return STATUS_FILTER_OPTIONS.filter((option) => option === 'all' || present.has(option));
  }, [runs]);

  const filteredRuns = useMemo(() => {
    return runs.filter((run) => {
      const matchesStatus = statusFilter === 'all' || run.status === statusFilter;
      const matchesProject = projectFilter === 'all' || String(run.project_id) === projectFilter;
      return matchesStatus && matchesProject;
    });
  }, [runs, statusFilter, projectFilter]);

  const upcomingRun = useMemo(() => findNearestUpcomingRun(projects, runs), [projects, runs]);

  return (
    <div className="admin-page-shell">
      <div className="admin-page-header">
        <div>
          <div className="admin-page-kicker">
            <Database size={14} /> Pipeline history
          </div>
          <h1 className="admin-page-title">Pipeline Runs</h1>
          <p className="admin-page-subtitle">
            Independent history view for scraper and enrich jobs.
          </p>
        </div>

        <div className="admin-page-toolbar">
          <button className="btn-secondary" onClick={() => loadRuns()} disabled={loading}>
            <RefreshCw size={16} /> Refresh
          </button>
          <Link to="/dashboard" className="btn-secondary" style={{ textDecoration: 'none' }}>
            Back to Dashboard
          </Link>
        </div>
      </div>

      <div className="admin-toolbar-row">
        <select
          className="filter-select"
          value={projectFilter}
          onChange={(e) => setProjectFilter(e.target.value)}
        >
          <option value="all">All projects</option>
          {projectFilterOptions.map((option) => (
            <option key={option.id} value={String(option.id)}>
              {option.name}
            </option>
          ))}
        </select>

        <select
          className="filter-select"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          {statusOptionsInRuns.map((option) => (
            <option key={option} value={option}>
              {option === 'all' ? 'All statuses' : option[0].toUpperCase() + option.slice(1)}
            </option>
          ))}
        </select>
      </div>

      {error ? (
        <div className="glass-card" style={{ color: '#b42318', borderLeft: '4px solid #ff4757', marginBottom: 18 }}>
          {error}
        </div>
      ) : null}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {upcomingRun ? (
          <motion.div
            className="glass-card"
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: 10,
              border: '1px dashed rgba(255, 107, 53, 0.4)',
              background: 'rgba(255, 107, 53, 0.05)',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              <strong style={{ fontSize: '0.98rem' }}>{upcomingRun.project.name || `Project #${upcomingRun.project.id}`}</strong>
              <span style={{ color: '#ff6b35', fontSize: '0.8rem', textTransform: 'uppercase', fontWeight: 700, display: 'flex', alignItems: 'center', gap: 6 }}>
                <CalendarClock size={14} /> Upcoming
              </span>
            </div>
            <div style={{ fontSize: '0.88rem', color: 'var(--text-dark)' }}>
              Scheduled to run {formatCountdown(upcomingRun.nextRunAt)}, at {new Date(upcomingRun.nextRunAt).toLocaleString()}.
            </div>
          </motion.div>
        ) : null}

        {loading ? (
          Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="glass-card" style={{ minHeight: 92, opacity: 0.7, animation: 'pulse 1.3s infinite' }} />
          ))
        ) : filteredRuns.length === 0 ? (
          <div className="admin-empty-state">
            <div className="admin-empty-state-icon">
              <Database size={18} />
            </div>
            <strong>No pipeline runs</strong>
            <span>{runs.length === 0 ? 'No recorded runs yet.' : 'No runs match the current filters.'}</span>
          </div>
        ) : (
          filteredRuns.map((run, i) => (
            <motion.div
              key={run.id}
              className="glass-card"
              initial={{ opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.03 }}
              style={{ display: 'flex', flexDirection: 'column', gap: 10 }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                <strong style={{ fontSize: '0.98rem' }}>{projectNameForRun(run, projectsById)}</strong>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                  <span style={{ color: stageColor(run.status), fontSize: '0.8rem', textTransform: 'uppercase', fontWeight: 700 }}>
                    {run.status}
                  </span>
                  <button
                    className="btn-secondary"
                    onClick={() => setViewingRun(run)}
                    style={{ padding: '6px 10px', fontSize: '0.75rem' }}
                  >
                    View
                  </button>
                  {ACTIVE_STATUSES.includes(run.status) ? (
                    <button
                      className="btn-secondary"
                      onClick={() => stopRun(run.id)}
                      disabled={stoppingId === run.id}
                      style={{ padding: '6px 10px', fontSize: '0.75rem' }}
                    >
                      {stoppingId === run.id ? 'Stopping...' : 'Stop'}
                    </button>
                  ) : null}
                </div>
              </div>
              <div style={{ fontSize: '0.78rem', color: 'var(--text-light)' }}>
                {prettyStage(run.stage)} - {run.message || 'No message'}
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

      <PipelineRunDetailModal
        open={Boolean(viewingRun)}
        runId={viewingRun?.id}
        projectName={viewingRun ? projectNameForRun(viewingRun, projectsById) : ''}
        onClose={() => setViewingRun(null)}
      />
    </div>
  );
}
