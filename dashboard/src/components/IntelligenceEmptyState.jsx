import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { AlertTriangle, CalendarRange, FileText, FolderPlus, Hourglass, Loader2, Play, Upload } from 'lucide-react';
import { useAuth } from '../auth/useAuth.js';
import { startAnalysisRun } from '../api/pipelineRunsApi.js';
import { translateApiError } from '../lib/apiError.js';
import { formatNumber } from '../lib/i18nFormat.js';

// Where "upload" / "see the documents" goes differs by project type:
// competitor studies keep their documents under /competitors, opinion-monitor
// projects upload through the project wizard's edit flow (or the Articles
// page's own import, for a user who can import but not edit the project).
function documentLinks(project, hasPermission) {
  if (!project) return { upload: null, review: null };
  if (project.mode === 'competitor') {
    const to = `/competitors/${project.id}/documents`;
    return { upload: hasPermission('competitors.manage') ? to : null, review: to };
  }
  let upload = null;
  if (hasPermission('projects.update')) upload = `/projects/${project.id}/edit`;
  else if (hasPermission('articles.import')) upload = `/articles?project_id=${project.id}`;
  return { upload, review: `/projects/${project.id}` };
}

// Queues a `scope: 'pending'` analysis run (pending + processing + failed
// articles - see pipeline.py's PENDING_STATUSES) for the project, the same
// POST /api/analysis-runs the Analysis Runs page's own button sends.
function useStartAnalysis(project, onStarted) {
  const { t } = useTranslation('dashboard');
  const { t: tErrors } = useTranslation('errors');
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState('');
  const start = async () => {
    if (!project || starting) return;
    setStarting(true);
    setError('');
    try {
      await startAnalysisRun({ project_id: Number(project.id), scope: 'pending' });
      onStarted?.();
    } catch (err) {
      setError(err?.code ? translateApiError(tErrors, err) : (err?.message || t('dashboard:states.analysisPending.startFailed')));
    } finally {
      setStarting(false);
    }
  };
  return { start, starting, error };
}

function StartAnalysisButton({ label, starting, onClick }) {
  const { t } = useTranslation('dashboard');
  return (
    <button type="button" className="btn-primary intelligence-state-action" onClick={onClick} disabled={starting} aria-busy={starting}>
      {starting ? <Loader2 size={15} className="spin" /> : <Play size={15} />}
      {starting ? t('dashboard:states.analysisPending.starting') : label}
    </button>
  );
}

