import { RefreshCw, FolderKanban, CalendarClock, ChevronRight, Activity, CheckCircle2, AlertCircle, BarChart3 } from 'lucide-react';
import { motion } from 'framer-motion';
import CompetitorPulseCard from './CompetitorPulseCard.jsx';
import StatsOverview from './StatsOverview';
import { REPORT_PERIODS, dominantSentimentFromStats, timeAgo, pipelineRunTitle } from '../lib/appHelpers.js';

// The Reports page, extracted out of App.jsx: everything here used to be a
// closure (App.jsx's renderReportsView) over App's own state - this is the
// same JSX, now driven entirely by props so it can be rendered/tested on its
// own instead of only through the full router tree.
export default function ReportsView({
  projects,
  isLoadingProjects,
  selectedProject,
  selectedProjectId,
  onSelectedProjectIdChange,
  intelligence,
  isLoadingIntelligence,
  intelligenceError,
  lastIntelligenceSyncAt,
  reportPeriod,
  onReportPeriodChange,
  reportRunId,
  onReportRunIdChange,
  projectRuns,
  onRefresh,
}) {
  const hasProjects = projects.length > 0;
  const liveReport = intelligence || {};
  const dominantSentiment = dominantSentimentFromStats(liveReport);
  const totalArticles = Number(liveReport.total) || 0;

  let syncStatus;
  if (intelligenceError) {
    syncStatus = {
      tone: 'error',
      icon: <AlertCircle size={13} />,
      label: 'Sync failed',
      detail: intelligenceError,
    };
  } else if (isLoadingIntelligence) {
    syncStatus = {
      tone: 'loading',
      icon: <RefreshCw size={13} className="spin" />,
      label: 'Syncing',
      detail: 'Fetching latest data...',
    };
  } else {
    syncStatus = {
      tone: 'success',
      icon: <CheckCircle2 size={13} />,
      label: 'Up to date',
      detail: lastIntelligenceSyncAt ? `Updated ${timeAgo(lastIntelligenceSyncAt)}` : 'Not synced yet',
    };
  }

  return (
    <div className="content-shell">
      <header className="report-header">
        <div className="report-header-top">
          <div className="report-heading">
            <span className="report-kicker">
              <BarChart3 size={13} /> Reports
            </span>
            <h2 className="report-title">
              {selectedProject ? selectedProject.name : 'Select a project'}
            </h2>
            <p className="subtitle">
              Sentiment, categories, and audience insights generated from analyzed articles.
            </p>
          </div>

          <div className="report-header-actions">
            <div className="report-project-control">
              <label className="report-project-control-label" htmlFor="reports-project-select">
                <FolderKanban size={13} /> Project scope
              </label>
              <div className="report-project-select-wrap">
                <FolderKanban size={16} aria-hidden="true" />
                <select
                  id="reports-project-select"
                  className="filter-select report-project-select"
                  value={selectedProjectId ?? ''}
                  onChange={(e) => onSelectedProjectIdChange(e.target.value ? Number(e.target.value) : null)}
                  disabled={isLoadingProjects || !hasProjects}
                  aria-label="Project scope for this report"
                >
                  {hasProjects ? (
                    projects.map((project) => (
                      <option key={project.id} value={project.id}>
                        {project.name} ({project.status || 'draft'})
                      </option>
                    ))
                  ) : (
                    <option value="">No projects yet</option>
                  )}
                </select>
              </div>
            </div>

            <button
              type="button"
              className="btn-secondary toolbar-button report-refresh-btn"
              onClick={onRefresh}
              disabled={isLoadingIntelligence || !hasProjects}
              aria-busy={isLoadingIntelligence}
            >
              <RefreshCw size={16} className={isLoadingIntelligence ? 'spin' : ''} />
              {isLoadingIntelligence ? 'Refreshing...' : 'Refresh'}
            </button>
          </div>
        </div>

        <div className="report-filter-row">
          <div className="filter-tabs-shell">
            <div className="filter-tab-buttons filter-mode-toggle" role="tablist" aria-label="Filter type">
              <button
                type="button"
                role="tab"
                aria-selected={!reportRunId}
                className={`source-type-tab ${!reportRunId ? 'active' : ''}`}
                onClick={() => onReportRunIdChange(null)}
              >
                Date range
              </button>
              {projectRuns.length > 0 ? (
                <button
                  type="button"
                  role="tab"
                  aria-selected={!!reportRunId}
                  className={`source-type-tab ${reportRunId ? 'active' : ''}`}
                  onClick={() => onReportRunIdChange(reportRunId || projectRuns[0].id)}
                >
                  Analysis run
                </button>
              ) : null}
            </div>

            <div className="filter-tab-divider" aria-hidden="true" />

            {reportRunId ? (
              projectRuns.length > 3 ? (
                <select
                  className="filter-select filter-run-select"
                  value={reportRunId}
                  onChange={(event) => onReportRunIdChange(event.target.value)}
                  aria-label="Filter by analysis run"
                >
                  {projectRuns.map((run, index) => (
                    <option key={run.id} value={run.id}>{pipelineRunTitle(run, index)}</option>
                  ))}
                </select>
              ) : (
                <div className="filter-tab-buttons scrollable" role="tablist" aria-label="Filter by analysis run">
                  {projectRuns.map((run, index) => (
                    <span key={run.id} className="filter-tab-run-item">
                      {index > 0 ? <ChevronRight size={14} className="filter-tab-arrow" aria-hidden="true" /> : null}
                      <button
                        type="button"
                        role="tab"
                        aria-selected={reportRunId === run.id}
                        className={`source-type-tab ${reportRunId === run.id ? 'active' : ''}`}
                        onClick={() => onReportRunIdChange(run.id)}
                      >
                        {pipelineRunTitle(run, index)}
                      </button>
                    </span>
                  ))}
                </div>
              )
            ) : (
              <div className="filter-tab-buttons" role="tablist" aria-label="Report date range">
                {REPORT_PERIODS.map((period) => (
                  <button
                    key={period.key}
                    type="button"
                    role="tab"
                    aria-selected={reportPeriod === period.key}
                    className={`source-type-tab ${reportPeriod === period.key ? 'active' : ''}`}
                    onClick={() => onReportPeriodChange(period.key)}
                  >
                    {period.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        <ul className="report-summary-chips" aria-label="Report summary">
          <li className="report-chip">
            <FolderKanban size={13} aria-hidden="true" />
            <span className="report-chip-label">Project</span>
            <strong>{selectedProject ? selectedProject.name : 'None selected'}</strong>
          </li>
          <li className="report-chip">
            <Activity size={13} aria-hidden="true" />
            <span className="report-chip-label">Articles analyzed</span>
            <strong>{totalArticles.toLocaleString()}</strong>
          </li>
          <li className="report-chip">
            <BarChart3 size={13} aria-hidden="true" style={{ color: dominantSentiment.color }} />
            <span className="report-chip-label">Dominant sentiment</span>
            <strong style={{ color: dominantSentiment.color }}>{dominantSentiment.label}</strong>
          </li>
          <li className="report-chip">
            <CalendarClock size={13} aria-hidden="true" />
            <span className="report-chip-label">Range</span>
            <strong>
              {reportRunId
                ? pipelineRunTitle(
                    projectRuns.find((run) => run.id === reportRunId),
                    projectRuns.findIndex((run) => run.id === reportRunId),
                  )
                : REPORT_PERIODS.find((period) => period.key === reportPeriod)?.label}
            </strong>
          </li>
          <li
            className={`report-chip report-sync-chip report-sync-${syncStatus.tone}`}
            role="status"
            aria-live="polite"
          >
            {syncStatus.icon}
            <span className="report-chip-label">{syncStatus.label}</span>
            <strong>{syncStatus.detail}</strong>
          </li>
        </ul>
      </header>

      {selectedProject?.mode === 'competitor' ? (
        <CompetitorPulseCard studyId={selectedProject.id} backTo="/reports" backLabel="Back to reports" />
      ) : null}

      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
        <StatsOverview
          intelligence={liveReport}
          scopeLabel={selectedProject ? selectedProject.name : 'no project selected'}
          loading={isLoadingIntelligence}
          error={intelligenceError}
          onRetry={onRefresh}
          project={selectedProject}
          period={reportPeriod}
          runId={reportRunId}
        />
      </motion.div>
    </div>
  );
}
