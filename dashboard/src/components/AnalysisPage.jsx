import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { motion } from 'framer-motion';
import { ScanSearch, RefreshCw, AlertTriangle, CheckCircle2, ChevronLeft, ChevronRight } from 'lucide-react';
import { useAuth } from '../auth/useAuth.js';
import { getAnalysisStatus, listAnalysisErrors, reprocessArticle, analyzeArticles } from '../api/articlesApi.js';
import { translateApiError } from '../lib/apiError.js';
import { formatDateTime, formatNumber, formatPercent } from '../lib/i18nFormat.js';

const STATUS_ORDER = ['success', 'failed', 'processing', 'pending', 'partial'];
const STATUS_COLORS = {
  success: '#2ed573',
  failed: '#ff4757',
  processing: '#ffb13b',
  pending: '#9aa0aa',
  partial: '#f59e0b',
};

// success/failed/processing/pending are stored analysis_status enum values -
// the STATUS_ORDER keys above stay untouched; only the displayed label goes
// through translation, reusing common:status.* where it already matches.
const STATUS_COMMON_KEYS = { success: 'success', failed: 'failed', processing: 'processing', pending: 'pending' };

function statusLabel(t, key) {
  if (STATUS_COMMON_KEYS[key]) return t(`common:status.${STATUS_COMMON_KEYS[key]}`);
  if (key === 'partial') return t('performanceLogs.statusPartial');
  return key;
}

const PAGE_SIZE = 20;

function formatAttemptTimestamp(value, locale, t) {
  if (!value) return t('performanceLogs.notYet');
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return formatDateTime(value, locale) || String(value);
}

