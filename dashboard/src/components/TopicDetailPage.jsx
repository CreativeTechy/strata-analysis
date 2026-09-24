import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useLocation } from 'react-router-dom';
import { CartesianGrid, Line, LineChart, Tooltip, XAxis, YAxis } from 'recharts';
import {
  ArrowLeft,
  Lightbulb,
  Loader2,
  AlertTriangle,
  Rss,
  ExternalLink,
  Workflow,
  FileText,
  ShieldCheck,
} from 'lucide-react';
import ResponsiveContainer from './ResponsiveChartContainer.jsx';
import { getPipelineRun } from '../api/pipelineRunsApi.js';
import { getArticleAnalysis } from '../api/articlesApi.js';
import { isSyntheticUrl, articleSourceLabel } from '../lib/articleHelpers.jsx';
import { formatDate, formatNumber } from '../lib/i18nFormat.js';
const TYPE_COLORS = { praise: '#16a34a', complaint: '#e11d48', issue: '#e11d48', suggestion: '#f59e0b' };
const ARTICLE_DISPLAY_CAP = 200;

// Bounded, known badge types - the underlying `type` data value is never
// translated itself, only the label shown for it; anything outside this
// fixed set (or missing, defaulting to "issue") falls back to the raw value.
const BADGE_TYPE_KEYS = {
  praise: 'topic.badgeType.praise',
  complaint: 'topic.badgeType.complaint',
  issue: 'topic.badgeType.issue',
  suggestion: 'topic.badgeType.suggestion',
};

function typeColor(type) {
  return TYPE_COLORS[String(type || '').toLowerCase()] || '#64748b';
}

// articleHelpers.jsx isn't owned by this localization pass and its
// articleDate() is an ad hoc toLocaleDateString() wrapper - these use the
// shared, locale-explicit formatDate()/formatNumber() (lib/i18nFormat.js)
// instead, matching the same "—" / raw-value fallbacks the local helpers
// this file used to define had.
function displayDate(value, locale) {
  if (!value) return '—';
  return formatDate(value, locale) || '—';
}

function displayChartDate(value, locale) {
  const formatted = formatDate(value, locale, { month: 'short', day: 'numeric' });
  return formatted || value;
}

function displayLongDate(value, locale) {
  if (!value) return '—';
  return formatDate(value, locale, { month: 'long', day: 'numeric', year: 'numeric' }) || '—';
}

function sourceDate(source) {
  return source?.published || source?.createdAt || null;
}

function TypeBadge({ type, t }) {
  const color = typeColor(type);
  const key = BADGE_TYPE_KEYS[String(type || '').toLowerCase()];
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        padding: '3px 10px',
        borderRadius: 999,
        background: `${color}1f`,
        color,
        fontWeight: 600,
        textTransform: 'capitalize',
        fontSize: '0.75rem',
      }}
    >
      {key ? t(key) : (type || t('topic.badgeType.issue'))}
    </span>
  );
}

