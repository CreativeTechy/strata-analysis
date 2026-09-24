import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { motion } from 'framer-motion';
import { Database, Play, RefreshCw, Trash2 } from 'lucide-react';
import ConfirmModal from './ConfirmModal';
import {
  listPipelineRuns, startAnalysisRun, stopPipelineRun, deletePipelineRun,
} from '../api/pipelineRunsApi.js';
import { translateApiError } from '../lib/apiError.js';
import { formatDateTime } from '../lib/i18nFormat.js';

const POLL_INTERVAL_MS = 5000;

function prettyStage(t, stage) {
  if (!stage) return t('shared.stage.queued');
  if (stage === 'done') return t('shared.stage.completed');
  if (stage === 'prepare') return t('shared.stage.selectingArticles');
  if (stage === 'analyze') return t('shared.stage.analyzing');
  if (stage === 'no_work') return t('shared.stage.noAnalysisRequired');
  return stage;
}

function stageColor(status) {
  if (status === 'success') return '#2ed573';
  if (status === 'failed') return '#ff4757';
  if (status === 'running') return '#ffb13b';
  return '#9aa0aa';
}

// queued/running/success/failed/cancelled are stored run-status enum values -
// only the displayed label is translated, reusing common:status.* for the
// two that already match it exactly.
function runStatusLabel(t, status) {
  if (status === 'success') return t('common:status.success');
  if (status === 'failed') return t('common:status.failed');
  return t(`shared.runStatusLabels.${status}`, status);
}

const ACTIVE_STATUSES = ['queued', 'running'];

const STATUS_FILTER_OPTIONS = ['all', 'queued', 'running', 'success', 'failed', 'cancelled'];

// "pending" re-analyzes only what hasn't succeeded yet; "all" re-analyzes
// everything the project holds, which is what you want after switching models.
function buildScopeOptions(t) {
  return [
    { value: 'pending', label: t('runsList.scopeNotYetAnalyzed') },
    { value: 'all', label: t('runsList.scopeEverything') },
  ];
}

function projectNameForRun(run, projectsById, t) {
  if (run.project_name) return run.project_name;
  const project = projectsById.get(Number(run.project_id));
  if (project?.name) return project.name;
  return run.project_id != null ? t('shared.projectFallback', { id: run.project_id }) : t('shared.projectUnassigned');
}

