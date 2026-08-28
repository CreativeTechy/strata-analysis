import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Database, Play, RefreshCw, Trash2 } from 'lucide-react';
import ConfirmModal from './ConfirmModal';
import {
  listPipelineRuns, startAnalysisRun, stopPipelineRun, deletePipelineRun,
} from '../api/pipelineRunsApi.js';

const POLL_INTERVAL_MS = 5000;

function prettyStage(stage) {
  if (!stage) return 'queued';
  if (stage === 'done') return 'completed';
  if (stage === 'prepare') return 'selecting articles';
  if (stage === 'analyze') return 'analyzing';
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

// "pending" re-analyzes only what hasn't succeeded yet; "all" re-analyzes
// everything the project holds, which is what you want after switching models.
const SCOPE_OPTIONS = [
  { value: 'pending', label: 'Not yet analyzed' },
  { value: 'all', label: 'Everything (re-analyze)' },
];

function projectNameForRun(run, projectsById) {
  if (run.project_name) return run.project_name;
  const project = projectsById.get(Number(run.project_id));
  if (project?.name) return project.name;
  return run.project_id != null ? `Project #${run.project_id}` : 'Unassigned';
}

export default function PipelineRunsPage({ projects = [] }) {
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [stoppingId, setStoppingId] = useState(null);
  const [statusFilter, setStatusFilter] = useState('all');
  const [projectFilter, setProjectFilter] = useState('all');
  const [runProjectId, setRunProjectId] = useState('');
  const [runScope, setRunScope] = useState('pending');
  const [starting, setStarting] = useState(false);
  const [notice, setNotice] = useState('');
  const [pendingDelete, setPendingDelete] = useState(null);
  const [deletingId, setDeletingId] = useState(null);

  const loadRuns = async ({ silent = false } = {}) => {
    if (!silent) setLoading(true);
    setError('');
    try {
      const data = await listPipelineRuns({ limit: 25 });
      setRuns(Array.isArray(data?.runs) ? data.runs : []);
    } catch (err) {
      setError(err?.message || 'Failed to load analysis runs.');
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

  // Default the picker to the first project rather than making the user choose
  // one before the button does anything.
  useEffect(() => {
    if (!runProjectId && projects.length) setRunProjectId(String(projects[0].id));
  }, [projects, runProjectId]);

  const startRun = async () => {
    if (!runProjectId) return;
    setStarting(true);
    setError('');
    setNotice('');
    try {
      const data = await startAnalysisRun({ project_id: Number(runProjectId), scope: runScope });
      setNotice(data?.message || 'Analysis run started.');
      await loadRuns();
    } catch (err) {
      setError(err?.message || 'Failed to start analysis run.');
    } finally {
      setStarting(false);
    }
  };

  const stopRun = async (runId) => {
    setStoppingId(runId);
    try {
      await stopPipelineRun(runId);
      await loadRuns();
    } catch (err) {
      setError(err?.message || 'Failed to stop analysis run.');
    } finally {
      setStoppingId(null);
    }
  };

  // Deletes the run and what was recorded about it - its per-document
  // breakdown and the per-article snapshots the comparison charts read. The
  // articles keep the analysis they currently hold, so this removes a
  // comparison point rather than undoing the run's work.
  const deleteRun = async (runId) => {
    setDeletingId(runId);
    setError('');
    setNotice('');
    try {
      const data = await deletePipelineRun(runId);
      setNotice(data?.message || 'Analysis run deleted.');
      await loadRuns();
    } catch (err) {
      setError(err?.message || 'Failed to delete analysis run.');
    } finally {
      setDeletingId(null);
      setPendingDelete(null);
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

  return (
    <div className="admin-page-shell">
      <div className="admin-page-header">
        <div>
          <div className="admin-page-kicker">
            <Database size={14} /> Analysis history
          </div>
          <h1 className="admin-page-title">Analysis Runs</h1>
          <p className="admin-page-subtitle">
            Every run of the AI analysis over a project's articles, with live progress and per-document results.
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
          value={runProjectId}
          onChange={(e) => setRunProjectId(e.target.value)}
          aria-label="Project to analyze"
          disabled={!projects.length}
        >
          {projects.length ? (
            projects.map((project) => (
              <option key={project.id} value={String(project.id)}>
                {project.name || `Project #${project.id}`}
              </option>
            ))
          ) : (
            <option value="">No projects yet</option>
          )}
        </select>

        <select
          className="filter-select"
          value={runScope}
          onChange={(e) => setRunScope(e.target.value)}
          aria-label="Which articles to analyze"
        >
          {SCOPE_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>

        <button className="btn-primary" onClick={startRun} disabled={starting || !runProjectId}>
          <Play size={16} /> {starting ? 'Starting...' : 'Run analysis'}
        </button>
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

      {notice ? (
        <div className="glass-card" style={{ borderLeft: '4px solid #2ed573', marginBottom: 18 }}>
          {notice}
        </div>
      ) : null}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {loading ? (
          Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="glass-card" style={{ minHeight: 92, opacity: 0.7, animation: 'pulse 1.3s infinite' }} />
          ))
        ) : filteredRuns.length === 0 ? (
          <div className="admin-empty-state">
            <div className="admin-empty-state-icon">
              <Database size={18} />
            </div>
            <strong>No analysis runs</strong>
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
                  {run.pipeline === 'competitor-analysis' ? (
                    <span className="panel-chip">Competitor analysis</span>
                  ) : null}
                  <span style={{ color: stageColor(run.status), fontSize: '0.8rem', textTransform: 'uppercase', fontWeight: 700 }}>
                    {run.status}
                  </span>
                  <Link
                    to={`/pipeline-runs/${run.id}`}
                    className="btn-secondary"
                    style={{ padding: '6px 10px', fontSize: '0.75rem', textDecoration: 'none' }}
                  >
                    View
                  </Link>
                  {ACTIVE_STATUSES.includes(run.status) ? (
                    <button
                      className="btn-secondary"
                      onClick={() => stopRun(run.id)}
                      disabled={stoppingId === run.id}
                      style={{ padding: '6px 10px', fontSize: '0.75rem' }}
                    >
                      {stoppingId === run.id ? 'Stopping...' : 'Stop'}
                    </button>
                  ) : (
                    <button
                      className="btn-secondary"
                      onClick={() => setPendingDelete(run)}
                      disabled={deletingId === run.id}
                      title="Delete this run from the history"
                      aria-label={`Delete analysis run for ${projectNameForRun(run, projectsById)}`}
                      style={{ padding: '6px 10px', fontSize: '0.75rem', color: '#b42318' }}
                    >
                      <Trash2 size={14} /> {deletingId === run.id ? 'Deleting...' : 'Delete'}
                    </button>
                  )}
                </div>
              </div>
              <div style={{ fontSize: '0.78rem', color: 'var(--text-light)' }}>
                {prettyStage(run.stage)} - {run.message || 'No message'}
              </div>
              <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', fontSize: '0.75rem', color: 'var(--text-light)' }}>
                <span>Selected: {run.articles_selected || 0}</span>
                <span>Analyzed: {run.articles_analyzed || 0}</span>
                <span>Failed: {run.articles_failed || 0}</span>
              </div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-light)' }}>
                {run.created_at ? `Created ${new Date(run.created_at).toLocaleString()}` : ''}
                {run.finished_at ? ` • Finished ${new Date(run.finished_at).toLocaleString()}` : ''}
              </div>
            </motion.div>
          ))
        )}
      </div>

      <ConfirmModal
        open={Boolean(pendingDelete)}
        title="Delete this analysis run?"
        message={
          pendingDelete
            ? `Analysis #${pendingDelete.sequence_number ?? '?'} for ${projectNameForRun(pendingDelete, projectsById)} will be removed from the history, along with its per-document breakdown and the results the comparison charts read for it. The ${pendingDelete.articles_analyzed || 0} article(s) it analyzed are kept, and so is the analysis currently stored on them.`
            : ''
        }
        confirmLabel={deletingId ? 'Deleting...' : 'Delete run'}
        confirmButtonStyle={{ background: '#b42318' }}
        onConfirm={() => pendingDelete && deleteRun(pendingDelete.id)}
        onClose={() => setPendingDelete(null)}
      />
    </div>
  );
}
