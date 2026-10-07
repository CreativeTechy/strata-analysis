import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import {
  Activity, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight, ExternalLink, FileText, Gauge, Languages, Layers, Lightbulb, Loader2, Network,
  RefreshCw, Scale, Sparkles, TrendingDown, TrendingUp,
} from 'lucide-react';
import {
  CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, Radar, RadarChart,
  PolarAngleAxis, PolarGrid, PolarRadiusAxis, ReferenceLine, Text, Tooltip,
} from 'recharts';
import { XAxis, YAxis } from './ChartAxes.jsx';
import '../styles/IntelligenceDashboard.css';
import CompetitorPulseCard from './CompetitorPulseCard.jsx';
import IntelligenceEmptyState, { DashboardSkeleton, MetricValueSkeleton, NoProjectsState, PendingAnalysisNotice } from './IntelligenceEmptyState.jsx';
import ResponsiveContainer from './ResponsiveChartContainer.jsx';
import { getIdeaComparisons, getProjectIntelligence } from '../api/projectsApi.js';
import { isIntelligenceStale, resolveIntelligenceState } from '../lib/intelligenceState.js';
import { formatDate as formatLocaleDate, formatLanguageName, formatNumber, formatPercent, formatTime } from '../lib/i18nFormat.js';
import { articlesEvidencePath, isLinkableBucket } from '../lib/evidenceLinks.js';
import {
  DEFAULT_LOCALE, LOCALE_NATIVE_NAMES, SUPPORTED_LOCALES, isRtlLocale, isSupportedLocale,
} from '../i18n/locales.js';

const IDEA_COMPARISONS_PAGE_SIZE = 3;
const PLATFORM_LIST_PAGE_SIZE = 5;
const IDEAS_PAGE_SIZE = 3;
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
// Idea types that count as a concern - the fallback filter for an
// intelligence payload without insights.frequent_concerns (see
// articles_analytics.CONCERN_IDEA_TYPES); praise/suggestion stay reachable
// through the "Top concerns" card's "All ideas" tab.
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

// Recharts' default 80% leaves little room beside the radar for its angle
// labels; RadarAngleTick below handles whatever still doesn't fit.
const RADAR_OUTER_RADIUS = '68%';

// An angle label beside the radar can only use the space between its anchor
// and the chart edge on its own side (the chart is centered, so the full
// width is 2 * cx); a long one ("Anticipation" on a phone) wraps or is
// ellipsized into that space instead of being cut off at the card edge.
function RadarAngleTick({ payload, x, cx, textAnchor, formatLabel, index, ...props }) {
  const room = textAnchor === 'start' ? 2 * cx - x : textAnchor === 'end' ? x : 2 * cx;
  return (
    <Text {...props} x={x} textAnchor={textAnchor} width={Math.max(room - 4, 24)} maxLines={2} className="recharts-polar-angle-axis-tick-value">
      {formatLabel(payload.value, index)}
    </Text>
  );
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

// `to` makes the whole card an evidence link (see lib/evidenceLinks.js) -
// every headline number opens what it was counted from.
function MetricCard({ icon, label, value, detail, tone = 'blue', to, linkTitle }) {
  const body = <>
    <span className="intelligence-metric-icon">{icon}</span>
    <div><span className="intelligence-metric-label">{label}</span><strong>{value}</strong>{detail && <small>{detail}</small>}</div>
  </>;
  if (to) {
    return <Link className={`intelligence-metric intelligence-metric-link intelligence-metric-${tone}`} to={to} title={linkTitle} aria-label={linkTitle ? `${label}: ${value}. ${linkTitle}` : undefined}>{body}</Link>;
  }
  return <article className={`intelligence-metric intelligence-metric-${tone}`}>{body}</article>;
}

// One legend row of a donut: a link to that slice's articles, or a plain
// row for the folded "other" slice, which has no single bucket to open.
function LegendRow({ to, title, children }) {
  if (!to) return <div>{children}</div>;
  return <Link className="intelligence-legend-link" to={to} title={title}>{children}</Link>;
}

// Recharts hands a Pie's onClick the sector, whose original datum is on
// `payload` - read the bucket off whichever carries it.
function sliceValue(sector, key) {
  return sector?.payload?.[key] ?? sector?.[key];
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
      state={{ idea: idea.idea, topicQuery: idea.source_text || idea.idea, type: idea.type, category: idea.category, frequencyEstimate: idea.frequency_estimate, sources: mapTopicSources(idea.sources), projectId, backTo: '/dashboard', backLabel: t('dashboard:ideas.backLabel') }}
    >
      {body}
    </Link>;
  }
  return <div className={`intelligence-idea ${idea.type || 'issue'}`}>{body}</div>;
}