export default function TopicDetailPage() {
  const { t, i18n } = useTranslation(['articles', 'common']);
  const locale = i18n.language;
  const location = useLocation();
  const state = location.state;
  const sources = useMemo(() => (Array.isArray(state?.sources) ? state.sources : []), [state]);

  const distinctRunIds = useMemo(
    () => [...new Set(sources.map((source) => source.pipelineRunId).filter(Boolean))],
    [sources]
  );
  const unattributedCount = sources.length - sources.filter((source) => source.pipelineRunId).length;

  const [runDetails, setRunDetails] = useState({});

  useEffect(() => {
    if (!distinctRunIds.length) return undefined;
    let cancelled = false;
    distinctRunIds.forEach((runId) => {
      setRunDetails((prev) => ({ ...prev, [runId]: { ...(prev[runId] || {}), loading: true } }));
      getPipelineRun(runId)
        .then((data) => {
          if (!cancelled) setRunDetails((prev) => ({ ...prev, [runId]: { run: data?.run || null, loading: false, error: '' } }));
        })
        .catch((err) => {
          if (!cancelled) {
            setRunDetails((prev) => ({ ...prev, [runId]: { run: null, loading: false, error: err?.message || t('topic.pipelineDetailsUnavailable') } }));
          }
        });
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [distinctRunIds.join(',')]);

  const { seriesData, undatedCount } = useMemo(() => {
    const counts = new Map();
    let undated = 0;
    sources.forEach((source) => {
      const raw = sourceDate(source);
      const day = raw ? String(raw).slice(0, 10) : null;
      if (!day || Number.isNaN(new Date(day).getTime())) {
        undated += 1;
        return;
      }
      counts.set(day, (counts.get(day) || 0) + 1);
    });
    const dates = [...counts.keys()].sort();
    return { seriesData: dates.map((date) => ({ date, count: counts.get(date) })), undatedCount: undated };
  }, [sources]);

  const sortedSources = useMemo(
    () => [...sources].sort((a, b) => new Date(sourceDate(b) || 0).getTime() - new Date(sourceDate(a) || 0).getTime()),
    [sources]
  );
  const displayedSources = sortedSources.slice(0, ARTICLE_DISPLAY_CAP);

  // Every displayed article's full analysis (summary/sentiment), fetched up
  // front and shown inline - no click/modal needed to read it.
  const [articleDetails, setArticleDetails] = useState({});
  const displayedArticleIds = useMemo(
    () => displayedSources.map((source) => source.id).filter((id) => id != null),
    [displayedSources]
  );

  useEffect(() => {
    if (!displayedArticleIds.length) return undefined;
    let cancelled = false;
    displayedArticleIds.forEach((id) => {
      setArticleDetails((prev) => ({ ...prev, [id]: { ...(prev[id] || {}), loading: true } }));
      getArticleAnalysis(id, { locale })
        .then((data) => {
          if (!cancelled) setArticleDetails((prev) => ({ ...prev, [id]: { data: data?.analysis || null, loading: false, error: '' } }));
        })
        .catch((err) => {
          if (!cancelled) setArticleDetails((prev) => ({ ...prev, [id]: { data: null, loading: false, error: err?.message || t('topic.failedToLoadArticle') } }));
        });
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [displayedArticleIds.join(','), locale]);

  const totalMentions = sources.length || Number(state?.frequencyEstimate || 0);
  const firstSeen = sortedSources.length ? sourceDate(sortedSources[sortedSources.length - 1]) : null;
  const lastSeen = sortedSources.length ? sourceDate(sortedSources[0]) : null;

  const backTo = state?.backTo || '/dashboard';
  const backLabel = state?.backLabel || t('topic.backToDashboard');

  if (!state || !sources.length) {
    return (
      <div className="admin-page-shell">
        <div className="glass-card admin-empty-state">
          <div className="admin-empty-state-icon">
            <Lightbulb size={18} />
          </div>
          <strong>{t('topic.noTopicSelected')}</strong>
          <span>{t('topic.noTopicHint')}</span>
          <Link to={backTo} className="btn-secondary" style={{ textDecoration: 'none', marginTop: 12 }}>
            <ArrowLeft size={16} className="rtl-mirror" /> {backLabel}
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="admin-page-shell">
      <div className="admin-page-header">
        <div>
          <div className="admin-page-kicker">
            <Lightbulb size={14} /> {t('topic.kicker')}
          </div>
          <h1 className="admin-page-title" dir="auto">{state.idea}</h1>
          <p className="admin-page-subtitle" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <TypeBadge type={state.type} t={t} />
            {state.category ? <span className="admin-tag muted" dir="auto">{state.category}</span> : null}
          </p>
        </div>
        <div className="admin-page-toolbar">
          {state.projectId ? <Link
            to={`/projects/${state.projectId}/evidence?${new URLSearchParams({ ...(distinctRunIds[0] ? { run_id: distinctRunIds[0] } : {}), topic: state.idea }).toString()}`}
            className="btn-secondary"
            style={{ textDecoration: 'none' }}
          >
            <ShieldCheck size={16} /> {t('topic.topicEvidence')}
          </Link> : null}
          <Link to={backTo} className="btn-secondary" style={{ textDecoration: 'none' }}>
            <ArrowLeft size={16} className="rtl-mirror" /> {backLabel}
          </Link>
        </div>
      </div>

      <div className="admin-stats-grid">
        <div className="admin-stat-card">
          <div className="admin-stat-icon" style={{ background: 'rgba(37, 99, 235, 0.14)', color: '#2563eb' }}>
            <Lightbulb size={18} />
          </div>
          <div>
            <span>{t('topic.mentions')}</span>
            <strong>{formatNumber(totalMentions, locale)}</strong>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon" style={{ background: 'rgba(46, 213, 115, 0.14)', color: '#2ed573' }}>
            <Rss size={18} />
          </div>
          <div>
            <span>{t('topic.firstSeen')}</span>
            <strong>{displayDate(firstSeen, locale)}</strong>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon" style={{ background: 'rgba(255, 159, 67, 0.14)', color: 'var(--primary-color)' }}>
            <Rss size={18} />
          </div>
          <div>
            <span>{t('topic.lastSeen')}</span>
            <strong>{displayDate(lastSeen, locale)}</strong>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon" style={{ background: 'rgba(116, 125, 140, 0.14)', color: '#747d8c' }}>
            <Workflow size={18} />
          </div>
          <div>
            <span>{t('topic.analysisRuns')}</span>
            <strong>{formatNumber(distinctRunIds.length, locale)}</strong>
          </div>
        </div>
      </div>

      <div className="glass-card" style={{ marginBottom: 18 }}>
        <h3 className="run-detail-section-title">{t('topic.extractedBy')}</h3>
        {distinctRunIds.length === 0 ? (
          <div className="run-detail-fallback">{t('topic.noAnalysisRun')}</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {distinctRunIds.map((runId) => {
              const detail = runDetails[runId];
              return (
                <div
                  key={runId}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    padding: '10px 14px',
                    borderRadius: 12,
                    background: 'rgba(0,0,0,0.03)',
                    gap: 10,
                  }}
                >
                  {detail?.loading ? (
                    <span style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-light)', fontSize: '0.85rem' }}>
                      <Loader2 size={14} className="spin" /> {t('topic.loadingAnalysisRun')}
                    </span>
                  ) : detail?.error ? (
                    <span style={{ display: 'flex', alignItems: 'center', gap: 6, color: '#b42318', fontSize: '0.85rem' }} dir="auto">
                      <AlertTriangle size={14} /> {detail.error}
                    </span>
                  ) : (
                    <>
                      <span style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.85rem', fontWeight: 600 }}>
                        <Workflow size={15} style={{ color: 'var(--primary-color)' }} />
                        {detail?.run?.sequence_number ? t('topic.analysisNumber', { number: detail.run.sequence_number }) : t('topic.analysisRun')}
                      </span>
                      <span style={{ fontSize: '0.8rem', color: 'var(--text-light)' }}>
                        {displayLongDate(detail?.run?.started_at, locale)}
                      </span>
                    </>
                  )}
                </div>
              );
            })}
            {unattributedCount > 0 ? (
              <span style={{ fontSize: '0.78rem', color: 'var(--text-light)' }}>
                {t('topic.unattributedCount', { count: unattributedCount })}
              </span>
            ) : null}
          </div>
        )}
      </div>

      <div className="glass-card" style={{ marginBottom: 18 }}>
        <h3 className="run-detail-section-title">{t('topic.mentionsOverTime')}</h3>
        {seriesData.length === 0 ? (
          <div className="run-detail-fallback">{t('topic.noDatedArticles')}</div>
        ) : (
          <>
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={seriesData}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(15,23,42,.09)" />
                <XAxis dataKey="date" tickFormatter={(value) => displayChartDate(value, locale)} minTickGap={24} />
                <YAxis allowDecimals={false} />
                <Tooltip labelFormatter={(value) => displayChartDate(value, locale)} formatter={(value) => [`${value}`, t('topic.mentionsTooltipLabel')]} />
                <Line type="monotone" dataKey="count" name={t('topic.mentionsTooltipLabel')} stroke="#2563eb" strokeWidth={2.5} dot={false} />
              </LineChart>
            </ResponsiveContainer>
            {undatedCount > 0 ? (
              <span style={{ fontSize: '0.78rem', color: 'var(--text-light)' }}>
                {t('topic.undatedCount', { count: undatedCount })}
              </span>
            ) : null}
          </>
        )}
      </div>

      <div className="glass-card">
        <h3 className="run-detail-section-title">{t('topic.articlesHeading', { count: formatNumber(sources.length, locale) })}</h3>
        {displayedSources.length === 0 ? (
          <div className="run-detail-fallback">{t('topic.noRepresentativeArticles')}</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {displayedSources.map((source) => {
              const detail = source.id != null ? articleDetails[source.id] : null;
              const sentiment = detail?.data?.sentiment || source.sentiment;
              const rawUrl = detail?.data?.url || source.url;
              const url = isSyntheticUrl(rawUrl) ? null : rawUrl;
              return (
                <div
                  key={source.id ?? source.url}
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 8,
                    padding: '12px 14px',
                    borderRadius: 10,
                    background: 'rgba(0,0,0,0.02)',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, fontSize: '0.84rem' }}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0, fontWeight: 600 }} dir="auto">
                      {source.title || source.url} <FileText size={12} style={{ opacity: 0.5, flexShrink: 0 }} />
                    </span>
                    <span style={{ display: 'flex', alignItems: 'center', gap: 10, color: 'var(--text-light)', flexShrink: 0 }}>
                      {source.source ? <span dir="auto">{articleSourceLabel({ url: rawUrl, source: source.source })}</span> : null}
                      {sentiment ? <span className="admin-tag muted">{sentiment}</span> : null}
                      <span>{displayDate(sourceDate(source), locale)}</span>
                    </span>
                  </div>
                  {detail?.loading ? (
                    <p className="subtitle" style={{ margin: 0 }}>{t('topic.loadingSummary')}</p>
                  ) : detail?.error ? (
                    <p style={{ margin: 0, color: '#b42318', fontSize: '0.82rem' }} dir="auto">{detail.error}</p>
                  ) : detail?.data?.summary ? (
                    <p style={{ margin: 0, lineHeight: 1.5, fontSize: '0.84rem' }} dir="auto">{detail.data.summary}</p>
                  ) : (
                    <p className="subtitle" style={{ margin: 0 }}>{t('topic.noSummaryAvailable')}</p>
                  )}
                  {url ? (
                    <a
                      href={url}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ display: 'inline-flex', alignItems: 'center', gap: 5, alignSelf: 'flex-start', fontSize: '0.8rem', color: 'var(--primary-color)', textDecoration: 'none' }}
                    >
                      {t('topic.viewOriginalArticle')} <ExternalLink size={12} />
                    </a>
                  ) : null}
                </div>
              );
            })}
            {sources.length > displayedSources.length ? (
              <span style={{ fontSize: '0.78rem', color: 'var(--text-light)' }}>
                {t('topic.showingOfArticles', { shown: formatNumber(displayedSources.length, locale), total: formatNumber(sources.length, locale) })}
              </span>
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
}
