import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, Briefcase, CalendarRange, CircleMinus, FileText, Globe2, RefreshCw, Tag, ThumbsDown, ThumbsUp, Users } from 'lucide-react';
import { CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import SearchableSelect from './SearchableSelect';
import DemographicPieCarousel from './DemographicPieCarousel';
import '../styles/IntelligenceDashboard.css';

const COLORS = { positive: '#16a34a', neutral: '#64748b', negative: '#e11d48', mixed: '#f59e0b' };
// Categorical palette for keyword lines (validated CVD-safe order, see dataviz skill).
const KEYWORD_COLORS = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#e34948'];

function percent(value, total) { return total ? Math.round((Number(value || 0) / total) * 100) : 0; }
function formatDate(value) { const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }); }

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
  return <article className={`report-feedback-column ${tone}`}><h4>{icon}{title}</h4>{items.length ? <ul>{items.slice(0, 5).map((item) => {
    const label = item.text || item.idea;
    const count = item.count || item.frequency_estimate || 1;
    if (!projectId || !item.sources?.length) {
      return <li key={label}>{label}<strong>{count}</strong></li>;
    }
    return <li key={label}>
      <Link
        className="feedback-topic-link"
        to={`/projects/${projectId}/topics`}
        state={{ idea: label, type: item.type, category: item.category, frequencyEstimate: item.frequency_estimate || item.count, sources: mapTopicSources(item.sources), backTo: '/reports', backLabel: 'Back to Reports' }}
        style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 10, width: '100%', color: 'inherit', textDecoration: 'none' }}
      >
        {label}<strong>{count}</strong>
      </Link>
    </li>;
  })}</ul> : <p>No signals in this category yet.</p>}</article>;
}

