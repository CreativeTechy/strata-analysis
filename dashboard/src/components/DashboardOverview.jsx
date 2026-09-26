import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useLocation } from 'react-router-dom';
import {
  Activity, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight, ExternalLink, FileText, Gauge, Layers, Lightbulb, Loader2, Network,
  RefreshCw, Scale, Sparkles, TrendingDown, TrendingUp,
} from 'lucide-react';
import {
  CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, Radar, RadarChart,
  PolarAngleAxis, PolarGrid, PolarRadiusAxis, ReferenceLine, Tooltip, XAxis, YAxis,
} from 'recharts';
import '../styles/IntelligenceDashboard.css';
import CompetitorPulseCard from './CompetitorPulseCard.jsx';
import IntelligenceEmptyState, { DashboardSkeleton, MetricValueSkeleton, NoProjectsState, PendingAnalysisNotice } from './IntelligenceEmptyState.jsx';
import ResponsiveContainer from './ResponsiveChartContainer.jsx';
import { getIdeaComparisons } from '../api/projectsApi.js';
import { isIntelligenceStale, resolveIntelligenceState } from '../lib/intelligenceState.js';
import { formatDate as formatLocaleDate, formatLanguageName, formatNumber, formatPercent, formatTime } from '../lib/i18nFormat.js';

const IDEA_COMPARISONS_PAGE_SIZE = 3;
const PLATFORM_LIST_PAGE_SIZE = 5;
const PERIODS = [
  { key: '7d', labelKey: 'dashboard:periods.last7d' },
  { key: '30d', labelKey: 'dashboard:periods.last30d' },
  { key: 'all', labelKey: 'dashboard:periods.allTime' },
];
const SENTIMENT_COLORS = { positive: '#16a34a', neutral: '#64748b', negative: '#e11d48', mixed: '#f59e0b' };
const SENTIMENT_KEYS = ['positive', 'neutral', 'negative', 'mixed'];
// Categorical palette for language slices (open-ended set, unlike the fixed 4 sentiments) -
// same validated CVD-safe order used for keyword lines in StatsOverview.jsx.
const LANGUAGE_COLORS = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#e34948'];
// Same offline trust tiers source_trust.py resolves - order matches the
// Sources tab's own tier order (trusted -> mixed -> untrusted -> unknown).
const TRUST_TIER_ORDER = ['trusted', 'mixed', 'untrusted', 'unknown'];
const TRUST_TIER_COLORS = { trusted: '#16a34a', mixed: '#f59e0b', untrusted: '#e11d48', unknown: '#64748b' };
// Idea types (see analysis/normalize.py's _FREQUENT_IDEA_TYPES) that count as
// a concern for the first-screen "Top concerns" card; praise/suggestion stay
// reachable through that card's "All ideas" tab.
const CONCERN_IDEA_TYPES = new Set(['issue', 'complaint']);
const TOP_IDEAS_LIMIT = 6;
// Per-viewer memory of whether the "Detailed breakdowns" area is expanded -
// collapsed by default so the first screen stays on the key signals.
const DETAILED_BREAKDOWNS_STORAGE_KEY = 'dashboard-detailed-breakdowns-open';

// SENTIMENT_KEYS/idea "type"/EMOTION_AXES are fixed, small enums, so they go
// through a real translation lookup (object keys stay the untranslated code -
// see dashboard.json's sentiment.*/ideaType.*/emotionAxis.*); region/gender/
// age/language buckets below are open-ended DB text and stay a plain
// capitalize transform instead (see distributionLabel()).
function sentimentLabel(t, key) {
  return t(`dashboard:sentiment.${key}`, key);
}

function ideaTypeLabel(t, type) {
  const value = type || 'issue';
  return t(`dashboard:ideaType.${value}`, value);
}

function emotionAxisLabel(t, axis) {
  const fallback = axis ? axis.charAt(0).toUpperCase() + axis.slice(1) : axis;
  return t(`dashboard:emotionAxis.${axis}`, fallback);
}

function languageLabel(t, locale, code) {
  if (!code || code === 'unknown') return t('dashboard:distributions.language.unknown');
  if (code === 'other') return t('dashboard:distributions.language.other');
  const name = formatLanguageName(code, locale);
  return name ? `${name} (${code.toUpperCase()})` : code.toUpperCase();
}