export default function PipelineRunsPage({ projects = [] }) {
  const { t, i18n } = useTranslation(['analysis', 'common']);
  const { t: tErrors } = useTranslation('errors');
  const locale = i18n.language;
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

  const loadRuns = useCallback(async ({ silent = false } = {}) => {
    if (!silent) setLoading(true);
    setError('');
    try {
      const data = await listPipelineRuns({ limit: 25 });
      setRuns(Array.isArray(data?.runs) ? data.runs : []);
    } catch (err) {
      setError(err?.code ? translateApiError(tErrors, err) : (err?.message || t('runsList.loadRunsFailed')));
      setRuns([]);
    } finally {
      if (!silent) setLoading(false);
    }
  }, [t, tErrors]);

  useEffect(() => {
    loadRuns();
    const interval = setInterval(() => loadRuns({ silent: true }), POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [loadRuns]);

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
      setNotice(data?.message || t('runsList.runStartedFallback'));
      await loadRuns();
    } catch (err) {
      setError(err?.code ? translateApiError(tErrors, err) : (err?.message || t('runsList.startRunFailed')));
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
      setError(err?.code ? translateApiError(tErrors, err) : (err?.message || t('runsList.stopRunFailed')));
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
      setNotice(data?.message || t('runsList.runDeletedFallback'));
      await loadRuns();
    } catch (err) {
      setError(err?.code ? translateApiError(tErrors, err) : (err?.message || t('runsList.deleteRunFailed')));
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
      .map((project) => ({ id: Number(project.id), name: project.name || t('shared.projectFallback', { id: project.id }) }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [projects, runs, t]);

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
            <Database size={14} /> {t('runsList.kicker')}
          </div>
          <h1 className="admin-page-title">{t('runsList.title')}</h1>
          <p className="admin-page-subtitle">
            {t('runsList.subtitle')}
          </p>
        </div>

        <div className="admin-page-toolbar">
          <button className="btn-secondary" onClick={() => loadRuns()} disabled={loading}>
            <RefreshCw size={16} /> {t('common:actions.refresh')}
          </button>
          <Link to="/dashboard" className="btn-secondary" style={{ textDecoration: 'none' }}>
            {t('runsList.backToDashboard')}
          </Link>
        </div>
      </div>

      <div className="admin-toolbar-row">
        <select
          className="filter-select"
          value={runProjectId}
          onChange={(e) => setRunProjectId(e.target.value)}
          aria-label={t('runsList.projectToAnalyzeLabel')}
          disabled={!projects.length}
        >
          {projects.length ? (
            projects.map((project) => (
              <option key={project.id} value={String(project.id)}>
                {project.name || t('shared.projectFallback', { id: project.id })}
              </option>
            ))
          ) : (
            <option value="">{t('runsList.noProjectsYet')}</option>
          )}
        </select>

        <select
          className="filter-select"
          value={runScope}
          onChange={(e) => setRunScope(e.target.value)}
          aria-label={t('runsList.scopeSelectLabel')}
        >
          {buildScopeOptions(t).map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>

        <button className="btn-primary" onClick={startRun} disabled={starting || !runProjectId}>
          <Play size={16} /> {starting ? t('runsList.starting') : t('runsList.runAnalysis')}
        </button>
      </div>

      <div className="admin-toolbar-row">
        <select
          className="filter-select"
          value={projectFilter}
          onChange={(e) => setProjectFilter(e.target.value)}
        >
          <option value="all">{t('runsList.allProjects')}</option>
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
              {option === 'all' ? t('runsList.allStatuses') : runStatusLabel(t, option)}
            </option>
          ))}
        </select>
      </div>

      {error ? (
        <div className="glass-card" style={{ color: '#b42318', borderLeft: '4px solid #ff4757', marginBottom: 18 }} dir="auto">
          {error}
        </div>
      ) : null}

      {notice ? (
        <div className="glass-card" style={{ borderLeft: '4px solid #2ed573', marginBottom: 18 }} dir="auto">
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
            <strong>{t('runsList.noRunsTitle')}</strong>
            <span>{runs.length === 0 ? t('runsList.noRecordedRuns') : t('runsList.noRunsMatchFilters')}</span>
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
                <strong style={{ fontSize: '0.98rem' }} dir="auto">{projectNameForRun(run, projectsById, t)}</strong>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                  {run.pipeline === 'competitor-analysis' ? (
                    <span className="panel-chip">{t('runsList.competitorAnalysisChip')}</span>
                  ) : null}
                  {run.pipeline === 'analysis' && run.finished_at && !run.analytics_eligible ? (
                    <span className="panel-chip muted">{t('runsList.noAnalyticalDatasetChip')}</span>
                  ) : null}
                  <span style={{ color: stageColor(run.status), fontSize: '0.8rem', textTransform: 'uppercase', fontWeight: 700 }}>
                    {runStatusLabel(t, run.status)}
                  </span>
                  <Link
                    to={`/pipeline-runs/${run.id}`}
                    className="btn-secondary"
                    style={{ padding: '6px 10px', fontSize: '0.75rem', textDecoration: 'none' }}
                  >
                    {t('common:actions.view')}
                  </Link>
                  {ACTIVE_STATUSES.includes(run.status) ? (
                    <button
                      className="btn-secondary"
                      onClick={() => stopRun(run.id)}
                      disabled={stoppingId === run.id}
                      style={{ padding: '6px 10px', fontSize: '0.75rem' }}
                    >
                      {stoppingId === run.id ? t('runsList.stopping') : t('runsList.stop')}
                    </button>
                  ) : (
                    <button
                      className="btn-secondary"
                      onClick={() => setPendingDelete(run)}
                      disabled={deletingId === run.id}
                      title={t('runsList.deleteTitle')}
                      aria-label={t('runsList.deleteAriaLabel', { project: projectNameForRun(run, projectsById, t) })}
                      style={{ padding: '6px 10px', fontSize: '0.75rem', color: '#b42318' }}
                    >
                      <Trash2 size={14} /> {deletingId === run.id ? t('runsList.deleting') : t('common:actions.delete')}
                    </button>
                  )}
                </div>
              </div>
              <div style={{ fontSize: '0.78rem', color: 'var(--text-light)' }} dir="auto">
                {prettyStage(t, run.stage)} - {run.message || t('runsList.noMessage')}
              </div>
              <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', fontSize: '0.75rem', color: 'var(--text-light)' }}>
                <span>{t('runsList.selectedCount', { count: run.articles_selected || 0 })}</span>
                <span>{t('runsList.analyzedCount', { count: run.articles_analyzed || 0 })}</span>
                <span>{t('runsList.failedCount', { count: run.articles_failed || 0 })}</span>
              </div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-light)' }}>
                {run.created_at ? t('runsList.createdAt', { datetime: formatDateTime(run.created_at, locale) }) : ''}
                {run.finished_at ? ` • ${t('runsList.finishedAt', { datetime: formatDateTime(run.finished_at, locale) })}` : ''}
              </div>
            </motion.div>
          ))
        )}
      </div>

      <ConfirmModal
        open={Boolean(pendingDelete)}
        title={t('runsList.deleteConfirm.title')}
        message={
          pendingDelete
            ? t('runsList.deleteConfirm.message', {
                count: pendingDelete.articles_analyzed || 0,
                sequence: pendingDelete.sequence_number ?? '?',
                project: projectNameForRun(pendingDelete, projectsById, t),
              })
            : ''
        }
        confirmLabel={deletingId ? t('runsList.deleteConfirm.deleting') : t('runsList.deleteConfirm.confirmLabel')}
        confirmButtonStyle={{ background: '#b42318' }}
        onConfirm={() => pendingDelete && deleteRun(pendingDelete.id)}
        onClose={() => setPendingDelete(null)}
      />
    </div>
  );
}