// One donut + legend card for a single distribution (language, region,
// gender, ...). `nameKey` is the bucket field, `valueKey` the count field,
// and `valueTotal` the denominator the legend percentages are taken against.
// `linkFor(bucket)` is that bucket's evidence link (null when it can't be
// opened on its own, like the folded "other" slice) - both the slice and
// its legend row open it.
function DistributionCard({ title, entries, nameKey, valueKey, valueTotal, colorFor, labelFor, emptyText, linkFor }) {
  const { t, i18n } = useTranslation('dashboard');
  const locale = i18n.language;
  const navigate = useNavigate();
  const openSlice = (sector) => {
    const path = linkFor?.(sliceValue(sector, nameKey));
    if (path) navigate(path);
  };
  return <article className="glass-card intelligence-card intelligence-language-card">
    <h3>{title}</h3>
    {entries.length ? (
      <div className="intelligence-language-layout">
        <div className="intelligence-donut">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={entries} dataKey={valueKey} nameKey={nameKey} outerRadius="92%" paddingAngle={3} stroke="none" className={linkFor ? 'intelligence-clickable-chart' : undefined} onClick={linkFor ? openSlice : undefined}>
                {entries.map((entry, index) => <Cell key={entry[nameKey]} fill={colorFor(entry, index)} />)}
              </Pie>
              <Tooltip formatter={(value, name) => [t('dashboard:counts.articlesCount', { count: value }), labelFor(name)]} />
            </PieChart>
          </ResponsiveContainer>
        </div>
        <div className="intelligence-legend">
          {entries.map((entry, index) => (
            <LegendRow key={entry[nameKey]} to={linkFor?.(entry[nameKey])} title={t('dashboard:evidence.openArticles', { label: labelFor(entry[nameKey]) })}>
              <span style={{ background: colorFor(entry, index) }} />
              <label>{labelFor(entry[nameKey])}</label>
              <strong>{formatPercent(percent(entry[valueKey], valueTotal), locale, { alreadyWhole: true })}</strong>
            </LegendRow>
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
  const populationTotal = Number(data.articles_total ?? total);
  const notAssessedTotal = Number(data.sentiment_not_assessed ?? Math.max(0, populationTotal - total));
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
  const navigate = useNavigate();
  // Every selection opens the Articles page on exactly what it counted, in
  // the same project and scope (period, or the selected run) - see
  // lib/evidenceLinks.js.
  const evidencePath = (filters = {}) => articlesEvidencePath({ projectId: selectedProjectId, period, runId: selectedRunId, filters });
  const bucketPath = (dimension, value) => (isLinkableBucket(value) ? evidencePath({ [dimension]: value }) : null);
  const openBucket = (dimension, value) => {
    const path = bucketPath(dimension, value);
    if (path) navigate(path);
  };
  const openArticlesTitle = (label) => t('dashboard:evidence.openArticles', { label });
  // A run point on the cross-run charts opens that run's articles - a run
  // scope of its own, whatever the dashboard's current scope is.
  const openRunPoint = (points, state) => {
    // Recharts reports the index as a string, and null off any point -
    // guarded before converting, since Number(null) would read as run 0.
    const raw = state?.activeTooltipIndex ?? state?.activeIndex;
    const index = raw == null || raw === '' ? NaN : Number(raw);
    const runId = Number.isInteger(index) ? points?.[index]?.run_id : null;
    if (runId) navigate(articlesEvidencePath({ projectId: selectedProjectId, runId }));
  };

  const [ideaComparisons, setIdeaComparisons] = useState([]);
  const [ideaComparisonsLoading, setIdeaComparisonsLoading] = useState(false);
  const [ideaComparisonsError, setIdeaComparisonsError] = useState('');
  const [ideaComparisonsRegenerating, setIdeaComparisonsRegenerating] = useState(false);
  const [ideaComparisonsElapsedSeconds, setIdeaComparisonsElapsedSeconds] = useState(0);
  const [ideaComparisonsTruncated, setIdeaComparisonsTruncated] = useState(null);
  const [ideaComparisonsNonce, setIdeaComparisonsNonce] = useState(0);
  const [ideaComparisonsPage, setIdeaComparisonsPage] = useState(0);
  // Output language of the idea comparison cards - independent of the
  // interface locale, same as the other output-language switchers. Defaults to
  // the interface locale at mount; translations are cached server-side.
  const [ideaComparisonsLocale, setIdeaComparisonsLocale] = useState(
    () => (isSupportedLocale(i18n.language) ? i18n.language : DEFAULT_LOCALE),
  );
  // Output language of the "Most talked-about ideas" card - independent of the
  // interface locale. `intelligence` (App.jsx) is already fetched in the
  // interface locale, so only a diverging choice needs its own request; the
  // translations are cached server-side by idea text.
  const [ideasLocale, setIdeasLocale] = useState(
    () => (isSupportedLocale(i18n.language) ? i18n.language : DEFAULT_LOCALE),
  );
  const [ideasResult, setIdeasResult] = useState(null);
  const [platformListPage, setPlatformListPage] = useState(0);
  // Tab and page are keyed by project, so switching project lands back on
  // page 1 of Top concerns - the first screen's point - rather than carrying
  // over another project's tab or page.
  const [ideaView, setIdeaView] = useState({ projectId: selectedProjectId, filter: 'concerns', page: 0 });
  const currentIdeaView = ideaView.projectId === selectedProjectId
    ? ideaView
    : { projectId: selectedProjectId, filter: 'concerns', page: 0 };
  const ideaFilter = currentIdeaView.filter;
  const ideasPage = currentIdeaView.page;
  const setIdeaFilter = (filter) => setIdeaView({ projectId: selectedProjectId, filter, page: 0 });
  const setIdeasPage = (next) => setIdeaView((prev) => {
    const base = prev.projectId === selectedProjectId ? prev : { projectId: selectedProjectId, filter: 'concerns', page: 0 };
    return { ...base, page: typeof next === 'function' ? next(base.page) : next };
  });
  const ideasWantTranslation = Boolean(selectedProjectId) && ideasLocale !== i18n.language;
  const ideasKey = `${selectedProjectId}|${period}|${selectedRunId || ''}|${ideasLocale}`;
  useEffect(() => {
    if (!ideasWantTranslation) return undefined;
    let cancelled = false;
    getProjectIntelligence(selectedProjectId, { period, run_id: selectedRunId || undefined, locale: ideasLocale })
      .then((result) => { if (!cancelled) setIdeasResult({ key: ideasKey, insights: result?.insights || null }); })
      .catch((err) => {
        if (!cancelled) {
          console.error('Failed to load translated ideas', err);
          setIdeasResult({ key: ideasKey, insights: null });
        }
      });
    return () => { cancelled = true; };
  }, [ideasWantTranslation, selectedProjectId, period, selectedRunId, ideasLocale, ideasKey]);
  const translatedIdeas = ideasWantTranslation && ideasResult?.key === ideasKey ? ideasResult.insights : null;
  const ideasTranslating = ideasWantTranslation && ideasResult?.key !== ideasKey;

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
      setIdeaComparisonsTruncated(null);
      let elapsedTimer;
      if (forceRegenerate) {
        setIdeaComparisonsRegenerating(true);
        setIdeaComparisonsElapsedSeconds(0);
        // A whole-project regenerate can spend one LLM call per qualifying
        // idea cluster (see idea_comparisons.generate_idea_comparisons), so
        // this can legitimately run for tens of seconds - an elapsed-time
        // counter tells the user it's still working rather than leaving a
        // bare spinner up with no sense of progress.
        elapsedTimer = setInterval(() => setIdeaComparisonsElapsedSeconds((s) => s + 1), 1000);
      } else {
        setIdeaComparisonsLoading(true);
      }
      setIdeaComparisonsError('');
      try {
        const { ok, data } = await getIdeaComparisons(
          selectedProjectId,
          { regenerate: forceRegenerate || undefined, run_id: selectedRunId || undefined, locale: ideaComparisonsLocale },
          controller.signal,
        );
        if (cancelled) return;
        setIdeaComparisons(Array.isArray(data?.comparisons) ? data.comparisons : []);
        setIdeaComparisonsPage(0);
        if (!ok) {
          setIdeaComparisonsError(data?.error || t('dashboard:ideaComparisons.loadError'));
        } else if (data?.regeneration_timed_out) {
          setIdeaComparisonsTruncated({ written: data.regenerated_count ?? 0, total: data.regeneration_total ?? 0 });
        }
      } catch (err) {
        if (cancelled || err?.name === 'AbortError') return; // component unmounted / project switched mid-request
        setIdeaComparisons([]);
        setIdeaComparisonsError(
          err?.name === 'TimeoutError'
            ? t('dashboard:ideaComparisons.timeoutError')
            : (err?.message || t('dashboard:ideaComparisons.loadError')),
        );
      } finally {
        clearInterval(elapsedTimer);
        if (!cancelled) {
          setIdeaComparisonsLoading(false);
          setIdeaComparisonsRegenerating(false);
        }
      }
    }
    loadIdeaComparisons();
    return () => { cancelled = true; controller.abort(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedProjectId, selectedRunId, ideaComparisonsNonce, ideaComparisonsLocale]);

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

  const ideaInsights = translatedIdeas || data.insights;
  const frequentIdeas = ideaInsights?.frequent_ideas || [];
  // frequent_concerns is ranked over every idea, not just frequent_ideas'
  // top-12 slice - filtering that slice would drop concerns outranked by 12
  // more-repeated praise/suggestion ideas.
  const concernIdeas = ideaInsights?.frequent_concerns
    || frequentIdeas.filter((idea) => CONCERN_IDEA_TYPES.has(idea.type || 'issue'));
  const filteredIdeas = (ideaFilter === 'concerns' ? concernIdeas : frequentIdeas).slice(0, TOP_IDEAS_LIMIT);
  const ideasTotalPages = Math.max(1, Math.ceil(filteredIdeas.length / IDEAS_PAGE_SIZE));
  const safeIdeasPage = Math.min(ideasPage, ideasTotalPages - 1);
  const visibleIdeas = filteredIdeas.slice(safeIdeasPage * IDEAS_PAGE_SIZE, (safeIdeasPage + 1) * IDEAS_PAGE_SIZE);
  const maxIdeaFrequency = Math.max(1, ...filteredIdeas.map((idea) => Number(idea.frequency_estimate || 0)));

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
          {projects.map((project) => <option value={project.id} key={project.id}>{project.display_name || project.name}</option>)}
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
        <MetricCard icon={<Network size={18} />} label={t('dashboard:metrics.analyzedArticles.label')} value={showLoading ? <MetricValueSkeleton /> : formatNumber(isReady ? total : 0, locale)} detail={selectedRun ? pipelineRunTitle(selectedRun, selectedRunIndex, locale, t) : periodLabel} tone="blue" to={isReady && total > 0 ? evidencePath() : undefined} linkTitle={t('dashboard:evidence.openScope')} />
        <MetricCard icon={<Gauge size={18} />} label={t('dashboard:metrics.netSentiment.label')} value={showLoading ? <MetricValueSkeleton /> : isReady ? formatNumber(data.net_sentiment || 0, locale, { signDisplay: 'always', maximumFractionDigits: 0 }) : '—'} detail={t('dashboard:metrics.netSentiment.detail')} tone={!isReady || Number(data.net_sentiment || 0) >= 0 ? 'positive' : 'negative'} to={isReady && total > 0 ? evidencePath() : undefined} linkTitle={t('dashboard:evidence.openScope')} />
        <MetricCard icon={<FileText size={18} />} label={t('dashboard:metrics.documents.label')} value={showLoading ? <MetricValueSkeleton /> : formatNumber(data.document_count || 0, locale)} detail={t('dashboard:metrics.documents.detail')} tone="blue" to="/sources" linkTitle={t('dashboard:evidence.openSources')} />
        <MetricCard icon={<Activity size={18} />} label={t('dashboard:metrics.analysisHealth.label')} value={pipelineHealth?.lastRun?.status ? runStatusLabel(t, pipelineHealth.lastRun.status) : t('dashboard:metrics.analysisHealth.noRuns')} detail={pipelineHealth?.lastFinished ? t('dashboard:metrics.analysisHealth.lastCompleted', { date: formatDate(pipelineHealth.lastFinished.finished_at, locale) }) : t('dashboard:metrics.analysisHealth.noCompletedRuns')} tone="blue" to={pipelineHealth?.lastRun?.id ? `/pipeline-runs/${pipelineHealth.lastRun.id}` : '/pipeline-runs'} linkTitle={t('dashboard:evidence.openRuns')} />
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
          <article className="glass-card intelligence-card intelligence-line-card"><div className="intelligence-card-heading"><h3>{t('dashboard:sentimentTrend.title')}</h3><span>{t('dashboard:volumeOverTime.title')}</span></div><ResponsiveContainer width="100%" height={260}><LineChart data={data.sentiment_over_time || []} className="intelligence-clickable-chart" onClick={(state) => openBucket('date', state?.activeLabel)}><CartesianGrid strokeDasharray="3 3" stroke="rgba(15,23,42,.09)" /><XAxis dataKey="date" tickFormatter={(value) => formatDate(value, locale)} minTickGap={24} /><YAxis allowDecimals={false} /><Tooltip labelFormatter={(value) => formatDate(value, locale)} /><Legend /><Line type="monotone" dataKey="total" name={t('dashboard:series.total')} stroke="#2563eb" strokeWidth={2.5} dot={false} /><Line type="monotone" dataKey="positive" name={t('dashboard:series.positive')} stroke={SENTIMENT_COLORS.positive} strokeWidth={2} dot={false} /><Line type="monotone" dataKey="negative" name={t('dashboard:series.negative')} stroke={SENTIMENT_COLORS.negative} strokeWidth={2} dot={false} /><Line type="monotone" dataKey="neutral" name={t('dashboard:series.neutral')} stroke={SENTIMENT_COLORS.neutral} strokeWidth={2} dot={false} /></LineChart></ResponsiveContainer><p className="intelligence-chart-hint">{t('dashboard:evidence.chartHint')}</p></article>
          <article className="glass-card intelligence-card intelligence-ideas-card">
            <div className="intelligence-card-heading">
              <div>
                <h3>{ideaFilter === 'concerns' ? t('dashboard:topConcerns.title') : t('dashboard:ideas.title')}</h3>
                <span>{ideaFilter === 'concerns' ? t('dashboard:topConcerns.subtitle') : t('dashboard:ideas.subtitle')}</span>
              </div>
              <div className="filter-tab-buttons filter-mode-toggle" role="tablist" aria-label={t('dashboard:topConcerns.filterAria')}>
                <button type="button" role="tab" aria-selected={ideaFilter === 'concerns'} className={`source-type-tab ${ideaFilter === 'concerns' ? 'active' : ''}`} onClick={() => { setIdeaFilter('concerns'); setIdeasPage(0); }}>{t('dashboard:topConcerns.concernsTab')}</button>
                <button type="button" role="tab" aria-selected={ideaFilter === 'all'} className={`source-type-tab ${ideaFilter === 'all' ? 'active' : ''}`} onClick={() => { setIdeaFilter('all'); setIdeasPage(0); }}>{t('dashboard:topConcerns.allTab')}</button>
              </div>
              <div
                className="language-switcher"
                role="group"
                aria-label={t('dashboard:ideas.outputLanguage.label')}
                title={ideasTranslating ? t('dashboard:ideas.outputLanguage.translating') : t('dashboard:ideas.outputLanguage.hint')}
                aria-busy={ideasTranslating}
              >
                <Languages size={14} aria-hidden="true" className={`language-switcher-icon${ideasTranslating ? ' spin' : ''}`} />
                {SUPPORTED_LOCALES.map((code) => (
                  <button
                    key={code}
                    type="button"
                    lang={code}
                    dir={isRtlLocale(code) ? 'rtl' : 'ltr'}
                    className={`language-switcher-option${code === ideasLocale ? ' is-active' : ''}`}
                    aria-pressed={code === ideasLocale}
                    disabled={ideasTranslating}
                    onClick={() => { setIdeasLocale(code); setIdeasPage(0); }}
                  >
                    {LOCALE_NATIVE_NAMES[code]}
                  </button>
                ))}
              </div>
            </div>
            {visibleIdeas.map((idea) => <IdeaRow key={idea.idea} idea={idea} maxFrequency={maxIdeaFrequency} projectId={selectedProjectId} />)}
            {!visibleIdeas.length && <p className="intelligence-empty">{ideaFilter === 'concerns' ? t('dashboard:topConcerns.empty') : t('dashboard:ideas.empty')}</p>}
            {ideasTotalPages > 1 ? (
              <div className="intelligence-idea-comparison-pagination">
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => setIdeasPage((current) => Math.max(0, current - 1))}
                  disabled={safeIdeasPage === 0}
                >
                  <ChevronLeft size={14} className="rtl-mirror" /> {t('common:actions.previous')}
                </button>
                <span className="intelligence-idea-comparison-pagination-status">
                  {t('common:pagination.pageOfTotal', { page: safeIdeasPage + 1, totalPages: ideasTotalPages })}
                </span>
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => setIdeasPage((current) => Math.min(ideasTotalPages - 1, current + 1))}
                  disabled={safeIdeasPage >= ideasTotalPages - 1}
                >
                  {t('common:actions.next')} <ChevronRight size={14} className="rtl-mirror" />
                </button>
              </div>
            ) : null}
          </article>
        </section>

        <section className="intelligence-top-grid">
          <article className="glass-card intelligence-card intelligence-sentiment-card"><h3>{t('dashboard:sentimentBreakdown.title')}</h3><p className="subtitle">{t('dashboard:sentimentBreakdown.denominator', { assessed: formatNumber(total, locale), total: formatNumber(populationTotal, locale), notAssessed: formatNumber(notAssessedTotal, locale) })}</p><div className="intelligence-sentiment-layout"><div className="intelligence-donut"><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={sentimentData} dataKey="value" innerRadius="63%" outerRadius="84%" paddingAngle={3} stroke="none" className="intelligence-clickable-chart" onClick={(sector) => openBucket('sentiment', sliceValue(sector, 'name'))}>{sentimentData.map((entry) => <Cell key={entry.name} fill={SENTIMENT_COLORS[entry.name]} />)}</Pie><Tooltip formatter={(value, name) => [t('dashboard:counts.articlesCount', { count: value }), sentimentLabel(t, name)]} /></PieChart></ResponsiveContainer><strong>{formatNumber(data.net_sentiment || 0, locale, { signDisplay: 'always', maximumFractionDigits: 0 })}</strong><span>{t('dashboard:sentimentBreakdown.netSentimentCaption')}</span></div><div className="intelligence-legend">{sentimentData.map((entry) => <LegendRow key={entry.name} to={entry.value > 0 ? bucketPath('sentiment', entry.name) : null} title={openArticlesTitle(sentimentLabel(t, entry.name))}><span style={{ background: SENTIMENT_COLORS[entry.name] }} /><label>{sentimentLabel(t, entry.name)}</label><strong>{formatPercent(percent(entry.value, total), locale, { alreadyWhole: true })}</strong></LegendRow>)}</div></div></article>
          <article className="glass-card intelligence-card intelligence-radar-card"><h3>{t('dashboard:emotionalSignature.title')}</h3><ResponsiveContainer width="100%" height={285}><RadarChart data={data.emotional_signature || []} outerRadius={RADAR_OUTER_RADIUS} className="intelligence-clickable-chart" onClick={(state) => openBucket('emotion', state?.activeLabel)}><PolarGrid /><PolarAngleAxis dataKey="axis" tick={<RadarAngleTick formatLabel={(value) => emotionAxisLabel(t, value)} />} /><PolarRadiusAxis angle={30} domain={[0, 100]} tick={false} /><Radar dataKey="value" stroke="#2563eb" fill="#2563eb" fillOpacity={0.22} /></RadarChart></ResponsiveContainer><p>{t('dashboard:emotionalSignature.description')}</p></article>
          <article className="glass-card intelligence-card"><h3>{t('dashboard:sentimentByPlatform.title')}</h3><div className="intelligence-platform-sentiment">{platformData.map((item) => <div key={item.platform}>{item.total > 0 ? <Link className="intelligence-platform-sentiment-name" to={bucketPath('platform', item.platform)} title={openArticlesTitle(item.platform)} dir="auto">{item.platform}</Link> : <span dir="auto">{item.platform}</span>}<div>{SENTIMENT_KEYS.map((tone) => { const label = t('dashboard:sentimentByPlatform.tooltipTitle', { tone: sentimentLabel(t, tone), count: item[tone] || 0 }); const style = { width: `${percent(item[tone], Math.max(1, item.total))}%`, background: SENTIMENT_COLORS[tone] }; return item[tone] > 0 ? <Link key={tone} to={evidencePath({ platform: item.platform, sentiment: tone })} title={label} aria-label={`${item.platform}, ${label}`} style={style} /> : <i key={tone} title={label} style={style} />; })}</div></div>)}</div></article>
        </section>

        <section className="intelligence-bottom-grid">
          <article className={`glass-card intelligence-card${selectedProject?.mode === 'competitor' ? ' intelligence-card-full' : ''}`}>
            <h3>{t('dashboard:wherePosted.title')}</h3>
            <div className="intelligence-platform-list">{pagedPlatformData.map((item) => { const row = <><div><strong dir="auto">{item.platform}</strong></div><div className="intelligence-track"><span style={{ width: `${percent(item.total, total)}%` }} /></div><div className="intelligence-platform-count"><strong>{formatNumber(item.total, locale)}</strong><small>{t('dashboard:counts.articleUnit', { count: item.total })}</small></div></>; return item.total > 0 ? <Link key={item.platform} className="intelligence-platform-link" to={bucketPath('platform', item.platform)} title={openArticlesTitle(item.platform)}>{row}</Link> : <div key={item.platform}>{row}</div>; })}</div>
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
          {selectedProject?.mode !== 'competitor' ? <article className="glass-card intelligence-card"><h3>{t('dashboard:trending.title')}</h3><div className="intelligence-term-list">{(data.trending_terms || []).filter((term) => term.mentions > 0).map((term) => <Link key={`${term.kind}-${term.term}`} to={evidencePath({ search: term.term.replace(/^#/, '') })} className={`intelligence-term-link ${term.kind}`} title={t('dashboard:trending.linkTitle', { term: term.term })}><b dir="auto">{term.term}</b> <em>{formatNumber(term.mentions, locale)}</em></Link>)}{!(data.trending_terms || []).some((term) => term.mentions > 0) && <p className="intelligence-empty">{t('dashboard:trending.empty')}</p>}</div></article> : null}
        </section>

        <section className="intelligence-idea-comparisons-grid">
          <article className="glass-card intelligence-card intelligence-idea-comparisons-card">
            <div className="intelligence-card-heading">
              <div>
                <h3>{t('dashboard:ideaComparisons.title')}</h3>
                <span>{t('dashboard:ideaComparisons.subtitle')}</span>
              </div>
              <div
                className="language-switcher"
                role="group"
                aria-label={t('dashboard:ideaComparisons.outputLanguage.label')}
                title={ideaComparisonsLoading ? t('dashboard:ideaComparisons.outputLanguage.translating') : t('dashboard:ideaComparisons.outputLanguage.hint')}
                aria-busy={ideaComparisonsLoading}
              >
                <Languages size={14} aria-hidden="true" className={`language-switcher-icon${ideaComparisonsLoading ? ' spin' : ''}`} />
                {SUPPORTED_LOCALES.map((code) => (
                  <button
                    key={code}
                    type="button"
                    lang={code}
                    dir={isRtlLocale(code) ? 'rtl' : 'ltr'}
                    className={`language-switcher-option${code === ideaComparisonsLocale ? ' is-active' : ''}`}
                    aria-pressed={code === ideaComparisonsLocale}
                    disabled={ideaComparisonsLoading || ideaComparisonsRegenerating}
                    onClick={() => setIdeaComparisonsLocale(code)}
                  >
                    {LOCALE_NATIVE_NAMES[code]}
                  </button>
                ))}
              </div>
              <button
                type="button"
                className="btn-secondary"
                onClick={regenerateIdeaComparisons}
                disabled={ideaComparisonsRegenerating || !selectedProjectId}
                style={{ padding: '6px 10px', fontSize: '0.78rem', display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}
              >
                {ideaComparisonsRegenerating ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} />}
                {ideaComparisonsRegenerating
                  ? t('dashboard:ideaComparisons.regeneratingElapsed', { seconds: ideaComparisonsElapsedSeconds })
                  : t('common:actions.regenerate')}
              </button>
            </div>
            {ideaComparisonsTruncated ? (
              <p className="intelligence-empty" dir="auto">
                {t('dashboard:ideaComparisons.timedOutPartial', ideaComparisonsTruncated)}
              </p>
            ) : null}
            {ideaComparisonsError ? (
              <p className="intelligence-empty" dir="auto">{ideaComparisonsError}</p>
            ) : ideaComparisonsLoading ? (
              <p className="intelligence-empty"><Loader2 size={14} className="spin" /> {t('dashboard:ideaComparisons.loading')}</p>
            ) : ideaComparisonsRegenerating && ideaComparisons.length === 0 ? (
              <p className="intelligence-empty"><Loader2 size={14} className="spin" /> {t('dashboard:ideaComparisons.regenerating')}</p>
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
                          state={{ from: `${location.pathname}${location.search}`, locale: ideaComparisonsLocale }}
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
          <article className="glass-card intelligence-card intelligence-pipeline-card"><div className="intelligence-card-heading"><h3>{t('dashboard:articlesByRun.title')}</h3>{latestRun && <Change value={latestRun.change_pct} />}</div>{(data.pipeline_discovery || []).length ? <ResponsiveContainer width="100%" height={240}><LineChart data={data.pipeline_discovery} className="intelligence-clickable-chart" onClick={(state) => openRunPoint(data.pipeline_discovery, state)}><CartesianGrid strokeDasharray="3 3" stroke="rgba(15,23,42,.09)" /><XAxis dataKey="completed_at" tickFormatter={(value, index) => pipelineRunShortLabel(data.pipeline_discovery[index], index, t)} minTickGap={18} /><YAxis allowDecimals={false} /><Tooltip labelFormatter={(value, payload) => { const item = payload?.[0]?.payload; return item ? `${pipelineRunShortLabel(item, 0, t)} · ${formatDate(item.completed_at, locale)}` : value; }} formatter={(value) => [t('dashboard:counts.articlesCount', { count: value }), t('dashboard:articlesByRun.tooltipLabel')]} /><Line type="monotone" dataKey="articles_discovered" stroke="#2563eb" strokeWidth={3} dot={{ r: 4 }} /></LineChart></ResponsiveContainer> : <p className="intelligence-empty">{t('dashboard:articlesByRun.empty')}</p>}</article>
          <article className="glass-card intelligence-card intelligence-run-sentiment-card">
            <h3>{t('dashboard:sentimentAcrossRuns.title')}</h3>
            {(data.sentiment_by_pipeline_run || []).some((run) => run.total > 0) ? <ResponsiveContainer width="100%" height={240}><LineChart data={data.sentiment_by_pipeline_run} className="intelligence-clickable-chart" onClick={(state) => openRunPoint(data.sentiment_by_pipeline_run, state)}><CartesianGrid strokeDasharray="3 3" stroke="rgba(15,23,42,.09)" /><XAxis dataKey="completed_at" tickFormatter={(value, index) => pipelineRunShortLabel(data.sentiment_by_pipeline_run[index], index, t)} minTickGap={18} /><YAxis domain={[-100, 100]} tickFormatter={(value) => formatNumber(value, locale, { signDisplay: 'always', maximumFractionDigits: 0 })} /><Tooltip labelFormatter={(value, payload) => { const item = payload?.[0]?.payload; return item ? `${pipelineRunShortLabel(item, 0, t)} · ${formatDate(item.completed_at, locale)}` : value; }} formatter={(value) => [formatNumber(value, locale, { signDisplay: 'always', maximumFractionDigits: 0 }), t('dashboard:sentimentAcrossRuns.tooltipLabel')]} /><ReferenceLine y={0} stroke="rgba(15,23,42,.25)" /><Line type="monotone" dataKey="net_sentiment" name={t('dashboard:sentimentAcrossRuns.tooltipLabel')} stroke={SENTIMENT_COLORS.positive} strokeWidth={2} dot={{ r: 4 }} /></LineChart></ResponsiveContainer> : <p className="intelligence-empty">{t('dashboard:sentimentAcrossRuns.empty')}</p>}
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
          {/* Always rendered so the toggle's aria-controls resolves; the
              charts themselves only mount while it's open. */}
          <div id="intelligence-detailed-breakdowns-panel" className="intelligence-language-grid" hidden={!detailedBreakdownsOpen}>
            {detailedBreakdownsOpen ? (<>
              <DistributionCard title={t('dashboard:distributions.language.title')} linkFor={(value) => bucketPath('language', value)} entries={languageData} nameKey="language" valueKey="count" valueTotal={total} colorFor={paletteColor} labelFor={(code) => languageLabel(t, locale, code)} emptyText={t('dashboard:distributions.language.empty')} />
              <DistributionCard title={t('dashboard:distributions.region.title')} linkFor={(value) => bucketPath('region', value)} entries={regionData} nameKey="value" valueKey="total" valueTotal={total} colorFor={paletteColor} labelFor={(value) => distributionLabel(t, value)} emptyText={t('dashboard:distributions.region.empty')} />
              <DistributionCard title={t('dashboard:distributions.gender.title')} linkFor={(value) => bucketPath('gender', value)} entries={genderData} nameKey="value" valueKey="total" valueTotal={total} colorFor={paletteColor} labelFor={(value) => distributionLabel(t, value)} emptyText={t('dashboard:distributions.gender.empty')} />
              <DistributionCard title={t('dashboard:distributions.ageRange.title')} linkFor={(value) => bucketPath('age_range', value)} entries={ageRangeData} nameKey="value" valueKey="total" valueTotal={total} colorFor={paletteColor} labelFor={(value) => distributionLabel(t, value)} emptyText={t('dashboard:distributions.ageRange.empty')} />
              <DistributionCard title={t('dashboard:distributions.segment.title')} linkFor={(value) => bucketPath('segment', value)} entries={segmentData} nameKey="value" valueKey="total" valueTotal={total} colorFor={paletteColor} labelFor={(value) => distributionLabel(t, value)} emptyText={t('dashboard:distributions.segment.empty')} />
              <DistributionCard title={t('dashboard:sourceTrust.title')} linkFor={(value) => bucketPath('trust', value)} entries={trustData} nameKey="tier" valueKey="articles" valueTotal={data.source_trust?.total_articles || 0} colorFor={(entry) => TRUST_TIER_COLORS[entry.tier]} labelFor={(tier) => trustTierLabel(t, tier)} emptyText={t('dashboard:sourceTrust.empty')} />
            </>) : null}
          </div>
        </section>
      </>}
    </>) : null}
  </div>;
}