export default function StatsOverview({ intelligence = {}, scopeLabel, loading, error, onRetry, project = null, period = 'all', runId = null }) {
  const projectId = project?.id ?? null;

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
      label: document.original_filename || `Document #${document.id}`,
    })),
    [documents],
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
    fetch(`/api/projects/${projectId}/documents`)
      .then((res) => (res.ok ? res.json() : { documents: [] }))
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
    const params = new URLSearchParams({ period });
    if (sourceFilter !== 'all') params.set('source_url', sourceFilter);
    if (keywordFilter !== 'all') params.set('keyword', keywordFilter);
    if (runId) params.set('run_id', runId);
    fetch(`/api/projects/${projectId}/keyword-existence?${params.toString()}`)
      .then((res) => {
        if (!res.ok) throw new Error(`Keyword existence request failed: ${res.status}`);
        return res.json();
      })
      .then((data) => { if (!cancelled) setKeywordReport(data); })
      .catch((err) => {
        if (!cancelled) {
          console.error('Failed to load keyword existence', err);
          setKeywordReport(null);
          setKeywordError(err?.message || 'Failed to load keyword existence');
        }
      })
      .finally(() => { if (!cancelled) setKeywordLoading(false); });
    return () => { cancelled = true; };
  }, [projectId, period, runId, sourceFilter, keywordFilter, configuredKeywords.length]);

  useEffect(() => {
    if (projectId == null || totalArticles === 0) {
      setTrendSummary(null);
      setTrendSummaryError(null);
      setTrendSummaryLoading(false);
      return undefined;
    }
    let cancelled = false;
    setTrendSummaryLoading(true);
    setTrendSummaryError(null);
    const params = new URLSearchParams({ period });
    if (runId) params.set('run_id', runId);
    fetch(`/api/projects/${projectId}/trend-summary?${params.toString()}`)
      .then(async (res) => ({ ok: res.ok, data: await res.json().catch(() => ({})) }))
      .then(({ ok, data }) => {
        if (cancelled) return;
        if (!ok || data?.error) {
          setTrendSummary(null);
          setTrendSummaryError(data?.error || 'Failed to generate the trend summary');
          return;
        }
        setTrendSummary(data);
      })
      .catch((err) => {
        if (!cancelled) {
          console.error('Failed to load trend summary', err);
          setTrendSummary(null);
          setTrendSummaryError(err?.message || 'Failed to generate the trend summary');
        }
      })
      .finally(() => { if (!cancelled) setTrendSummaryLoading(false); });
    return () => { cancelled = true; };
  }, [projectId, period, runId, totalArticles, trendSummaryNonce]);

  if (loading) return <section className="report-brief glass-card intelligence-loading">Loading the live intelligence brief…</section>;
  if (error) return <section className="report-brief"><div className="glass-card admin-empty-state report-error-state" role="alert"><div className="admin-empty-state-icon"><AlertTriangle size={20} /></div><strong>Couldn’t load this report</strong><p className="subtitle">{error}</p>{onRetry && <button className="btn-secondary" type="button" onClick={onRetry}>Try again</button>}</div></section>;

  const total = totalArticles;
  if (!total) return <section className="report-brief"><div className="glass-card admin-empty-state"><strong>No analyzed articles yet</strong><p className="subtitle">Run an analysis for {scopeLabel || 'this project'} or broaden the date range to generate a report.</p><Link to="/pipeline-runs" className="btn-secondary">Go to Analysis Runs</Link></div></section>;

  const sentiments = ['positive', 'neutral', 'negative', 'mixed'].map((name) => ({ name, value: Number(intelligence[name] || 0) }));
  const insights = intelligence.insights || {};
  const leadingIdea = insights.frequent_ideas?.[0]?.idea;
  const leadingConcern = insights.negative_feedback?.[0]?.text || insights.complaints?.[0]?.text;
  const headline = leadingIdea
    ? `${scopeLabel} generated ${total.toLocaleString()} analyzed articles. The leading conversation theme is ${leadingIdea}${leadingConcern ? `, while ${leadingConcern} is the primary concern` : ''}.`
    : `${scopeLabel} generated ${total.toLocaleString()} analyzed articles with a net sentiment of ${intelligence.net_sentiment >= 0 ? '+' : ''}${intelligence.net_sentiment}.`;

  const keywordSeriesData = keywordReport?.series || [];
  const isMultiKeyword = Boolean(keywordReport?.all_keywords);
  const keywordSeriesKeys = isMultiKeyword
    ? (keywordReport?.selected_keywords?.length ? keywordReport.selected_keywords : configuredKeywords)
    : ['matches'];
  const keywordHasMatches = keywordSeriesData.some((point) => keywordSeriesKeys.some((key) => Number(point[key] || 0) > 0));

  return <section className="report-brief">
    <Section
      number="01"
      title="Executive summary"
      actions={
        <button
          type="button"
          className="report-trend-refresh-btn"
          onClick={() => setTrendSummaryNonce((n) => n + 1)}
          disabled={trendSummaryLoading}
          aria-busy={trendSummaryLoading}
          aria-label="Regenerate the AI trend summary"
          title="Regenerate the AI trend summary"
        >
          <RefreshCw size={13} className={trendSummaryLoading ? 'spin' : ''} />
        </button>
      }
    >
      <p className="report-brief-summary">{trendSummary?.summary || headline}</p>
      {trendSummaryLoading ? <p className="report-trend-summary-status">Generating AI trend summary…</p> : null}
      {!trendSummaryLoading && trendSummaryError ? (
        <p className="report-trend-summary-status report-trend-summary-error">
          Couldn't generate an AI trend summary right now — showing a quick overview instead.
        </p>
      ) : null}
      <div className="report-brief-metrics">
        <div><strong>{total.toLocaleString()}</strong><span>Analyzed articles</span></div>
        <div><strong className={intelligence.net_sentiment >= 0 ? 'positive-text' : 'negative-text'}>{intelligence.net_sentiment >= 0 ? '+' : ''}{intelligence.net_sentiment}</strong><span>Net sentiment</span></div>
        <div><strong>{Number(intelligence.document_count || 0).toLocaleString()}</strong><span>Documents</span></div>
      </div>
    </Section>

    <Section number="02" title="Sentiment analysis">
      <div className="report-sentiment-grid"><div className="report-donut"><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={sentiments} dataKey="value" innerRadius="58%" outerRadius="82%" paddingAngle={3} stroke="none">{sentiments.map((entry) => <Cell key={entry.name} fill={COLORS[entry.name]} />)}</Pie><Tooltip formatter={(value, name) => [`${value} articles`, name]} /></PieChart></ResponsiveContainer></div><div className="report-sentiment-bars">{sentiments.map((entry) => <div key={entry.name}><span><i style={{ background: COLORS[entry.name] }} />{entry.name}</span><div><b style={{ width: `${percent(entry.value, total)}%`, background: COLORS[entry.name] }} /></div><strong>{percent(entry.value, total)}%</strong></div>)}<p>Sentiment is calculated from the analyzed article content already stored for this project.</p></div></div>
    </Section>

    <Section number="03" title="Keyword existence">
      {configuredKeywords.length === 0 ? (
        <div className="glass-card admin-empty-state intelligence-keyword-empty">
          <strong>No keywords configured</strong>
          <p className="subtitle">Add keywords to {scopeLabel || 'this project'} to track how often they show up in analyzed articles over time.</p>
          <Link to="/projects" className="btn-secondary">Manage project keywords</Link>
        </div>
      ) : (
        <>
          <div className="keyword-existence-filters">
            <SearchableSelect
              label="Document"
              icon={<FileText size={13} />}
              value={sourceFilter}
              onChange={setSourceFilter}
              options={documentOptions}
              allLabel="All documents"
              placeholder="Search documents…"
              disabled={documentOptions.length === 0}
            />
            <SearchableSelect
              label="Keyword"
              icon={<Tag size={13} />}
              value={keywordFilter}
              onChange={setKeywordFilter}
              options={keywordOptions}
              allLabel="All keywords"
              placeholder="Search keywords…"
            />
          </div>

          {keywordLoading ? (
            <p className="intelligence-empty">Loading keyword existence…</p>
          ) : keywordError ? (
            <div className="glass-card admin-empty-state report-error-state" role="alert">
              <div className="admin-empty-state-icon"><AlertTriangle size={20} /></div>
              <strong>Couldn’t load keyword existence</strong>
              <p className="subtitle">{keywordError}</p>
            </div>
          ) : !keywordHasMatches ? (
            <div className="glass-card admin-empty-state">
              <strong>No matches for this filter</strong>
              <p className="subtitle">No analyzed articles matched the selected source and keyword combination in this date range.</p>
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={keywordSeriesData}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(15,23,42,.09)" />
                <XAxis dataKey="date" tickFormatter={formatDate} minTickGap={24} />
                <YAxis allowDecimals={false} />
                <Tooltip labelFormatter={formatDate} />
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

    <Section number="04" title="Volume trend">
      <ResponsiveContainer width="100%" height={285}><LineChart data={intelligence.sentiment_over_time || []}><CartesianGrid strokeDasharray="3 3" stroke="rgba(15,23,42,.09)" /><XAxis dataKey="date" tickFormatter={formatDate} minTickGap={24} /><YAxis allowDecimals={false} /><Tooltip labelFormatter={formatDate} /><Legend /><Line dataKey="total" name="Total" type="monotone" stroke="#2563eb" strokeWidth={2.5} dot={false} /><Line dataKey="positive" name="Positive" type="monotone" stroke={COLORS.positive} strokeWidth={2} dot={false} /><Line dataKey="negative" name="Negative" type="monotone" stroke={COLORS.negative} strokeWidth={2} dot={false} /></LineChart></ResponsiveContainer>
    </Section>

    <Section number="05" title="Categorized feedback">
      <div className="report-feedback-grid"><FeedbackColumn title="Positive drivers" icon={<ThumbsUp size={16} />} tone="positive" items={insights.positive_feedback || []} projectId={projectId} /><FeedbackColumn title="Negative drivers" icon={<ThumbsDown size={16} />} tone="negative" items={insights.negative_feedback || []} projectId={projectId} /><FeedbackColumn title="Neutral / mixed" icon={<CircleMinus size={16} />} tone="neutral" items={(insights.frequent_ideas || []).filter((item) => !['praise', 'complaint'].includes(item.type))} projectId={projectId} /></div>
    </Section>

    <Section number="06" title="Sentiment by demographics">
      <p className="report-demographics-intro">
        How sentiment splits across the people quoted or mentioned in analyzed articles - based only on explicit signal in the text, not inferred or guessed.
      </p>
      <div className="report-demographics-grid">
        <div className="report-demographics-block">
          <h4><Users size={16} />Gender</h4>
          <DemographicPieCarousel data={insights.gender_breakdown} emptyLabel="No gender detected on analyzed articles yet." />
        </div>
        <div className="report-demographics-block">
          <h4><Globe2 size={16} />Region</h4>
          <DemographicPieCarousel data={insights.region_breakdown} emptyLabel="No region detected on analyzed articles yet." />
        </div>
        <div className="report-demographics-block">
          <h4><CalendarRange size={16} />Age range</h4>
          <DemographicPieCarousel data={insights.age_range_breakdown} emptyLabel="No age range detected on analyzed articles yet." />
        </div>
        <div className="report-demographics-block">
          <h4><Briefcase size={16} />Segment</h4>
          <DemographicPieCarousel data={insights.segment_breakdown} emptyLabel="No life-situation/occupation segment detected on analyzed articles yet." />
        </div>
      </div>
    </Section>
  </section>;
}