// Labels the demographic breakdown APIs' bucket values (region/gender/age_range)
// - see backend/services/articles/articles_store.py's _demographic_sentiment_breakdown.
// Open-ended DB text, so this stays a plain transform rather than a
// translation lookup - except the "other"/"unknown" buckets, which the app
// itself generates (capBreakdown() below, or a missing value) and so do
// have a fixed translation.
function distributionLabel(t, value) {
  const key = String(value || 'unknown');
  if (key === 'other' || key === 'unknown') return t(`dashboard:distributions.bucket.${key}`);
  return key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

// Same fixed tiers (and labels) the Sources tab uses - see sources.json's
// trustTier.* and TRUST_TIER_ORDER above.
function trustTierLabel(t, tier) {
  return t(`sources:trustTier.${tier}`, tier);
}

// queued/running/success/failed/cancelled are stored run-status enum values;
// same label lookup PipelineRunsPage.jsx's runStatusLabel() uses.
function runStatusLabel(t, status) {
  if (status === 'success') return t('common:status.success');
  if (status === 'failed') return t('common:status.failed');
  return t(`analysis:shared.runStatusLabels.${status}`, status);
}

// region/gender/age_range/segment are all open-ended text buckets, so every
// distribution pie is capped to the top `limit` buckets (already sorted desc
// by the backend) with the long tail folded into one "other" bucket, rather
// than letting a chart grow unbounded as the taxonomy grows.
function capBreakdown(entries, limit = 7) {
  if (entries.length <= limit) return entries;
  const rest = entries.slice(limit);
  const other = rest.reduce((acc, entry) => ({
    value: 'other',
    total: acc.total + Number(entry.total || 0),
    positive: acc.positive + Number(entry.positive || 0),
    negative: acc.negative + Number(entry.negative || 0),
    neutral: acc.neutral + Number(entry.neutral || 0),
    mixed: acc.mixed + Number(entry.mixed || 0),
  }), { value: 'other', total: 0, positive: 0, negative: 0, neutral: 0, mixed: 0 });
  return [...entries.slice(0, limit), other];
}

// Same idea as capBreakdown() above but for language_breakdown's {language,
// count} shape, which carries no sentiment split to fold together.
function capLanguageBreakdown(entries, limit = 7) {
  if (entries.length <= limit) return entries;
  const rest = entries.slice(limit);
  const otherCount = rest.reduce((sum, entry) => sum + Number(entry.count || 0), 0);
  return [...entries.slice(0, limit), { language: 'other', count: otherCount }];
}

function percent(value, total) {
  return total ? Math.round((Number(value || 0) / total) * 100) : 0;
}

function formatDate(value, locale) {
  const formatted = formatLocaleDate(value, locale, { month: 'short', day: 'numeric' });
  return formatted || value;
}

function Change({ value }) {
  const { t, i18n } = useTranslation('dashboard');
  if (value == null) return <span className="intelligence-change neutral">{t('dashboard:change.firstRun')}</span>;
  const positive = value >= 0;
  const Icon = positive ? TrendingUp : TrendingDown;
  const formattedValue = formatNumber(value, i18n.language, { signDisplay: 'always', maximumFractionDigits: 0 });
  return <span className={`intelligence-change ${positive ? 'positive' : 'negative'}`}><Icon size={13} />{t('dashboard:change.vsPrevious', { value: formattedValue })}</span>;
}

function MetricCard({ icon, label, value, detail, tone = 'blue' }) {
  return <article className={`intelligence-metric intelligence-metric-${tone}`}>
    <span className="intelligence-metric-icon">{icon}</span>
    <div><span className="intelligence-metric-label">{label}</span><strong>{value}</strong>{detail && <small>{detail}</small>}</div>
  </article>;
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

function IdeaRow({ idea, maxFrequency, projectId }) {
  const { t, i18n } = useTranslation('dashboard');
  const body = <>
    <div><strong dir="auto">{idea.idea}</strong><span>{ideaTypeLabel(t, idea.type)}</span></div>
    <strong>{formatNumber(idea.frequency_estimate || 0, i18n.language)}</strong>
    <div className="intelligence-track"><span style={{ width: `${Math.max(8, percent(idea.frequency_estimate, maxFrequency))}%` }} /></div>
  </>;
  if (projectId && idea.sources?.length) {
    return <Link
      className={`intelligence-idea intelligence-idea-clickable ${idea.type || 'issue'}`}
      style={{ textDecoration: 'none', color: 'inherit' }}
      to={`/projects/${projectId}/topics`}
      state={{ idea: idea.idea, type: idea.type, category: idea.category, frequencyEstimate: idea.frequency_estimate, sources: mapTopicSources(idea.sources), projectId, backTo: '/dashboard', backLabel: t('dashboard:ideas.backLabel') }}
    >
      {body}
    </Link>;
  }
  return <div className={`intelligence-idea ${idea.type || 'issue'}`}>{body}</div>;
}

// One donut + legend card for a single distribution (language, region,
// gender, ...). `nameKey` is the bucket field, `valueKey` the count field,
// and `valueTotal` the denominator the legend percentages are taken against.
function DistributionCard({ title, entries, nameKey, valueKey, valueTotal, colorFor, labelFor, emptyText }) {
  const { t, i18n } = useTranslation('dashboard');
  const locale = i18n.language;
  return <article className="glass-card intelligence-card intelligence-language-card">
    <h3>{title}</h3>
    {entries.length ? (
      <div className="intelligence-language-layout">
        <div className="intelligence-donut">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={entries} dataKey={valueKey} nameKey={nameKey} outerRadius="92%" paddingAngle={3} stroke="none">
                {entries.map((entry, index) => <Cell key={entry[nameKey]} fill={colorFor(entry, index)} />)}
              </Pie>
              <Tooltip formatter={(value, name) => [t('dashboard:counts.articlesCount', { count: value }), labelFor(name)]} />
            </PieChart>
          </ResponsiveContainer>
        </div>
        <div className="intelligence-legend">
          {entries.map((entry, index) => (
            <div key={entry[nameKey]}>
              <span style={{ background: colorFor(entry, index) }} />
              <label>{labelFor(entry[nameKey])}</label>
              <strong>{formatPercent(percent(entry[valueKey], valueTotal), locale, { alreadyWhole: true })}</strong>
            </div>
          ))}
        </div>
      </div>
    ) : <p className="intelligence-empty">{emptyText}</p>}
  </article>;
}

function paletteColor(entry, index) {
  return LANGUAGE_COLORS[index % LANGUAGE_COLORS.length];
}

function formatRunLabel(run, locale, t) {
  const value = run?.finished_at || run?.created_at;
  const date = value ? new Date(value) : null;
  if (!date || Number.isNaN(date.getTime())) return t('dashboard:runLabel.fallback');
  return `${formatLocaleDate(date, locale, { month: 'short', day: 'numeric' })} ${formatTime(date, locale)}`;
}

// sequence_number is this project's Nth analysis run ever (oldest = 1),
// computed server-side so it stays fixed regardless of how many runs are in
// the currently-fetched list or what order they're shown in. `index` is only
// a fallback for the rare case a run has no sequence_number (e.g. a
// competitor-analysis pipeline row).
function pipelineRunNumber(run, index) {
  return run?.sequence_number ?? (index + 1);
}

// Full label (with date/time) for the tab list, where several runs are
// shown side by side and the date disambiguates them at a glance.
function pipelineRunTitle(run, index, locale, t) {
  return t('dashboard:runLabel.title', { number: pipelineRunNumber(run, index), label: formatRunLabel(run, locale, t) });
}

// Compact label for summary spots (metric cards, the "showing run" note)
// where the number alone is already unambiguous and a repeated date/time is
// just clutter.
function pipelineRunShortLabel(run, index, t) {
  return t('dashboard:runLabel.short', { number: pipelineRunNumber(run, index) });
}

export default function DashboardOverview({
  projects, selectedProjectId, onProjectChange, period, onPeriodChange, intelligence,
  loading, error, pipelineHealth, runs = [], selectedRunId, onRunChange,
  isLoadingProjects = false, onRefresh,
}) {
  const { t, i18n } = useTranslation(['dashboard', 'common']);
  const locale = i18n.language;
  const location = useLocation();
  const data = intelligence || {};
  const total = Number(data.total || 0);
  const sentimentData = SENTIMENT_KEYS.map((name) => ({ name, value: Number(data[name] || 0) }));
  const latestRun = data.pipeline_discovery?.[data.pipeline_discovery.length - 1];
  const platformData = data.platforms || [];
  const sortedPlatformData = useMemo(
    () => [...platformData].sort((a, b) => b.total - a.total),
    [platformData],
  );
  const languageData = capLanguageBreakdown(data.insights?.language_breakdown || []);
  const regionData = capBreakdown((data.insights?.region_breakdown || []).filter((entry) => entry.total > 0));
  const genderData = capBreakdown((data.insights?.gender_breakdown || []).filter((entry) => entry.total > 0));
  const trustTiers = data.source_trust?.tiers || {};
  const trustData = TRUST_TIER_ORDER
    .map((tier) => ({ tier, articles: trustTiers[tier]?.articles || 0, sources: trustTiers[tier]?.sources || 0 }))
    .filter((entry) => entry.articles > 0);
  const ageRangeData = capBreakdown((data.insights?.age_range_breakdown || []).filter((entry) => entry.total > 0));
  const segmentData = capBreakdown((data.insights?.segment_breakdown || []).filter((entry) => entry.total > 0));
  const selectedProject = useMemo(() => projects.find((project) => Number(project.id) === Number(selectedProjectId)), [projects, selectedProjectId]);
  const selectedRunIndex = selectedRunId ? runs.findIndex((run) => run.id === selectedRunId) : -1;
  const selectedRun = selectedRunIndex >= 0 ? runs[selectedRunIndex] : null;
  const isStale = isIntelligenceStale(intelligence, selectedProjectId);
  const showLoading = !error && (loading || isStale);
  const scopeState = resolveIntelligenceState(intelligence);
  const isReady = !showLoading && scopeState.kind === 'ready';
  const periodLabel = t(PERIODS.find((item) => item.key === period)?.labelKey || '');

  const [ideaComparisons, setIdeaComparisons] = useState([]);
  const [ideaComparisonsLoading, setIdeaComparisonsLoading] = useState(false);
  const [ideaComparisonsError, setIdeaComparisonsError] = useState('');
  const [ideaComparisonsRegenerating, setIdeaComparisonsRegenerating] = useState(false);
  const [ideaComparisonsNonce, setIdeaComparisonsNonce] = useState(0);
  const [ideaComparisonsPage, setIdeaComparisonsPage] = useState(0);
  const [platformListPage, setPlatformListPage] = useState(0);
  const [ideaFilter, setIdeaFilter] = useState('concerns');
  const [detailedBreakdownsOpen, setDetailedBreakdownsOpen] = useState(() => {
    try {
      return window.localStorage.getItem(DETAILED_BREAKDOWNS_STORAGE_KEY) === 'open';
    } catch {
      return false;
    }
  });

  const toggleDetailedBreakdowns = () => {
    const next = !detailedBreakdownsOpen;
    setDetailedBreakdownsOpen(next);
    try {
      window.localStorage.setItem(DETAILED_BREAKDOWNS_STORAGE_KEY, next ? 'open' : 'closed');
    } catch {
      // ignore - persistence is a nicety, not a requirement
    }
  };
  // Set right before bumping ideaComparisonsNonce from the Regenerate button
  // below, and consumed (and cleared) by the effect - the same
  // forceRegenerateRef/nonce pattern StatsOverview.jsx's trend-summary
  // refresh button uses. Routing the regenerate call through this effect
  // (instead of a standalone async click handler) means a project switch
  // while a regenerate call is still in flight aborts/ignores that response
  // instead of letting it land on top of the now-selected project's data.
  const forceIdeaComparisonsRegenerateRef = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;
    async function loadIdeaComparisons() {
      if (!selectedProjectId) {
        setIdeaComparisons([]);
        setIdeaComparisonsPage(0);
        return;
      }
      const forceRegenerate = forceIdeaComparisonsRegenerateRef.current;
      forceIdeaComparisonsRegenerateRef.current = false;
      if (forceRegenerate) setIdeaComparisonsRegenerating(true);
      else setIdeaComparisonsLoading(true);
      setIdeaComparisonsError('');
      try {
        const { ok, data } = await getIdeaComparisons(
          selectedProjectId,
          { regenerate: forceRegenerate || undefined, run_id: selectedRunId || undefined },
          controller.signal,
        );
        if (cancelled) return;
        setIdeaComparisons(Array.isArray(data?.comparisons) ? data.comparisons : []);
        setIdeaComparisonsPage(0);
        if (!ok) setIdeaComparisonsError(data?.error || t('dashboard:ideaComparisons.loadError'));
      } catch (err) {
        if (!cancelled && err?.name !== 'AbortError') {
          setIdeaComparisons([]);
          setIdeaComparisonsError(err?.message || t('dashboard:ideaComparisons.loadError'));
        }
      } finally {
        if (!cancelled) {
          setIdeaComparisonsLoading(false);
          setIdeaComparisonsRegenerating(false);
        }
      }
    }
    loadIdeaComparisons();
    return () => { cancelled = true; controller.abort(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedProjectId, selectedRunId, ideaComparisonsNonce]);

  // Spends an LLM call per qualifying idea cluster (see
  // services/articles/idea_comparisons.py), so this only runs on an explicit
  // click - never automatically on a page view - the same restraint
  // getTrendSummary()'s refresh button uses.
  const regenerateIdeaComparisons = () => {
    if (!selectedProjectId) return;
    forceIdeaComparisonsRegenerateRef.current = true;
    setIdeaComparisonsNonce((n) => n + 1);
  };

  const ideaComparisonsTotalPages = Math.max(1, Math.ceil(ideaComparisons.length / IDEA_COMPARISONS_PAGE_SIZE));
  const pagedIdeaComparisons = ideaComparisons.slice(
    ideaComparisonsPage * IDEA_COMPARISONS_PAGE_SIZE,
    (ideaComparisonsPage + 1) * IDEA_COMPARISONS_PAGE_SIZE,
  );

  const frequentIdeas = data.insights?.frequent_ideas || [];
  const concernIdeas = frequentIdeas.filter((idea) => CONCERN_IDEA_TYPES.has(idea.type || 'issue'));
  const visibleIdeas = (ideaFilter === 'concerns' ? concernIdeas : frequentIdeas).slice(0, TOP_IDEAS_LIMIT);
  const maxIdeaFrequency = Math.max(1, ...visibleIdeas.map((idea) => Number(idea.frequency_estimate || 0)));

  const platformListTotalPages = Math.max(1, Math.ceil(sortedPlatformData.length / PLATFORM_LIST_PAGE_SIZE));
  const safePlatformListPage = Math.min(platformListPage, platformListTotalPages - 1);
  const pagedPlatformData = sortedPlatformData.slice(
    safePlatformListPage * PLATFORM_LIST_PAGE_SIZE,
    (safePlatformListPage + 1) * PLATFORM_LIST_PAGE_SIZE,
  );

  return <div className="content-shell intelligence-page">
    <header className="intelligence-header">
      <div>
        <span className="intelligence-eyebrow"><Sparkles size={14} /> {t('dashboard:overview.eyebrow')}</span>
        <h2>{t('dashboard:overview.title')}</h2>
        <p className="subtitle">{t('dashboard:overview.subtitle')}</p>
        <div className="filter-tabs-shell">
          <div className="filter-tab-buttons filter-mode-toggle" role="tablist" aria-label={t('dashboard:overview.filterTypeAria')}>
            <button type="button" role="tab" aria-selected={!selectedRunId} className={`source-type-tab ${!selectedRunId ? 'active' : ''}`} onClick={() => onRunChange?.(null)}>{t('dashboard:overview.dateRangeTab')}</button>
            {runs.length > 0 ? <button type="button" role="tab" aria-selected={!!selectedRunId} className={`source-type-tab ${selectedRunId ? 'active' : ''}`} onClick={() => onRunChange?.(selectedRunId || runs[0].id)}>{t('dashboard:overview.analysisRunTab')}</button> : null}
          </div>
          <div className="filter-tab-divider" aria-hidden="true" />
          {selectedRunId ? (
            runs.length > 3 ? (
              <select className="filter-select filter-run-select" value={selectedRunId} onChange={(event) => onRunChange?.(event.target.value)} aria-label={t('dashboard:overview.filterByRunAria')}>
                {runs.map((run, index) => <option key={run.id} value={run.id}>{pipelineRunTitle(run, index, locale, t)}</option>)}
              </select>
            ) : (
              <div className="filter-tab-buttons scrollable" role="tablist" aria-label={t('dashboard:overview.filterByRunAria')}>
                {runs.map((run, index) => <span key={run.id} className="filter-tab-run-item">{index > 0 ? <ChevronRight size={14} className="filter-tab-arrow rtl-mirror" aria-hidden="true" /> : null}<button type="button" role="tab" aria-selected={selectedRunId === run.id} className={`source-type-tab ${selectedRunId === run.id ? 'active' : ''}`} onClick={() => onRunChange?.(run.id)}>{pipelineRunTitle(run, index, locale, t)}</button></span>)}
              </div>
            )
          ) : (
            <div className="filter-tab-buttons" role="tablist" aria-label={t('dashboard:overview.dateRangeAria')}>
              {PERIODS.map((item) => <button key={item.key} type="button" role="tab" aria-selected={period === item.key} className={`source-type-tab ${period === item.key ? 'active' : ''}`} onClick={() => onPeriodChange(item.key)}>{t(item.labelKey)}</button>)}
            </div>
          )}
        </div>
      </div>
      <div className="intelligence-controls">
        <select className="filter-select" value={selectedProjectId ?? ''} onChange={(event) => onProjectChange(Number(event.target.value))} disabled={!projects.length} aria-label={t('dashboard:overview.projectSelectAria')}>
          {projects.map((project) => <option value={project.id} key={project.id}>{project.name}</option>)}
        </select>
      </div>
    </header>

    {selectedRun ? <p className="intelligence-run-note">{t('dashboard:runLabel.showing', { run: pipelineRunTitle(selectedRun, selectedRunIndex, locale, t) })}</p> : null}

    {selectedProject?.mode === 'competitor' ? (
      <CompetitorPulseCard studyId={selectedProject.id} backTo="/dashboard" backLabel={t('dashboard:overview.competitorBackLabel')} />
    ) : null}

    {/* App auto-selects the first project once the list lands, so "projects
        but none selected" is a transient state, not an empty one. */}
    {!selectedProject && (isLoadingProjects || projects.length > 0) ? <DashboardSkeleton /> : null}
    {!selectedProject && !isLoadingProjects && !projects.length ? <NoProjectsState /> : null}
    {selectedProject && error ? <div className="glass-card admin-empty-state report-error-state" role="alert"><strong>{t('dashboard:overview.loadErrorTitle')}</strong><p className="subtitle" dir="auto">{error}</p>{onRefresh ? <button type="button" className="btn-secondary" onClick={onRefresh}>{t('dashboard:report.tryAgain')}</button> : null}</div> : null}

    {selectedProject && !error ? (<>
      <section className="intelligence-metric-grid" aria-busy={showLoading}>
        <MetricCard icon={<Network size={18} />} label={t('dashboard:metrics.analyzedArticles.label')} value={showLoading ? <MetricValueSkeleton /> : formatNumber(isReady ? total : 0, locale)} detail={selectedRun ? pipelineRunTitle(selectedRun, selectedRunIndex, locale, t) : periodLabel} tone="blue" />
        <MetricCard icon={<Gauge size={18} />} label={t('dashboard:metrics.netSentiment.label')} value={showLoading ? <MetricValueSkeleton /> : isReady ? formatNumber(data.net_sentiment || 0, locale, { signDisplay: 'always', maximumFractionDigits: 0 }) : '—'} detail={t('dashboard:metrics.netSentiment.detail')} tone={!isReady || Number(data.net_sentiment || 0) >= 0 ? 'positive' : 'negative'} />
        <MetricCard icon={<FileText size={18} />} label={t('dashboard:metrics.documents.label')} value={showLoading ? <MetricValueSkeleton /> : formatNumber(data.document_count || 0, locale)} detail={t('dashboard:metrics.documents.detail')} tone="blue" />
        <MetricCard icon={<Activity size={18} />} label={t('dashboard:metrics.analysisHealth.label')} value={pipelineHealth?.lastRun?.status ? runStatusLabel(t, pipelineHealth.lastRun.status) : t('dashboard:metrics.analysisHealth.noRuns')} detail={pipelineHealth?.lastFinished ? t('dashboard:metrics.analysisHealth.lastCompleted', { date: formatDate(pipelineHealth.lastFinished.finished_at, locale) }) : t('dashboard:metrics.analysisHealth.noCompletedRuns')} tone="blue" />
      </section>

      {showLoading ? <DashboardSkeleton /> : !isReady ? <IntelligenceEmptyState
        state={scopeState}
        project={selectedProject}
        rangeLabel={periodLabel}
        onShowAllTime={selectedRunId || period !== 'all' ? () => onPeriodChange('all') : undefined}
        onAnalysisStarted={onRefresh}
      /> : <>
        <PendingAnalysisNotice state={scopeState} project={selectedProject} onAnalysisStarted={onRefresh} />
        <section className="intelligence-priority-grid">
          <article className="glass-card intelligence-card intelligence-line-card"><div className="intelligence-card-heading"><h3>{t('dashboard:sentimentTrend.title')}</h3><span>{t('dashboard:volumeOverTime.title')}</span></div><ResponsiveContainer width="100%" height={260}><LineChart data={data.sentiment_over_time || []}><CartesianGrid strokeDasharray="3 3" stroke="rgba(15,23,42,.09)" /><XAxis dataKey="date" tickFormatter={(value) => formatDate(value, locale)} minTickGap={24} /><YAxis allowDecimals={false} /><Tooltip labelFormatter={(value) => formatDate(value, locale)} /><Legend /><Line type="monotone" dataKey="total" name={t('dashboard:series.total')} stroke="#2563eb" strokeWidth={2.5} dot={false} /><Line type="monotone" dataKey="positive" name={t('dashboard:series.positive')} stroke={SENTIMENT_COLORS.positive} strokeWidth={2} dot={false} /><Line type="monotone" dataKey="negative" name={t('dashboard:series.negative')} stroke={SENTIMENT_COLORS.negative} strokeWidth={2} dot={false} /><Line type="monotone" dataKey="neutral" name={t('dashboard:series.neutral')} stroke={SENTIMENT_COLORS.neutral} strokeWidth={2} dot={false} /></LineChart></ResponsiveContainer></article>
          <article className="glass-card intelligence-card intelligence-ideas-card">
            <div className="intelligence-card-heading">
              <div>
                <h3>{ideaFilter === 'concerns' ? t('dashboard:topConcerns.title') : t('dashboard:ideas.title')}</h3>
                <span>{ideaFilter === 'concerns' ? t('dashboard:topConcerns.subtitle') : t('dashboard:ideas.subtitle')}</span>
              </div>
              <div className="filter-tab-buttons filter-mode-toggle" role="tablist" aria-label={t('dashboard:topConcerns.filterAria')}>
                <button type="button" role="tab" aria-selected={ideaFilter === 'concerns'} className={`source-type-tab ${ideaFilter === 'concerns' ? 'active' : ''}`} onClick={() => setIdeaFilter('concerns')}>{t('dashboard:topConcerns.concernsTab')}</button>
                <button type="button" role="tab" aria-selected={ideaFilter === 'all'} className={`source-type-tab ${ideaFilter === 'all' ? 'active' : ''}`} onClick={() => setIdeaFilter('all')}>{t('dashboard:topConcerns.allTab')}</button>
              </div>
            </div>
            {visibleIdeas.map((idea) => <IdeaRow key={idea.idea} idea={idea} maxFrequency={maxIdeaFrequency} projectId={selectedProjectId} />)}
            {!visibleIdeas.length && <p className="intelligence-empty">{ideaFilter === 'concerns' ? t('dashboard:topConcerns.empty') : t('dashboard:ideas.empty')}</p>}
          </article>
        </section>

        <section className="intelligence-top-grid">
          <article className="glass-card intelligence-card intelligence-sentiment-card"><h3>{t('dashboard:sentimentBreakdown.title')}</h3><div className="intelligence-sentiment-layout"><div className="intelligence-donut"><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={sentimentData} dataKey="value" innerRadius="63%" outerRadius="84%" paddingAngle={3} stroke="none">{sentimentData.map((entry) => <Cell key={entry.name} fill={SENTIMENT_COLORS[entry.name]} />)}</Pie><Tooltip formatter={(value, name) => [t('dashboard:counts.articlesCount', { count: value }), sentimentLabel(t, name)]} /></PieChart></ResponsiveContainer><strong>{formatNumber(data.net_sentiment || 0, locale, { signDisplay: 'always', maximumFractionDigits: 0 })}</strong><span>{t('dashboard:sentimentBreakdown.netSentimentCaption')}</span></div><div className="intelligence-legend">{sentimentData.map((entry) => <div key={entry.name}><span style={{ background: SENTIMENT_COLORS[entry.name] }} /><label>{sentimentLabel(t, entry.name)}</label><strong>{formatPercent(percent(entry.value, total), locale, { alreadyWhole: true })}</strong></div>)}</div></div></article>
          <article className="glass-card intelligence-card intelligence-radar-card"><h3>{t('dashboard:emotionalSignature.title')}</h3><ResponsiveContainer width="100%" height={285}><RadarChart data={data.emotional_signature || []}><PolarGrid /><PolarAngleAxis dataKey="axis" tickFormatter={(value) => emotionAxisLabel(t, value)} /><PolarRadiusAxis angle={30} domain={[0, 100]} tick={false} /><Radar dataKey="value" stroke="#2563eb" fill="#2563eb" fillOpacity={0.22} /></RadarChart></ResponsiveContainer><p>{t('dashboard:emotionalSignature.description')}</p></article>
          <article className="glass-card intelligence-card"><h3>{t('dashboard:sentimentByPlatform.title')}</h3><div className="intelligence-platform-sentiment">{platformData.map((item) => <div key={item.platform}><span dir="auto">{item.platform}</span><div>{SENTIMENT_KEYS.map((tone) => <i key={tone} title={t('dashboard:sentimentByPlatform.tooltipTitle', { tone: sentimentLabel(t, tone), count: item[tone] || 0 })} style={{ width: `${percent(item[tone], Math.max(1, item.total))}%`, background: SENTIMENT_COLORS[tone] }} />)}</div></div>)}</div></article>
        </section>

        <section className="intelligence-bottom-grid">
          <article className={`glass-card intelligence-card${selectedProject?.mode === 'competitor' ? ' intelligence-pipeline-card-full' : ''}`}>
            <h3>{t('dashboard:wherePosted.title')}</h3>
            <div className="intelligence-platform-list">{pagedPlatformData.map((item) => <div key={item.platform}><div><strong dir="auto">{item.platform}</strong></div><div className="intelligence-track"><span style={{ width: `${percent(item.total, total)}%` }} /></div><div className="intelligence-platform-count"><strong>{formatNumber(item.total, locale)}</strong><small>{t('dashboard:counts.articleUnit', { count: item.total })}</small></div></div>)}</div>
            {platformListTotalPages > 1 ? (
              <div className="intelligence-idea-comparison-pagination">
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => setPlatformListPage((current) => Math.max(0, current - 1))}
                  disabled={safePlatformListPage === 0}
                >
                  <ChevronLeft size={14} className="rtl-mirror" /> {t('dashboard:wherePosted.prev')}
                </button>
                <span className="intelligence-idea-comparison-pagination-status">
                  {t('common:pagination.pageOfTotal', { page: safePlatformListPage + 1, totalPages: platformListTotalPages })}
                </span>
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => setPlatformListPage((current) => Math.min(platformListTotalPages - 1, current + 1))}
                  disabled={safePlatformListPage >= platformListTotalPages - 1}
                >
                  {t('dashboard:wherePosted.next')} <ChevronRight size={14} className="rtl-mirror" />
                </button>
              </div>
            ) : null}
          </article>
          {selectedProject?.mode !== 'competitor' ? <article className="glass-card intelligence-card"><h3>{t('dashboard:trending.title')}</h3><div className="intelligence-term-list">{(data.trending_terms || []).filter((term) => term.mentions > 0).map((term) => <Link key={`${term.kind}-${term.term}`} to={`/articles?search=${encodeURIComponent(term.term.replace(/^#/, ''))}${selectedProjectId != null ? `&project_id=${selectedProjectId}` : ''}`} className={`intelligence-term-link ${term.kind}`} title={t('dashboard:trending.linkTitle', { term: term.term })}><b dir="auto">{term.term}</b> <em>{formatNumber(term.mentions, locale)}</em></Link>)}{!(data.trending_terms || []).some((term) => term.mentions > 0) && <p className="intelligence-empty">{t('dashboard:trending.empty')}</p>}</div></article> : null}
        </section>

        <section className="intelligence-idea-comparisons-grid">
          <article className="glass-card intelligence-card intelligence-idea-comparisons-card">
            <div className="intelligence-card-heading">
              <div>
                <h3>{t('dashboard:ideaComparisons.title')}</h3>
                <span>{t('dashboard:ideaComparisons.subtitle')}</span>
              </div>
              <button
                type="button"
                className="btn-secondary"
                onClick={regenerateIdeaComparisons}
                disabled={ideaComparisonsRegenerating || !selectedProjectId}
                style={{ padding: '6px 10px', fontSize: '0.78rem', display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}
              >
                {ideaComparisonsRegenerating ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} />}
                {t('common:actions.regenerate')}
              </button>
            </div>
            {ideaComparisonsError ? (
              <p className="intelligence-empty" dir="auto">{ideaComparisonsError}</p>
            ) : ideaComparisonsLoading ? (
              <p className="intelligence-empty"><Loader2 size={14} className="spin" /> {t('dashboard:ideaComparisons.loading')}</p>
            ) : ideaComparisons.length === 0 ? (
              <div className="intelligence-idea-comparison-empty">
                <Lightbulb size={20} />
                <p>
                  {t('dashboard:ideaComparisons.emptyBody')}
                </p>
              </div>
            ) : (
              <>
              <div className="intelligence-idea-comparison-list">
                {pagedIdeaComparisons.map((comparison) => (
                  <div
                    key={comparison.idea_cluster_id}
                    className={`intelligence-idea-comparison-item ${comparison.diverges ? 'diverges' : 'agrees'}`}
                  >
                    <div className="intelligence-idea-comparison-header">
                      <div className="intelligence-idea-comparison-title">
                        <Lightbulb size={14} className="intelligence-idea-comparison-icon" />
                        <strong dir="auto">{comparison.idea}</strong>
                      </div>
                      <div className="intelligence-idea-comparison-actions">
                        {comparison.diverges ? (
                          <span className="intelligence-idea-comparison-tag diverges"><Scale size={12} /> {t('dashboard:ideaComparisons.diverges')}</span>
                        ) : (
                          <span className="intelligence-idea-comparison-tag agrees"><CheckCircle2 size={12} /> {t('dashboard:ideaComparisons.agrees')}</span>
                        )}
                        <Link
                          className="intelligence-idea-comparison-details-link"
                          to={`/projects/${selectedProjectId}/idea-comparisons/${comparison.idea_cluster_id}${selectedRunId ? `?run_id=${encodeURIComponent(selectedRunId)}` : ''}`}
                          state={{ from: `${location.pathname}${location.search}` }}
                          aria-label={t('dashboard:ideaComparisons.viewDetails', { idea: comparison.idea })}
                          title={t('dashboard:ideaComparisons.viewDetailsTitle')}
                        ><ChevronRight size={17} /></Link>
                      </div>
                    </div>
                    {comparison.summary ? <p className="intelligence-idea-comparison-summary" dir="auto">{comparison.summary}</p> : null}
                    <details className="intelligence-idea-comparison-sources-disclosure">
                      <summary>{t('dashboard:ideaComparisons.sourcesCount', { count: (comparison.sources || []).length })} <ChevronDown size={14} /></summary>

                    <div className="intelligence-idea-comparison-sources">
                      {(comparison.sources || []).map((source, index) => {
                        const content = (
                          <>
                            <span className="intelligence-idea-comparison-source-label" dir="auto">{source.source_label}</span>
                            {source.value ? (
                              <span className="intelligence-idea-comparison-source-value" dir="auto">{source.value}</span>
                            ) : (
                              <span className="intelligence-idea-comparison-source-novalue">{t('dashboard:ideaComparisons.noValue')}</span>
                            )}
                            {source.url ? <ExternalLink size={12} className="intelligence-idea-comparison-source-link-icon" /> : null}
                          </>
                        );
                        const key = `${comparison.idea_cluster_id}-${source.article_id ?? index}`;
                        return source.url ? (
                          <a
                            key={key}
                            href={source.url}
                            target="_blank"
                            rel="noreferrer"
                            className="intelligence-idea-comparison-source"
                            title={source.title || source.source_label}
                          >
                            {content}
                          </a>
                        ) : (
                          <span key={key} className="intelligence-idea-comparison-source" title={source.title || source.source_label}>
                            {content}
                          </span>
                        );
                      })}
                    </div>
                    </details>
                  </div>
                ))}
              </div>
              {ideaComparisonsTotalPages > 1 ? (
                <div className="intelligence-idea-comparison-pagination">
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => setIdeaComparisonsPage((current) => Math.max(0, current - 1))}
                    disabled={ideaComparisonsPage === 0}
                  >
                    <ChevronLeft size={14} className="rtl-mirror" /> {t('dashboard:ideaComparisons.prev')}
                  </button>
                  <span className="intelligence-idea-comparison-pagination-status">
                    {t('common:pagination.pageOfTotal', { page: ideaComparisonsPage + 1, totalPages: ideaComparisonsTotalPages })}
                  </span>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => setIdeaComparisonsPage((current) => Math.min(ideaComparisonsTotalPages - 1, current + 1))}
                    disabled={ideaComparisonsPage >= ideaComparisonsTotalPages - 1}
                  >
                    {t('dashboard:ideaComparisons.next')} <ChevronRight size={14} className="rtl-mirror" />
                  </button>
                </div>
              ) : null}
              </>
            )}
          </article>
        </section>

        <section className="intelligence-run-sentiment-grid">
          <article className="glass-card intelligence-card intelligence-pipeline-card"><div className="intelligence-card-heading"><h3>{t('dashboard:articlesByRun.title')}</h3>{latestRun && <Change value={latestRun.change_pct} />}</div>{(data.pipeline_discovery || []).length ? <ResponsiveContainer width="100%" height={240}><LineChart data={data.pipeline_discovery}><CartesianGrid strokeDasharray="3 3" stroke="rgba(15,23,42,.09)" /><XAxis dataKey="completed_at" tickFormatter={(value, index) => pipelineRunShortLabel(data.pipeline_discovery[index], index, t)} minTickGap={18} /><YAxis allowDecimals={false} /><Tooltip labelFormatter={(value, payload) => { const item = payload?.[0]?.payload; return item ? `${pipelineRunShortLabel(item, 0, t)} · ${formatDate(item.completed_at, locale)}` : value; }} formatter={(value) => [t('dashboard:counts.articlesCount', { count: value }), t('dashboard:articlesByRun.tooltipLabel')]} /><Line type="monotone" dataKey="articles_discovered" stroke="#2563eb" strokeWidth={3} dot={{ r: 4 }} /></LineChart></ResponsiveContainer> : <p className="intelligence-empty">{t('dashboard:articlesByRun.empty')}</p>}</article>
          <article className="glass-card intelligence-card intelligence-run-sentiment-card">
            <h3>{t('dashboard:sentimentAcrossRuns.title')}</h3>
            {(data.sentiment_by_pipeline_run || []).some((run) => run.total > 0) ? <ResponsiveContainer width="100%" height={240}><LineChart data={data.sentiment_by_pipeline_run}><CartesianGrid strokeDasharray="3 3" stroke="rgba(15,23,42,.09)" /><XAxis dataKey="completed_at" tickFormatter={(value, index) => pipelineRunShortLabel(data.sentiment_by_pipeline_run[index], index, t)} minTickGap={18} /><YAxis domain={[-100, 100]} tickFormatter={(value) => formatNumber(value, locale, { signDisplay: 'always', maximumFractionDigits: 0 })} /><Tooltip labelFormatter={(value, payload) => { const item = payload?.[0]?.payload; return item ? `${pipelineRunShortLabel(item, 0, t)} · ${formatDate(item.completed_at, locale)}` : value; }} formatter={(value) => [formatNumber(value, locale, { signDisplay: 'always', maximumFractionDigits: 0 }), t('dashboard:sentimentAcrossRuns.tooltipLabel')]} /><ReferenceLine y={0} stroke="rgba(15,23,42,.25)" /><Line type="monotone" dataKey="net_sentiment" name={t('dashboard:sentimentAcrossRuns.tooltipLabel')} stroke={SENTIMENT_COLORS.positive} strokeWidth={2} dot={{ r: 4 }} /></LineChart></ResponsiveContainer> : <p className="intelligence-empty">{t('dashboard:sentimentAcrossRuns.empty')}</p>}
          </article>
        </section>

        <section className="intelligence-detailed-breakdowns">
          <button
            type="button"
            className="glass-card intelligence-detailed-breakdowns-toggle"
            aria-expanded={detailedBreakdownsOpen}
            aria-controls="intelligence-detailed-breakdowns-panel"
            onClick={toggleDetailedBreakdowns}
          >
            <span className="intelligence-metric-icon"><Layers size={18} /></span>
            <span className="intelligence-detailed-breakdowns-text">
              <strong>{t('dashboard:detailedBreakdowns.title')}</strong>
              <small>{t('dashboard:detailedBreakdowns.summary')}</small>
            </span>
            <span className="intelligence-detailed-breakdowns-action">
              {detailedBreakdownsOpen ? t('dashboard:detailedBreakdowns.hide') : t('dashboard:detailedBreakdowns.show')}
              <ChevronDown size={16} />
            </span>
          </button>
          {detailedBreakdownsOpen ? (
            <div id="intelligence-detailed-breakdowns-panel" className="intelligence-language-grid">
              <DistributionCard title={t('dashboard:distributions.language.title')} entries={languageData} nameKey="language" valueKey="count" valueTotal={total} colorFor={paletteColor} labelFor={(code) => languageLabel(t, locale, code)} emptyText={t('dashboard:distributions.language.empty')} />
              <DistributionCard title={t('dashboard:distributions.region.title')} entries={regionData} nameKey="value" valueKey="total" valueTotal={total} colorFor={paletteColor} labelFor={(value) => distributionLabel(t, value)} emptyText={t('dashboard:distributions.region.empty')} />
              <DistributionCard title={t('dashboard:distributions.gender.title')} entries={genderData} nameKey="value" valueKey="total" valueTotal={total} colorFor={paletteColor} labelFor={(value) => distributionLabel(t, value)} emptyText={t('dashboard:distributions.gender.empty')} />
              <DistributionCard title={t('dashboard:distributions.ageRange.title')} entries={ageRangeData} nameKey="value" valueKey="total" valueTotal={total} colorFor={paletteColor} labelFor={(value) => distributionLabel(t, value)} emptyText={t('dashboard:distributions.ageRange.empty')} />
              <DistributionCard title={t('dashboard:distributions.segment.title')} entries={segmentData} nameKey="value" valueKey="total" valueTotal={total} colorFor={paletteColor} labelFor={(value) => distributionLabel(t, value)} emptyText={t('dashboard:distributions.segment.empty')} />
              <DistributionCard title={t('dashboard:sourceTrust.title')} entries={trustData} nameKey="tier" valueKey="articles" valueTotal={data.source_trust?.total_articles || 0} colorFor={(entry) => TRUST_TIER_COLORS[entry.tier]} labelFor={(tier) => trustTierLabel(t, tier)} emptyText={t('dashboard:sourceTrust.empty')} />
            </div>
          ) : null}
        </section>
      </>}
    </>) : null}
  </div>;
}