export default function IntelligenceEmptyState({ state, project, rangeLabel, onShowAllTime, onAnalysisStarted }) {
  const { t, i18n } = useTranslation('dashboard');
  const locale = i18n.language;
  const { hasPermission } = useAuth();
  const { start, starting, error: startError } = useStartAnalysis(project, onAnalysisStarted);
  const coverage = state?.coverage || {};
  const links = documentLinks(project, hasPermission);
  const canRun = hasPermission('pipeline.run');

  let tone = 'info';
  let icon = <FileText size={20} />;
  let title;
  let body;
  let actions;
  let hint = null;

  if (state?.kind === 'no_documents') {
    icon = <Upload size={20} />;
    if (state.variant === 'no_articles') {
      title = t('dashboard:states.noDocuments.noArticlesTitle');
      body = t('dashboard:states.noDocuments.noArticlesBody', { count: coverage.documents, formattedCount: formatNumber(coverage.documents, locale) });
    } else {
      title = t('dashboard:states.noDocuments.title');
      body = t('dashboard:states.noDocuments.body');
    }
    actions = <>
      {links.upload ? <Link to={links.upload} className="btn-primary intelligence-state-action"><Upload size={15} />{t('dashboard:states.noDocuments.upload')}</Link> : null}
      {state.variant === 'no_articles' && links.review ? <Link to={links.review} className="btn-secondary intelligence-state-action"><FileText size={15} />{t('dashboard:states.noDocuments.reviewDocuments')}</Link> : null}
    </>;
    if (!links.upload) hint = t('dashboard:states.noDocuments.noPermission');
  } else if (state?.kind === 'analysis_pending') {
    icon = <Hourglass size={20} />;
    const run = coverage.activeRun;
    if (state.variant === 'extracting') {
      title = t('dashboard:states.analysisPending.extractingTitle');
      body = t('dashboard:states.analysisPending.extractingBody', { count: coverage.documentsInProgress, formattedCount: formatNumber(coverage.documentsInProgress, locale) });
      actions = links.review ? <Link to={links.review} className="btn-secondary intelligence-state-action"><FileText size={15} />{t('dashboard:states.noDocuments.reviewDocuments')}</Link> : null;
    } else if (state.variant === 'running') {
      title = t('dashboard:states.analysisPending.runningTitle');
      // No live "X of Y" here: this response is a snapshot, and the run
      // page is where progress updates live.
      body = t('dashboard:states.analysisPending.runningBody');
      actions = run?.id ? <Link to={`/pipeline-runs/${run.id}`} className="btn-primary intelligence-state-action"><Loader2 size={15} className="spin" />{t('dashboard:states.analysisPending.viewRun')}</Link> : null;
    } else if (state.variant === 'queued') {
      title = t('dashboard:states.analysisPending.queuedTitle');
      body = t('dashboard:states.analysisPending.queuedBody', { count: coverage.pending, formattedCount: formatNumber(coverage.pending, locale) });
      actions = canRun
        ? <StartAnalysisButton label={t('dashboard:states.analysisPending.start')} starting={starting} onClick={start} />
        : <Link to="/pipeline-runs" className="btn-secondary intelligence-state-action">{t('dashboard:states.analysisPending.goToRuns')}</Link>;
      if (!canRun) hint = t('dashboard:states.analysisPending.noPermission');
    } else {
      tone = 'error';
      icon = <AlertTriangle size={20} />;
      title = t('dashboard:states.analysisPending.failedTitle');
      body = t('dashboard:states.analysisPending.failedBody', { count: coverage.failed, formattedCount: formatNumber(coverage.failed, locale) });
      actions = <>
        {canRun ? <StartAnalysisButton label={t('dashboard:states.analysisPending.retry')} starting={starting} onClick={start} /> : null}
        <Link to="/analysis" className="btn-secondary intelligence-state-action">{t('dashboard:states.analysisPending.viewLogs')}</Link>
      </>;
    }
  } else if (state?.kind === 'no_results' && state.variant !== 'unknown') {
    icon = <CalendarRange size={20} />;
    if (state.variant === 'run') {
      title = t('dashboard:states.noResults.runTitle');
      body = t('dashboard:states.noResults.runBody');
    } else {
      title = t('dashboard:states.noResults.periodTitle');
      body = t('dashboard:states.noResults.periodBody', { count: coverage.analyzed, formattedCount: formatNumber(coverage.analyzed, locale), range: rangeLabel || '' });
    }
    actions = onShowAllTime ? <button type="button" className="btn-primary intelligence-state-action" onClick={onShowAllTime}><CalendarRange size={15} />{t('dashboard:states.noResults.showAllTime')}</button> : null;
  } else {
    title = t('dashboard:overview.emptyTitle');
    body = t('dashboard:overview.emptyBody');
    actions = <Link to="/pipeline-runs" className="btn-secondary intelligence-state-action">{t('dashboard:report.goToRuns')}</Link>;
  }

  return (
    <div className={`glass-card admin-empty-state intelligence-state intelligence-state-tone-${tone}`} data-state={state?.kind} data-variant={state?.variant}>
      <div className="admin-empty-state-icon">{icon}</div>
      <strong>{title}</strong>
      <p className="subtitle">{body}</p>
      {actions ? <div className="intelligence-state-actions">{actions}</div> : null}
      {hint ? <p className="intelligence-state-hint">{hint}</p> : null}
      {startError ? <p className="intelligence-state-error" role="alert" dir="auto">{startError}</p> : null}
    </div>
  );
}

export function NoProjectsState() {
  const { t } = useTranslation('dashboard');
  const { hasPermission } = useAuth();
  const canCreate = hasPermission('projects.create');
  return (
    <div className="glass-card admin-empty-state intelligence-state" data-state="no_projects">
      <div className="admin-empty-state-icon"><FolderPlus size={20} /></div>
      <strong>{t('dashboard:states.noProjects.title')}</strong>
      <p className="subtitle">{t('dashboard:states.noProjects.body')}</p>
      {canCreate ? (
        <div className="intelligence-state-actions">
          <Link to="/projects/new" className="btn-primary intelligence-state-action"><FolderPlus size={15} />{t('dashboard:states.noProjects.create')}</Link>
        </div>
      ) : <p className="intelligence-state-hint">{t('dashboard:states.noProjects.noPermission')}</p>}
    </div>
  );
}