export default function AnalysisPage({ projects = [] }) {
  const { t, i18n } = useTranslation(['analysis', 'common']);
  const { t: tErrors } = useTranslation('errors');
  const locale = i18n.language;
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
          setStatusError(err?.code ? translateApiError(tErrors, err) : (err?.message || t('statusLoadFailed')));
        }
      } finally {
        setStatusLoading(false);
      }
    }
    loadStatus();
    return () => controller.abort();
  }, [projectFilter, reloadToken, t, tErrors]);

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
          setErrorsError(err?.code ? translateApiError(tErrors, err) : (err?.message || t('errorsLoadFailed')));
        }
      } finally {
        setErrorsLoading(false);
      }
    }
    loadErrors();
    return () => controller.abort();
  }, [projectFilter, offset, reloadToken, t, tErrors]);

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
      setActionError(err?.code ? translateApiError(tErrors, err) : (err?.message || t('reprocessArticleFailed')));
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
      setActionError(err?.code ? translateApiError(tErrors, err) : (err?.message || t('reprocessSelectedFailed')));
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
            <ScanSearch size={14} /> {t('performanceLogs.kicker')}
          </div>
          <h1 className="admin-page-title">{t('performanceLogs.title')}</h1>
          <p className="admin-page-subtitle">
            {t('performanceLogs.subtitle')}
          </p>
        </div>

        <div className="admin-page-toolbar">
          <button className="btn-secondary" onClick={() => setReloadToken((value) => value + 1)} disabled={statusLoading || errorsLoading}>
            <RefreshCw size={16} /> {t('common:actions.refresh')}
          </button>
          <Link to="/dashboard" className="btn-secondary" style={{ textDecoration: 'none' }}>
            {t('performanceLogs.backToDashboard')}
          </Link>
        </div>
      </div>

      <div className="admin-toolbar-row">
        <select className="filter-select" value={projectFilter} onChange={(e) => setProjectFilter(e.target.value)}>
          <option value="all">{t('performanceLogs.allProjects')}</option>
          {projects.map((project) => (
            <option key={project.id} value={String(project.id)}>
              {project.name}
            </option>
          ))}
        </select>
      </div>

      {statusError ? (
        <div className="glass-card" style={{ color: '#b42318', borderLeft: '4px solid #ff4757', marginBottom: 18 }} dir="auto">
          {t('performanceLogs.statusError', { error: statusError })}
        </div>
      ) : null}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 12, marginBottom: 24 }}>
        {statusLoading && !statusCounts ? (
          Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="glass-card" style={{ minHeight: 84, opacity: 0.7, animation: 'pulse 1.3s infinite' }} />
          ))
        ) : statusEntries.length === 0 ? (
          <div className="glass-card admin-empty-state" style={{ gridColumn: '1 / -1' }}>
            <strong>{t('performanceLogs.noAnalysisDataTitle')}</strong>
            <span>{t('performanceLogs.noAnalysisDataHint')}</span>
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
                {statusLabel(t, entry.key)}
              </div>
              <strong style={{ fontSize: '1.6rem', display: 'block' }}>{formatNumber(entry.count, locale)}</strong>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-light)' }}>
                {totalAnalyzed
                  ? t('performanceLogs.percentOfTotal', {
                      percent: formatPercent(entry.count / totalAnalyzed, locale, { maximumFractionDigits: 0 }),
                      total: formatNumber(totalAnalyzed, locale),
                    })
                  : ''}
              </div>
            </div>
          ))
        )}
      </div>

      <div className="admin-toolbar-row" style={{ justifyContent: 'space-between', flexWrap: 'wrap', gap: 10 }}>
        <div>
          <h2 style={{ fontSize: '1.05rem', margin: 0 }}>{t('performanceLogs.failedAnalysisHeading')}</h2>
          <p className="subtitle" style={{ margin: '4px 0 0' }}>
            {errorsLoading
              ? t('performanceLogs.loadingErrors')
              : t('performanceLogs.articlesNeedAttention', { count: total, formattedCount: formatNumber(total, locale) })
                + (total ? t('performanceLogs.showingRange', { start, end }) : '')}
          </p>
        </div>
        {canReprocess ? (
          <button className="btn-secondary" onClick={reprocessSelected} disabled={selectedIds.length === 0 || reprocessingIds.length > 0}>
            {reprocessingIds.length > 0 && selectedIds.length === 0
              ? t('performanceLogs.reprocessing')
              : t('performanceLogs.reprocessSelected', { count: selectedIds.length })}
          </button>
        ) : null}
      </div>

      {actionError ? (
        <div className="glass-card" style={{ color: '#b42318', borderLeft: '4px solid #ff4757', marginTop: 12, marginBottom: 18 }} dir="auto">
          {actionError}
        </div>
      ) : null}

      {errorsError ? (
        <div className="glass-card" style={{ color: '#b42318', borderLeft: '4px solid #ff4757', marginTop: 12, marginBottom: 18 }} dir="auto">
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
            <strong>{t('performanceLogs.noFailuresTitle')}</strong>
            <span>{t('performanceLogs.noFailuresHint')}</span>
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
                      aria-label={t('performanceLogs.selectArticleLabel', { title: row.title || row.url })}
                    />
                  ) : null}
                  <div>
                    <strong style={{ fontSize: '0.95rem' }} dir="auto">
                      {row.title || row.url || t('performanceLogs.articleFallback', { id: row.id })}
                    </strong>
                    <div style={{ fontSize: '0.78rem', color: 'var(--text-light)' }} dir="auto">
                      {row.source || t('performanceLogs.unknownSource')}
                    </div>
                  </div>
                </div>
                {canReprocess ? (
                  <button
                    className="btn-secondary"
                    onClick={() => reprocessOne(row.id)}
                    disabled={reprocessingIds.includes(row.id)}
                    style={{ padding: '6px 10px', fontSize: '0.75rem' }}
                  >
                    {reprocessingIds.includes(row.id) ? t('performanceLogs.reprocessing') : t('performanceLogs.reprocess')}
                  </button>
                ) : null}
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.8rem', color: '#b42318' }} dir="auto">
                <AlertTriangle size={14} /> {row.analysis_error || t('performanceLogs.unknownError')}
              </div>
              <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', fontSize: '0.75rem', color: 'var(--text-light)' }}>
                <span>{t('performanceLogs.attempts', { count: row.analysis_attempt_count ?? 0 })}</span>
                <span>
                  {t('performanceLogs.lastAttempt', {
                    datetime: formatAttemptTimestamp(row.analysis_finished_at || row.analysis_started_at, locale, t),
                  })}
                </span>
              </div>
            </motion.div>
          ))
        )}
      </div>

      {total > PAGE_SIZE ? (
        <div className="admin-toolbar-row" style={{ justifyContent: 'flex-end', marginTop: 16 }}>
          <button className="btn-secondary" onClick={() => setOffset((prev) => Math.max(0, prev - PAGE_SIZE))} disabled={!hasPrev || errorsLoading}>
            <ChevronLeft size={16} className="rtl-mirror" /> {t('common:actions.previous')}
          </button>
          <button className="btn-secondary" onClick={() => setOffset((prev) => prev + PAGE_SIZE)} disabled={!hasNext || errorsLoading}>
            {t('common:actions.next')} <ChevronRight size={16} className="rtl-mirror" />
          </button>
        </div>
      ) : null}
    </div>
  );
}
