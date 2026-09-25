import { useState } from 'react';
import { RefreshCw, FolderKanban, CalendarClock, ChevronRight, Activity, CheckCircle2, AlertCircle, BarChart3, Download } from 'lucide-react';
import { motion } from 'framer-motion';
import { useTranslation } from 'react-i18next';
import CompetitorPulseCard from './CompetitorPulseCard.jsx';
import StatsOverview from './StatsOverview';
import { exportReportSummaryPdf } from '../api/projectsApi.js';
import { REPORT_PERIODS, SENTIMENT_COLORS, pipelineRunNumber } from '../lib/appHelpers.js';
import { formatNumber, formatPercent, formatRelativeTime } from '../lib/i18nFormat.js';

// Sanitized the same way the backend names the file (main.py's
// export_report_summary_pdf) - not load-bearing for correctness (the
// Content-Disposition header already names it), just avoids a flash of the
// browser's default download name before that header is read.
function safeFileFragment(value) {
  return String(value || '').trim().replace(/[^A-Za-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '') || 'project';
}

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
  const { t, i18n } = useTranslation('reports');
  const locale = i18n.language;
  const hasProjects = projects.length > 0;
  const liveReport = intelligence || {};
  const totalArticles = Number(liveReport.total) || 0;

  // Duplicated (rather than imported from appHelpers.js's
  // dominantSentimentFromStats) because that shared helper bakes in an
  // English label and other in-progress work depends on its current
  // signature - recomputing the same small ranking here keeps this page's
  // translation self-contained without touching a file other areas rely on.
  const dominantSentiment = (() => {
    const total = Number(liveReport.total) || 0;
    if (!total) return { label: t('sentimentLabels.noDataYet'), color: 'var(--text-light)' };
    const entries = ['positive', 'negative', 'neutral', 'mixed'].map((key) => ({
      key, value: Number(liveReport[key]) || 0,
    })).sort((a, b) => b.value - a.value);
    const top = entries[0];
    return {
      label: `${t(`sentimentLabels.${top.key}`)} - ${formatPercent(top.value / total, locale)}`,
      color: SENTIMENT_COLORS[top.key],
    };
  })();

  const runTabLabel = (run, index) => t('runLabel', {
    number: pipelineRunNumber(run, index),
    date: run ? formatDateTimeShort(run) : '',
  });

  function formatDateTimeShort(run) {
    const value = run?.finished_at || run?.created_at;
    if (!value) return '';
    return new Intl.DateTimeFormat(locale === 'ar' ? 'ar-SA-u-nu-latn' : 'en-US', {
      month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
    }).format(new Date(value));
  }

  const [exportingSummary, setExportingSummary] = useState(false);
  const [exportError, setExportError] = useState(null);

  const handleExportSummary = async () => {
    if (exportingSummary || selectedProjectId == null) return;
    setExportingSummary(true);
    setExportError(null);
    try {
      const blob = await exportReportSummaryPdf(selectedProjectId, {
        period: reportPeriod,
        run_id: reportRunId || undefined,
      });
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      const scopeFragment = reportRunId ? `run-${String(reportRunId).slice(0, 8)}` : reportPeriod;
      const dateFragment = new Date().toISOString().slice(0, 10);
      anchor.href = objectUrl;
      anchor.download = `${safeFileFragment(selectedProject?.name)}-summary-${scopeFragment}-${dateFragment}.pdf`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(objectUrl);
    } catch (err) {
      console.error('Failed to export the report summary', err);
      setExportError({ detail: err?.detail || null });
    } finally {
      setExportingSummary(false);
    }
  };

  let syncStatus;
  if (intelligenceError) {
    syncStatus = {
      tone: 'error',
      icon: <AlertCircle size={13} />,
      label: t('summaryChips.syncFailed'),
      detail: intelligenceError,
    };
  } else if (isLoadingIntelligence) {
    syncStatus = {
      tone: 'loading',
      icon: <RefreshCw size={13} className="spin" />,
      label: t('summaryChips.syncing'),
      detail: t('summaryChips.fetchingLatestData'),
    };
  } else {
    syncStatus = {
      tone: 'success',
      icon: <CheckCircle2 size={13} />,
      label: t('summaryChips.upToDate'),
      detail: lastIntelligenceSyncAt
        ? t('summaryChips.updatedAgo', { time: formatRelativeTime(lastIntelligenceSyncAt, locale) })
        : t('summaryChips.notSyncedYet'),
    };
  }

  return (
    <div className="content-shell">
      <header className="report-header">
        <div className="report-header-top">
          <div className="report-heading">
            <span className="report-kicker">
              <BarChart3 size={13} /> {t('header.kicker')}
            </span>
            <h2 className="report-title" dir="auto">
              {selectedProject ? selectedProject.name : t('header.selectProjectTitle')}
            </h2>
            <p className="subtitle">
              {t('header.subtitle')}
            </p>
          </div>

          <div className="report-header-actions">
            <div className="report-project-control">
              <label className="report-project-control-label" htmlFor="reports-project-select">
                <FolderKanban size={13} /> {t('header.projectScopeLabel')}
              </label>
              <div className="report-project-select-wrap">
                <FolderKanban size={16} aria-hidden="true" />
                <select
                  id="reports-project-select"
                  className="filter-select report-project-select"
                  value={selectedProjectId ?? ''}
                  onChange={(e) => onSelectedProjectIdChange(e.target.value ? Number(e.target.value) : null)}
                  disabled={isLoadingProjects || !hasProjects}
                  aria-label={t('header.projectScopeAriaLabel')}
                >
                  {hasProjects ? (
                    projects.map((project) => (
                      <option key={project.id} value={project.id}>
                        {project.name} ({t(`projects:shared.statusLabels.${project.status || 'draft'}`, project.status || 'draft')})
                      </option>
                    ))
                  ) : (
                    <option value="">{t('header.noProjectsYet')}</option>
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
              {isLoadingIntelligence ? t('header.refreshing') : t('header.refresh')}
            </button>

            <button
              type="button"
              className="btn-secondary toolbar-button report-export-summary-btn"
              onClick={handleExportSummary}
              disabled={exportingSummary || !hasProjects || selectedProjectId == null || !totalArticles}
              aria-busy={exportingSummary}
              title={!totalArticles ? t('export.noArticlesTitle') : t('export.title')}
            >
              <Download size={16} className={exportingSummary ? 'spin' : ''} />
              {exportingSummary ? t('export.preparing') : t('export.button')}
            </button>
          </div>
        </div>

        {exportError ? (
          <p className="report-export-summary-error" role="alert">
            <AlertCircle size={13} aria-hidden="true" /> {t('export.failed')}
            {exportError.detail ? <span dir="auto"> {exportError.detail}</span> : null}
          </p>
        ) : null}

        <div className="report-filter-row">
          <div className="filter-tabs-shell">
            <div className="filter-tab-buttons filter-mode-toggle" role="tablist" aria-label={t('header.filterTypeAriaLabel')}>
              <button
                type="button"
                role="tab"
                aria-selected={!reportRunId}
                className={`source-type-tab ${!reportRunId ? 'active' : ''}`}
                onClick={() => onReportRunIdChange(null)}
              >
                {t('header.dateRangeTab')}
              </button>
              {projectRuns.length > 0 ? (
                <button
                  type="button"
                  role="tab"
                  aria-selected={!!reportRunId}
                  className={`source-type-tab ${reportRunId ? 'active' : ''}`}
                  onClick={() => onReportRunIdChange(reportRunId || projectRuns[0].id)}
                >
                  {t('header.analysisRunTab')}
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
                  aria-label={t('header.runFilterAriaLabel')}
                >
                  {projectRuns.map((run, index) => (
                    <option key={run.id} value={run.id}>{runTabLabel(run, index)}</option>
                  ))}
                </select>
              ) : (
                <div className="filter-tab-buttons scrollable" role="tablist" aria-label={t('header.runFilterAriaLabel')}>
                  {projectRuns.map((run, index) => (
                    <span key={run.id} className="filter-tab-run-item">
                      {index > 0 ? <ChevronRight size={14} className="filter-tab-arrow rtl-mirror" aria-hidden="true" /> : null}
                      <button
                        type="button"
                        role="tab"
                        aria-selected={reportRunId === run.id}
                        className={`source-type-tab ${reportRunId === run.id ? 'active' : ''}`}
                        onClick={() => onReportRunIdChange(run.id)}
                      >
                        {runTabLabel(run, index)}
                      </button>
                    </span>
                  ))}
                </div>
              )
            ) : (
              <div className="filter-tab-buttons" role="tablist" aria-label={t('header.dateRangeFilterAriaLabel')}>
                {REPORT_PERIODS.map((period) => (
                  <button
                    key={period.key}
                    type="button"
                    role="tab"
                    aria-selected={reportPeriod === period.key}
                    className={`source-type-tab ${reportPeriod === period.key ? 'active' : ''}`}
                    onClick={() => onReportPeriodChange(period.key)}
                  >
                    {t(`periods.${period.key}`)}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        <ul className="report-summary-chips" aria-label={t('summaryChips.ariaLabel')}>
          <li className="report-chip">
            <FolderKanban size={13} aria-hidden="true" />
            <span className="report-chip-label">{t('summaryChips.project')}</span>
            <strong dir="auto">{selectedProject ? selectedProject.name : t('summaryChips.noneSelected')}</strong>
          </li>
          <li className="report-chip">
            <Activity size={13} aria-hidden="true" />
            <span className="report-chip-label">{t('summaryChips.articlesAnalyzed')}</span>
            <strong>{formatNumber(totalArticles, locale)}</strong>
          </li>
          <li className="report-chip">
            <BarChart3 size={13} aria-hidden="true" style={{ color: dominantSentiment.color }} />
            <span className="report-chip-label">{t('summaryChips.dominantSentiment')}</span>
            <strong style={{ color: dominantSentiment.color }}>{dominantSentiment.label}</strong>
          </li>
          <li className="report-chip">
            <CalendarClock size={13} aria-hidden="true" />
            <span className="report-chip-label">{t('summaryChips.range')}</span>
            <strong>
              {reportRunId
                ? runTabLabel(
                    projectRuns.find((run) => run.id === reportRunId),
                    projectRuns.findIndex((run) => run.id === reportRunId),
                  )
                : t(`periods.${reportPeriod}`)}
            </strong>
          </li>
          <li
            className={`report-chip report-sync-chip report-sync-${syncStatus.tone}`}
            role="status"
            aria-live="polite"
          >
            {syncStatus.icon}
            <span className="report-chip-label">{syncStatus.label}</span>
            <strong dir="auto">{syncStatus.detail}</strong>
          </li>
        </ul>
      </header>

      {selectedProject?.mode === 'competitor' ? (
        <CompetitorPulseCard studyId={selectedProject.id} backTo="/reports" backLabel={t('backToReports')} />
      ) : null}

      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
        <StatsOverview
          intelligence={liveReport}
          scopeLabel={selectedProject ? selectedProject.name : t('noProjectSelectedScope')}
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