// Results are on screen, but articles are still queued for (or being put
// through) analysis, or documents are still being split into articles - so
// the figures are about to change. Says so instead of letting a half-analyzed
// project read as final.
export function PendingAnalysisNotice({ state, project, onAnalysisStarted }) {
  const { t, i18n } = useTranslation('dashboard');
  const locale = i18n.language;
  const { hasPermission } = useAuth();
  const { start, starting, error } = useStartAnalysis(project, onAnalysisStarted);
  const coverage = state?.kind === 'ready' ? state.coverage : null;
  if (!coverage || (!coverage.pending && !coverage.documentsInProgress)) return null;

  const message = coverage.pending
    ? t('dashboard:states.pendingNotice.articles', { count: coverage.pending, formattedCount: formatNumber(coverage.pending, locale) })
    : t('dashboard:states.pendingNotice.documents', { count: coverage.documentsInProgress, formattedCount: formatNumber(coverage.documentsInProgress, locale) });
  const run = coverage.activeRun;
  let action = null;
  if (run?.id) {
    action = <Link to={`/pipeline-runs/${run.id}`}>{t('dashboard:states.pendingNotice.viewRun')}</Link>;
  } else if (coverage.pending && hasPermission('pipeline.run')) {
    action = <button type="button" onClick={start} disabled={starting} aria-busy={starting}>
      {starting ? t('dashboard:states.analysisPending.starting') : t('dashboard:states.analysisPending.start')}
    </button>;
  }

  return (
    <div className="intelligence-pending-notice" role="status">
      {run?.id ? <Loader2 size={15} className="spin" aria-hidden="true" /> : <Hourglass size={15} aria-hidden="true" />}
      <span>{message}</span>
      {action}
      {error ? <span className="intelligence-state-error" role="alert" dir="auto">{error}</span> : null}
    </div>
  );
}

function Bar({ width = '100%', height = 12, className = '' }) {
  return <span className={`intelligence-skeleton-bar ${className}`} style={{ width, height }} />;
}

function SkeletonCard({ className = '', children }) {
  return <div className={`glass-card intelligence-card intelligence-skeleton-card ${className}`}>{children}</div>;
}

// Mirrors the Dashboard's real layout (the same grid classes) so the page
// doesn't jump when data lands.
export function DashboardSkeleton() {
  const { t } = useTranslation('dashboard');
  return (
    <div className="intelligence-skeleton" role="status" aria-live="polite" aria-busy="true">
      <span className="sr-only">{t('dashboard:overview.loadingIntelligence')}</span>
      <section className="intelligence-top-grid" aria-hidden="true">
        <SkeletonCard>
          <Bar width="55%" height={14} />
          <div className="intelligence-skeleton-donut" />
          <Bar width="80%" /><Bar width="65%" />
        </SkeletonCard>
        <SkeletonCard>
          <Bar width="40%" height={14} />
          <div className="intelligence-skeleton-chart" />
        </SkeletonCard>
        <SkeletonCard className="intelligence-radar-card">
          <Bar width="60%" height={14} />
          <div className="intelligence-skeleton-donut" />
          <Bar width="90%" />
        </SkeletonCard>
      </section>
      <section className="intelligence-language-grid" aria-hidden="true">
        {[0, 1, 2].map((key) => (
          <SkeletonCard key={key}>
            <Bar width="45%" height={14} />
            <div className="intelligence-skeleton-row">
              <div className="intelligence-skeleton-donut small" />
              <div className="intelligence-skeleton-lines"><Bar /><Bar width="80%" /><Bar width="60%" /></div>
            </div>
          </SkeletonCard>
        ))}
      </section>
    </div>
  );
}

export function MetricValueSkeleton() {
  return <span className="intelligence-skeleton-bar intelligence-skeleton-metric" aria-hidden="true" />;
}

// Same idea for the Reports brief: numbered section shells, not a spinner.
export function ReportSkeleton() {
  const { t } = useTranslation('dashboard');
  return (
    <section className="report-brief intelligence-skeleton" role="status" aria-live="polite" aria-busy="true">
      <span className="sr-only">{t('dashboard:report.loading')}</span>
      <div className="report-brief-section" aria-hidden="true">
        <header><Bar width={32} height={28} /><Bar width="30%" height={16} /></header>
        <Bar width="92%" height={14} /><Bar width="78%" height={14} />
        <div className="report-brief-metrics">
          {[0, 1, 2].map((key) => <div key={key}><Bar width="40%" height={22} /><Bar width="60%" height={10} /></div>)}
        </div>
      </div>
      <div className="report-brief-section" aria-hidden="true">
        <header><Bar width={32} height={28} /><Bar width="26%" height={16} /></header>
        <div className="report-sentiment-grid">
          <div className="intelligence-skeleton-donut" />
          <div className="intelligence-skeleton-lines"><Bar /><Bar width="85%" /><Bar width="70%" /><Bar width="55%" /></div>
        </div>
      </div>
      <div className="report-brief-section" aria-hidden="true">
        <header><Bar width={32} height={28} /><Bar width="22%" height={16} /></header>
        <div className="intelligence-skeleton-chart" />
      </div>
    </section>
  );
}
