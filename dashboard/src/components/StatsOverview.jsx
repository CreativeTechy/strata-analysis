import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { AlertTriangle, Briefcase, CalendarRange, CircleMinus, FileText, Globe2, Languages, RefreshCw, Tag, ThumbsDown, ThumbsUp, Users } from 'lucide-react';
import { CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, Tooltip, XAxis, YAxis } from 'recharts';
import SearchableSelect from './SearchableSelect';
import DemographicPieCarousel from './DemographicPieCarousel';
import ResponsiveContainer from './ResponsiveChartContainer.jsx';
import VariationFromLastRun from './VariationFromLastRun.jsx';
import { getKeywordExistence, getTrendSummary } from '../api/projectsApi.js';
import { listDocuments } from '../api/projectDocumentsApi.js';
import { SUPPORTED_LOCALES, LOCALE_NATIVE_NAMES, isSupportedLocale, DEFAULT_LOCALE } from '../i18n/locales.js';
import { formatDate as formatLocaleDate, formatNumber, formatPercent } from '../lib/i18nFormat.js';
import '../styles/IntelligenceDashboard.css';

const COLORS = { positive: '#16a34a', neutral: '#64748b', negative: '#e11d48', mixed: '#f59e0b' };
const SENTIMENT_KEYS = ['positive', 'neutral', 'negative', 'mixed'];
// Categorical palette for keyword lines (validated CVD-safe order, see dataviz skill).
const KEYWORD_COLORS = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#e34948'];

function sentimentLabel(t, key) {
  return t(`dashboard:sentiment.${key}`, key);
}

function percent(value, total) { return total ? Math.round((Number(value || 0) / total) * 100) : 0; }
function formatDate(value, locale) {
  const formatted = formatLocaleDate(value, locale, { month: 'short', day: 'numeric' });
  return formatted || value;
}

function Section({ number, title, actions, children }) {
  return <section className="report-brief-section"><header><span>{number}</span><h3>{title}</h3>{actions ? <span className="report-trend-actions">{actions}</span> : null}</header>{children}</section>;
}

// A topic's `sources` come back from the API as {id, url, title,
// pipeline_run_id, published} - snake_case straight off the DB row - so they
// need mapping to camelCase before landing in router state for TopicDetailPage.
function mapTopicSources(sources) {
  return (Array.isArray(sources) ? sources : []).map((source) => ({
    id: source.id,
    url: source.url,
    title: source.title,
    pipelineRunId: source.pipeline_run_id,
    published: source.published,
  }));
}

function FeedbackColumn({ title, icon, tone, items, projectId }) {
  const { t } = useTranslation('dashboard');
  return <article className={`report-feedback-column ${tone}`}><h4>{icon}{title}</h4>{items.length ? <ul>{items.slice(0, 5).map((item) => {
    const label = item.text || item.idea;
    const count = item.count || item.frequency_estimate || 1;
    if (!projectId || !item.sources?.length) {
      return <li key={label} dir="auto">{label}<strong>{count}</strong></li>;
    }
    return <li key={label}>
      <Link
        className="feedback-topic-link"
        to={`/projects/${projectId}/topics`}
        state={{ idea: label, type: item.type, category: item.category, frequencyEstimate: item.frequency_estimate || item.count, sources: mapTopicSources(item.sources), projectId, backTo: '/reports', backLabel: t('dashboard:report.backLabel') }}
        style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 10, width: '100%', color: 'inherit', textDecoration: 'none' }}
        dir="auto"
      >
        {label}<strong>{count}</strong>
      </Link>
    </li>;
  })}</ul> : <p>{t('dashboard:report.feedback.noSignals')}</p>}</article>;
}

export default function StatsOverview({ intelligence = {}, scopeLabel, loading, error, onRetry, project = null, period = 'all', runId = null }) {
  const { t, i18n } = useTranslation(['dashboard', 'reports']);
  const locale = i18n.language;
  const projectId = project?.id ?? null;
  const resolvedScopeLabel = scopeLabel || t('dashboard:report.defaultScope');

  const configuredKeywords = useMemo(
    () => (project?.keywords || []).map((keyword) => String(keyword || '').trim()).filter(Boolean),
    [project]
  );
  const keywordOptions = useMemo(() => configuredKeywords.map((keyword) => ({ value: keyword, label: keyword })), [configuredKeywords]);

  // Articles split out of a document all share that document's synthetic
  // source_url (see project_document_articles._materialize), so the existing
  // source_url filter is exactly a per-document filter here.
  const [documents, setDocuments] = useState([]);
  const documentOptions = useMemo(
    () => documents.map((document) => ({
      value: `document://project-document/${document.id}`,
      label: document.original_filename || t('dashboard:report.keyword.documentFallback', { id: document.id }),
    })),
    [documents, t],
  );

  const [sourceFilter, setSourceFilter] = useState('all');
  const [keywordFilter, setKeywordFilter] = useState('all');
  const [keywordReport, setKeywordReport] = useState(null);
  const [keywordLoading, setKeywordLoading] = useState(false);
  const [keywordError, setKeywordError] = useState(null);

  const [trendSummary, setTrendSummary] = useState(null);
  const [trendSummaryLoading, setTrendSummaryLoading] = useState(false);
  const [trendSummaryError, setTrendSummaryError] = useState(null);
  const [trendSummaryNonce, setTrendSummaryNonce] = useState(0);
  // The trend summary's own output-language choice - deliberately separate
  // state from the interface locale (i18n.language above). It defaults to
  // whatever the interface locale is *at mount*, but once the user (or this
  // default) has set it, switching the interface language later must never
  // silently change it back out from under an already-chosen value (same
  // "interface language / AI output language are separate concepts"
  // principle CLAUDE.md calls out for reanalysis-on-locale-change).
  const [trendSummaryLocale, setTrendSummaryLocale] = useState(
    () => (isSupportedLocale(i18n.language) ? i18n.language : DEFAULT_LOCALE),
  );
  // Set right before bumping trendSummaryNonce from the refresh button, and
  // read (then cleared) inside the effect it triggers - a plain nonce bump
  // from a dependency change (project/period/run switch) must NOT force a
  // fresh LLM call, only the explicit refresh click should.
  const forceRegenerateRef = useRef(false);
  const totalArticles = Number(intelligence?.total || 0);

  useEffect(() => {
    setSourceFilter('all');
    setKeywordFilter('all');
  }, [projectId]);

  useEffect(() => {
    if (projectId == null) {
      setDocuments([]);
      return undefined;
    }
    let cancelled = false;
    listDocuments(projectId)
      .then((data) => { if (!cancelled) setDocuments(Array.isArray(data?.documents) ? data.documents : []); })
      .catch(() => { if (!cancelled) setDocuments([]); });
    return () => { cancelled = true; };
  }, [projectId]);

  useEffect(() => {
    if (projectId == null || configuredKeywords.length === 0) {
      setKeywordReport(null);
      setKeywordError(null);
      setKeywordLoading(false);
      return undefined;
    }
    let cancelled = false;
    setKeywordLoading(true);
    setKeywordError(null);
    getKeywordExistence(projectId, {
      period,
      source_url: sourceFilter !== 'all' ? sourceFilter : undefined,
      keyword: keywordFilter !== 'all' ? keywordFilter : undefined,
      run_id: runId || undefined,
    })
      .then((data) => { if (!cancelled) setKeywordReport(data); })
      .catch((err) => {
        if (!cancelled) {
          console.error('Failed to load keyword existence', err);
          setKeywordReport(null);
          setKeywordError(err?.message || t('dashboard:report.keyword.loadErrorFallback'));
        }
      })
      .finally(() => { if (!cancelled) setKeywordLoading(false); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, period, runId, sourceFilter, keywordFilter, configuredKeywords.length]);

  useEffect(() => {
    if (projectId == null || totalArticles === 0) {
      setTrendSummary(null);
      setTrendSummaryError(null);
      setTrendSummaryLoading(false);
      return undefined;
    }
    let cancelled = false;
    const forceRegenerate = forceRegenerateRef.current;
    forceRegenerateRef.current = false;
    setTrendSummaryLoading(true);
    setTrendSummaryError(null);
    getTrendSummary(projectId, {
      period,
      run_id: runId || undefined,
      regenerate: forceRegenerate ? 'true' : undefined,
      locale: trendSummaryLocale,
    })
      .then(({ ok, data }) => {
        if (cancelled) return;
        if (!ok || data?.error) {
          setTrendSummary(null);
          setTrendSummaryError(data?.error || t('dashboard:report.trendSummaryErrorFallback'));
          return;
        }
        setTrendSummary(data);
      })
      .catch((err) => {
        if (!cancelled) {
          console.error('Failed to load trend summary', err);
          setTrendSummary(null);
          setTrendSummaryError(err?.message || t('dashboard:report.trendSummaryErrorFallback'));
        }
      })
      .finally(() => { if (!cancelled) setTrendSummaryLoading(false); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, period, runId, totalArticles, trendSummaryNonce, trendSummaryLocale]);

  if (loading) return <section className="report-brief glass-card intelligence-loading">{t('dashboard:report.loading')}</section>;
  if (error) return <section className="report-brief"><div className="glass-card admin-empty-state report-error-state" role="alert"><div className="admin-empty-state-icon"><AlertTriangle size={20} /></div><strong>{t('dashboard:report.errorTitle')}</strong><p className="subtitle" dir="auto">{error}</p>{onRetry && <button className="btn-secondary" type="button" onClick={onRetry}>{t('dashboard:report.tryAgain')}</button>}</div></section>;

  const total = totalArticles;
  if (!total) return <section className="report-brief"><div className="glass-card admin-empty-state"><strong>{t('dashboard:report.noArticlesTitle')}</strong><p className="subtitle">{t('dashboard:report.noArticlesBody', { scope: resolvedScopeLabel })}</p><Link to="/pipeline-runs" className="btn-secondary">{t('dashboard:report.goToRuns')}</Link></div></section>;

  const sentiments = SENTIMENT_KEYS.map((name) => ({ name, value: Number(intelligence[name] || 0) }));
  const insights = intelligence.insights || {};
  const leadingIdea = insights.frequent_ideas?.[0]?.idea;
  const leadingConcern = insights.negative_feedback?.[0]?.text || insights.complaints?.[0]?.text;
  const formattedTotal = formatNumber(total, locale);
  const formattedNetSentiment = formatNumber(intelligence.net_sentiment || 0, locale, { signDisplay: 'always', maximumFractionDigits: 0 });
  const headline = leadingIdea
    ? (leadingConcern
      ? t('dashboard:report.headlineWithIdeaConcern', { scope: resolvedScopeLabel, total: formattedTotal, idea: leadingIdea, concern: leadingConcern })
      : t('dashboard:report.headlineWithIdea', { scope: resolvedScopeLabel, total: formattedTotal, idea: leadingIdea }))
    : t('dashboard:report.headlineWithoutIdea', { scope: resolvedScopeLabel, total: formattedTotal, netSentiment: formattedNetSentiment });

  const keywordSeriesData = keywordReport?.series || [];
  const isMultiKeyword = Boolean(keywordReport?.all_keywords);
  const keywordSeriesKeys = isMultiKeyword
    ? (keywordReport?.selected_keywords?.length ? keywordReport.selected_keywords : configuredKeywords)
    : ['matches'];
  const keywordHasMatches = keywordSeriesData.some((point) => keywordSeriesKeys.some((key) => Number(point[key] || 0) > 0));

  return <section className="report-brief">
    <Section
      number="01"
      title={t('dashboard:report.sections.executiveSummary')}
      actions={
        <>
          <label className="report-trend-language-select" title={t('reports:outputLanguage.hint')} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <Languages size={13} aria-hidden="true" />
            <span className="sr-only">{t('reports:outputLanguage.label')}</span>
            <select
              className="filter-select"
              value={trendSummaryLocale}
              onChange={(event) => setTrendSummaryLocale(event.target.value)}
              aria-label={t('reports:outputLanguage.label')}
              style={{ padding: '4px 8px', fontSize: '0.78rem' }}
            >
              {SUPPORTED_LOCALES.map((code) => (
                <option key={code} value={code} lang={code}>{LOCALE_NATIVE_NAMES[code]}</option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="report-trend-refresh-btn"
            onClick={() => { forceRegenerateRef.current = true; setTrendSummaryNonce((n) => n + 1); }}
            disabled={trendSummaryLoading}
            aria-busy={trendSummaryLoading}
            aria-label={t('dashboard:report.regenerateAria')}
            title={t('dashboard:report.regenerateAria')}
          >
            <RefreshCw size={13} className={trendSummaryLoading ? 'spin' : ''} />
          </button>
        </>
      }
    >
      <p className="report-brief-summary" dir="auto">{trendSummary?.summary || headline}</p>
      {trendSummary?.locale_fallback ? <p className="report-trend-summary-status">{t('reports:trendSummary.fallbackNotice')}</p> : null}
      {trendSummaryLoading ? <p className="report-trend-summary-status">{t('dashboard:report.generating')}</p> : null}
      {!trendSummaryLoading && trendSummaryError ? (
        <p className="report-trend-summary-status report-trend-summary-error">
          {t('dashboard:report.generateError')}
        </p>
      ) : null}
      <div className="report-brief-metrics">
        <div><strong>{formattedTotal}</strong><span>{t('dashboard:metrics.analyzedArticles.label')}</span></div>
        <div><strong className={intelligence.net_sentiment >= 0 ? 'positive-text' : 'negative-text'}>{formattedNetSentiment}</strong><span>{t('dashboard:metrics.netSentiment.label')}</span></div>
        <div><strong>{formatNumber(intelligence.document_count || 0, locale)}</strong><span>{t('dashboard:metrics.documents.label')}</span></div>
      </div>
    </Section>

    <VariationFromLastRun projectId={projectId} runId={runId} number="02" />

    <Section number="03" title={t('dashboard:report.sections.sentimentAnalysis')}>
      <div className="report-sentiment-grid"><div className="report-donut"><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={sentiments} dataKey="value" innerRadius="58%" outerRadius="82%" paddingAngle={3} stroke="none">{sentiments.map((entry) => <Cell key={entry.name} fill={COLORS[entry.name]} />)}</Pie><Tooltip formatter={(value, name) => [t('dashboard:counts.articlesCount', { count: value }), sentimentLabel(t, name)]} /></PieChart></ResponsiveContainer></div><div className="report-sentiment-bars">{sentiments.map((entry) => <div key={entry.name}><span><i style={{ background: COLORS[entry.name] }} />{sentimentLabel(t, entry.name)}</span><div><b style={{ width: `${percent(entry.value, total)}%`, background: COLORS[entry.name] }} /></div><strong>{formatPercent(percent(entry.value, total), locale, { alreadyWhole: true })}</strong></div>)}<p>{t('dashboard:report.sentimentNote')}</p></div></div>
    </Section>

    <Section number="04" title={t('dashboard:report.sections.keywordExistence')}>

      {configuredKeywords.length === 0 ? (
        <div className="glass-card admin-empty-state intelligence-keyword-empty">
          <strong>{t('dashboard:report.keyword.noKeywordsTitle')}</strong>
          <p className="subtitle">{t('dashboard:report.keyword.noKeywordsBody', { scope: resolvedScopeLabel })}</p>
          <Link to="/projects" className="btn-secondary">{t('dashboard:report.keyword.manageLink')}</Link>
        </div>
      ) : (
        <>
          <div className="keyword-existence-filters">
            <SearchableSelect
              label={t('dashboard:report.keyword.documentLabel')}
              icon={<FileText size={13} />}
              value={sourceFilter}
              onChange={setSourceFilter}
              options={documentOptions}
              allLabel={t('dashboard:report.keyword.allDocuments')}
              placeholder={t('dashboard:report.keyword.documentPlaceholder')}
              disabled={documentOptions.length === 0}
            />
            <SearchableSelect
              label={t('dashboard:report.keyword.keywordLabel')}
              icon={<Tag size={13} />}
              value={keywordFilter}
              onChange={setKeywordFilter}
              options={keywordOptions}
              allLabel={t('dashboard:report.keyword.allKeywords')}
              placeholder={t('dashboard:report.keyword.keywordPlaceholder')}
            />
          </div>

          {keywordLoading ? (
            <p className="intelligence-empty">{t('dashboard:report.keyword.loading')}</p>
          ) : keywordError ? (
            <div className="glass-card admin-empty-state report-error-state" role="alert">
              <div className="admin-empty-state-icon"><AlertTriangle size={20} /></div>
              <strong>{t('dashboard:report.keyword.errorTitle')}</strong>
              <p className="subtitle" dir="auto">{keywordError}</p>
            </div>
          ) : !keywordHasMatches ? (
            <div className="glass-card admin-empty-state">
              <strong>{t('dashboard:report.keyword.noMatchesTitle')}</strong>
              <p className="subtitle">{t('dashboard:report.keyword.noMatchesBody')}</p>
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={keywordSeriesData}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(15,23,42,.09)" />
                <XAxis dataKey="date" tickFormatter={(value) => formatDate(value, locale)} minTickGap={24} />
                <YAxis allowDecimals={false} />
                <Tooltip labelFormatter={(value) => formatDate(value, locale)} />
                {isMultiKeyword && <Legend />}
                {keywordSeriesKeys.map((key, index) => (
                  <Line
                    key={key}
                    dataKey={key}
                    name={isMultiKeyword ? key : keywordFilter}
                    type="monotone"
                    stroke={isMultiKeyword ? KEYWORD_COLORS[index % KEYWORD_COLORS.length] : '#2563eb'}
                    strokeWidth={2.5}
                    dot={false}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          )}
        </>
      )}
    </Section>

    <Section number="05" title={t('dashboard:report.sections.volumeTrend')}>
      <ResponsiveContainer width="100%" height={285}><LineChart data={intelligence.sentiment_over_time || []}><CartesianGrid strokeDasharray="3 3" stroke="rgba(15,23,42,.09)" /><XAxis dataKey="date" tickFormatter={(value) => formatDate(value, locale)} minTickGap={24} /><YAxis allowDecimals={false} /><Tooltip labelFormatter={(value) => formatDate(value, locale)} /><Legend /><Line dataKey="total" name={t('dashboard:series.total')} type="monotone" stroke="#2563eb" strokeWidth={2.5} dot={false} /><Line dataKey="positive" name={t('dashboard:series.positive')} type="monotone" stroke={COLORS.positive} strokeWidth={2} dot={false} /><Line dataKey="negative" name={t('dashboard:series.negative')} type="monotone" stroke={COLORS.negative} strokeWidth={2} dot={false} /></LineChart></ResponsiveContainer>
    </Section>

    <Section number="06" title={t('dashboard:report.sections.categorizedFeedback')}>
      <div className="report-feedback-grid"><FeedbackColumn title={t('dashboard:report.feedback.positiveDrivers')} icon={<ThumbsUp size={16} />} tone="positive" items={insights.positive_feedback || []} projectId={projectId} /><FeedbackColumn title={t('dashboard:report.feedback.negativeDrivers')} icon={<ThumbsDown size={16} />} tone="negative" items={insights.negative_feedback || []} projectId={projectId} /><FeedbackColumn title={t('dashboard:report.feedback.neutralMixed')} icon={<CircleMinus size={16} />} tone="neutral" items={(insights.frequent_ideas || []).filter((item) => !['praise', 'complaint'].includes(item.type))} projectId={projectId} /></div>
    </Section>

    <Section number="07" title={t('dashboard:report.sections.sentimentByDemographics')}>

      <p className="report-demographics-intro">
        {t('dashboard:report.demographics.intro')}
      </p>
      <div className="report-demographics-grid">
        <div className="report-demographics-block">
          <h4><Users size={16} />{t('dashboard:report.demographics.gender')}</h4>
          <DemographicPieCarousel data={insights.gender_breakdown} emptyLabel={t('dashboard:distributions.gender.empty')} />
        </div>
        <div className="report-demographics-block">
          <h4><Globe2 size={16} />{t('dashboard:report.demographics.region')}</h4>
          <DemographicPieCarousel data={insights.region_breakdown} emptyLabel={t('dashboard:distributions.region.empty')} />
        </div>
        <div className="report-demographics-block">
          <h4><CalendarRange size={16} />{t('dashboard:report.demographics.ageRange')}</h4>
          <DemographicPieCarousel data={insights.age_range_breakdown} emptyLabel={t('dashboard:distributions.ageRange.empty')} />
        </div>
        <div className="report-demographics-block">
          <h4><Briefcase size={16} />{t('dashboard:report.demographics.segment')}</h4>
          <DemographicPieCarousel data={insights.segment_breakdown} emptyLabel={t('dashboard:distributions.segment.empty')} />
        </div>
      </div>
    </Section>
  </section>;
}
