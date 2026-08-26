import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import {
  Activity, ChevronRight, FileText, Gauge, Network, Sparkles, TrendingDown, TrendingUp,
} from 'lucide-react';
import {
  CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, Radar, RadarChart,
  PolarAngleAxis, PolarGrid, PolarRadiusAxis, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import '../styles/IntelligenceDashboard.css';
import CompetitorPulseCard from './CompetitorPulseCard.jsx';

const PERIODS = [
  { key: '7d', label: 'Last 7 days' },
  { key: '30d', label: 'Last 30 days' },
  { key: 'all', label: 'All time' },
];
const SENTIMENT_COLORS = { positive: '#16a34a', neutral: '#64748b', negative: '#e11d48', mixed: '#f59e0b' };
// Fixed semantic colors for the binary verified/unverified split - unlike
// region/gender/segment this is never an open-ended category set, so it
// doesn't cycle through LANGUAGE_COLORS.
const VERIFIED_COLORS = { verified: '#16a34a', unverified: '#94a3b8' };
// Categorical palette for language slices (open-ended set, unlike the fixed 4 sentiments) -
// same validated CVD-safe order used for keyword lines in StatsOverview.jsx.
const LANGUAGE_COLORS = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#e34948'];

function languageLabel(code) {
  if (!code || code === 'unknown') return 'Unknown';
  if (code === 'other') return 'Other';
  try {
    const name = new Intl.DisplayNames(['en'], { type: 'language' }).of(code);
    return name ? `${name} (${code.toUpperCase()})` : code.toUpperCase();
  } catch {
    return code.toUpperCase();
  }
}

// Labels the demographic breakdown APIs' bucket values (region/gender/age_range)
// - see backend/services/articles/articles_store.py's _demographic_sentiment_breakdown.
function distributionLabel(value) {
  return String(value || 'unknown')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
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

function formatDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function Change({ value }) {
  if (value == null) return <span className="intelligence-change neutral">First completed run</span>;
  const positive = value >= 0;
  const Icon = positive ? TrendingUp : TrendingDown;
  return <span className={`intelligence-change ${positive ? 'positive' : 'negative'}`}><Icon size={13} />{positive ? '+' : ''}{value}% vs previous</span>;
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
  const body = <>
    <div><strong>{idea.idea}</strong><span>{idea.type || 'issue'}</span></div>
    <strong>{Number(idea.frequency_estimate || 0).toLocaleString()}</strong>
    <div className="intelligence-track"><span style={{ width: `${Math.max(8, percent(idea.frequency_estimate, maxFrequency))}%` }} /></div>
  </>;
  if (projectId && idea.sources?.length) {
    return <Link
      className={`intelligence-idea intelligence-idea-clickable ${idea.type || 'issue'}`}
      style={{ textDecoration: 'none', color: 'inherit' }}
      to={`/projects/${projectId}/topics`}
      state={{ idea: idea.idea, type: idea.type, category: idea.category, frequencyEstimate: idea.frequency_estimate, sources: mapTopicSources(idea.sources), backTo: '/dashboard', backLabel: 'Back to Dashboard' }}
    >
      {body}
    </Link>;
  }
  return <div className={`intelligence-idea ${idea.type || 'issue'}`}>{body}</div>;
}

function formatRunLabel(run) {
  const value = run?.finished_at || run?.created_at;
  const date = value ? new Date(value) : null;
  if (!date || Number.isNaN(date.getTime())) return 'Run';
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
    + ' ' + date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
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
function pipelineRunTitle(run, index) {
  return `Analysis #${pipelineRunNumber(run, index)}: ${formatRunLabel(run)}`;
}

// Compact label for summary spots (metric cards, the "showing run" note)
// where the number alone is already unambiguous and a repeated date/time is
// just clutter.
function pipelineRunShortLabel(run, index) {
  return `Analysis #${pipelineRunNumber(run, index)}`;
}

export default function DashboardOverview({
  projects, selectedProjectId, onProjectChange, period, onPeriodChange, intelligence,
  loading, error, pipelineHealth, runs = [], selectedRunId, onRunChange,
}) {
  const data = intelligence || {};
  const total = Number(data.total || 0);
  const sentimentData = ['positive', 'neutral', 'negative', 'mixed'].map((name) => ({ name, value: Number(data[name] || 0) }));
  const latestRun = data.pipeline_discovery?.[data.pipeline_discovery.length - 1];
  const platformData = data.platforms || [];
  const languageData = capLanguageBreakdown(data.insights?.language_breakdown || []);
  const regionData = capBreakdown((data.insights?.region_breakdown || []).filter((entry) => entry.total > 0));
  const genderData = capBreakdown((data.insights?.gender_breakdown || []).filter((entry) => entry.total > 0));
  const ageRangeData = capBreakdown((data.insights?.age_range_breakdown || []).filter((entry) => entry.total > 0));
  const segmentData = capBreakdown((data.insights?.segment_breakdown || []).filter((entry) => entry.total > 0));
  const verifiedData = (data.insights?.verified_breakdown || []).filter((entry) => entry.total > 0);
  const selectedProject = useMemo(() => projects.find((project) => Number(project.id) === Number(selectedProjectId)), [projects, selectedProjectId]);
  const selectedRunIndex = selectedRunId ? runs.findIndex((run) => run.id === selectedRunId) : -1;
  const selectedRun = selectedRunIndex >= 0 ? runs[selectedRunIndex] : null;

  return <div className="content-shell intelligence-page">
    <header className="intelligence-header">
      <div>
        <span className="intelligence-eyebrow"><Sparkles size={14} /> Intelligence dashboard</span>
        <h2>Project intelligence</h2>
        <p className="subtitle">Signals from the documents and articles already analyzed for this project.</p>
        <div className="filter-tabs-shell">
          <div className="filter-tab-buttons filter-mode-toggle" role="tablist" aria-label="Filter type">
            <button type="button" role="tab" aria-selected={!selectedRunId} className={`source-type-tab ${!selectedRunId ? 'active' : ''}`} onClick={() => onRunChange?.(null)}>Date range</button>
            {runs.length > 0 ? <button type="button" role="tab" aria-selected={!!selectedRunId} className={`source-type-tab ${selectedRunId ? 'active' : ''}`} onClick={() => onRunChange?.(selectedRunId || runs[0].id)}>Analysis run</button> : null}
          </div>
          <div className="filter-tab-divider" aria-hidden="true" />
          {selectedRunId ? (
            runs.length > 3 ? (
              <select className="filter-select filter-run-select" value={selectedRunId} onChange={(event) => onRunChange?.(event.target.value)} aria-label="Filter by analysis run">
                {runs.map((run, index) => <option key={run.id} value={run.id}>{pipelineRunTitle(run, index)}</option>)}
              </select>
            ) : (
              <div className="filter-tab-buttons scrollable" role="tablist" aria-label="Filter by analysis run">
                {runs.map((run, index) => <span key={run.id} className="filter-tab-run-item">{index > 0 ? <ChevronRight size={14} className="filter-tab-arrow" aria-hidden="true" /> : null}<button type="button" role="tab" aria-selected={selectedRunId === run.id} className={`source-type-tab ${selectedRunId === run.id ? 'active' : ''}`} onClick={() => onRunChange?.(run.id)}>{pipelineRunTitle(run, index)}</button></span>)}
              </div>
            )
          ) : (
            <div className="filter-tab-buttons" role="tablist" aria-label="Dashboard date range">
              {PERIODS.map((item) => <button key={item.key} type="button" role="tab" aria-selected={period === item.key} className={`source-type-tab ${period === item.key ? 'active' : ''}`} onClick={() => onPeriodChange(item.key)}>{item.label}</button>)}
            </div>
          )}
        </div>
      </div>
      <div className="intelligence-controls">
        <select className="filter-select" value={selectedProjectId ?? ''} onChange={(event) => onProjectChange(Number(event.target.value))} disabled={!projects.length} aria-label="Dashboard project">
          {projects.map((project) => <option value={project.id} key={project.id}>{project.name}</option>)}
        </select>
      </div>
    </header>

    {selectedRun ? <p className="intelligence-run-note">Showing {pipelineRunTitle(selectedRun, selectedRunIndex)}.</p> : null}

    {selectedProject?.mode === 'competitor' ? (
      <CompetitorPulseCard studyId={selectedProject.id} backTo="/dashboard" backLabel="Back to dashboard" />
    ) : null}

    {!selectedProject ? <div className="glass-card admin-empty-state"><strong>No project selected</strong><p className="subtitle">Create a project to begin tracking intelligence.</p></div> : null}
    {error ? <div className="glass-card admin-empty-state"><strong>Couldn’t load project intelligence</strong><p className="subtitle">{error}</p></div> : null}

    {selectedProject && !error ? (<>
      <section className="intelligence-metric-grid" aria-busy={loading}>
        <MetricCard icon={<Activity size={18} />} label="Analysis health" value={pipelineHealth?.lastRun?.status || 'No runs'} detail={pipelineHealth?.lastFinished ? `Last completed ${formatDate(pipelineHealth.lastFinished.finished_at)}` : 'No completed runs yet'} tone="blue" />
        <MetricCard icon={<Network size={18} />} label="Analyzed articles" value={loading ? '—' : total.toLocaleString()} detail={selectedRun ? pipelineRunTitle(selectedRun, selectedRunIndex) : PERIODS.find((item) => item.key === period)?.label} tone="blue" />
        <MetricCard icon={<Gauge size={18} />} label="Net sentiment" value={loading ? '—' : `${Number(data.net_sentiment || 0) >= 0 ? '+' : ''}${data.net_sentiment || 0}`} detail="Positive minus negative" tone={Number(data.net_sentiment || 0) >= 0 ? 'positive' : 'negative'} />
        <MetricCard icon={<FileText size={18} />} label="Documents" value={loading ? '—' : Number(data.document_count || 0).toLocaleString()} detail="Uploaded to this project" tone="blue" />
      </section>

      {loading ? <div className="glass-card intelligence-loading">Loading intelligence…</div> : total === 0 ? <div className="glass-card admin-empty-state"><strong>No analyzed articles in this period</strong><p className="subtitle">Run an analysis or choose a broader time range to populate this dashboard.</p></div> : <>
        <section className="intelligence-top-grid">
          <article className="glass-card intelligence-card intelligence-sentiment-card"><h3>Sentiment breakdown</h3><div className="intelligence-sentiment-layout"><div className="intelligence-donut"><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={sentimentData} dataKey="value" innerRadius="63%" outerRadius="84%" paddingAngle={3} stroke="none">{sentimentData.map((entry) => <Cell key={entry.name} fill={SENTIMENT_COLORS[entry.name]} />)}</Pie><Tooltip formatter={(value, name) => [`${value} articles`, name]} /></PieChart></ResponsiveContainer><strong>{data.net_sentiment >= 0 ? '+' : ''}{data.net_sentiment}</strong><span>net sentiment</span></div><div className="intelligence-legend">{sentimentData.map((entry) => <div key={entry.name}><span style={{ background: SENTIMENT_COLORS[entry.name] }} /><label>{entry.name}</label><strong>{percent(entry.value, total)}%</strong></div>)}</div></div></article>
          <article className="glass-card intelligence-card intelligence-line-card"><h3>Article volume &amp; sentiment over time</h3><ResponsiveContainer width="100%" height={260}><LineChart data={data.sentiment_over_time || []}><CartesianGrid strokeDasharray="3 3" stroke="rgba(15,23,42,.09)" /><XAxis dataKey="date" tickFormatter={formatDate} minTickGap={24} /><YAxis allowDecimals={false} /><Tooltip labelFormatter={formatDate} /><Legend /><Line type="monotone" dataKey="total" name="Total" stroke="#2563eb" strokeWidth={2.5} dot={false} /><Line type="monotone" dataKey="positive" name="Positive" stroke={SENTIMENT_COLORS.positive} strokeWidth={2} dot={false} /><Line type="monotone" dataKey="negative" name="Negative" stroke={SENTIMENT_COLORS.negative} strokeWidth={2} dot={false} /><Line type="monotone" dataKey="neutral" name="Neutral" stroke={SENTIMENT_COLORS.neutral} strokeWidth={2} dot={false} /></LineChart></ResponsiveContainer></article>
          <article className="glass-card intelligence-card intelligence-radar-card"><h3>Emotional signature</h3><ResponsiveContainer width="100%" height={285}><RadarChart data={data.emotional_signature || []}><PolarGrid /><PolarAngleAxis dataKey="axis" tickFormatter={(value) => value.charAt(0).toUpperCase() + value.slice(1)} /><PolarRadiusAxis angle={30} domain={[0, 100]} tick={false} /><Radar dataKey="value" stroke="#2563eb" fill="#2563eb" fillOpacity={0.22} /></RadarChart></ResponsiveContainer><p>Derived from the emotional tone of analyzed articles.</p></article>
        </section>

        <section className="intelligence-language-grid">
          <article className="glass-card intelligence-card intelligence-language-card">
            <h3>Language distribution</h3>
            {languageData.length ? (
              <div className="intelligence-language-layout">
                <div className="intelligence-donut">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={languageData} dataKey="count" nameKey="language" outerRadius="92%" paddingAngle={3} stroke="none">
                        {languageData.map((entry, index) => <Cell key={entry.language} fill={LANGUAGE_COLORS[index % LANGUAGE_COLORS.length]} />)}
                      </Pie>
                      <Tooltip formatter={(value, name) => [`${value} articles`, languageLabel(name)]} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div className="intelligence-legend">
                  {languageData.map((entry, index) => (
                    <div key={entry.language}>
                      <span style={{ background: LANGUAGE_COLORS[index % LANGUAGE_COLORS.length] }} />
                      <label>{languageLabel(entry.language)}</label>
                      <strong>{percent(entry.count, total)}%</strong>
                    </div>
                  ))}
                </div>
              </div>
            ) : <p className="intelligence-empty">No detected language on analyzed articles yet.</p>}
          </article>

          <article className="glass-card intelligence-card intelligence-language-card">
            <h3>Region distribution</h3>
            {regionData.length ? (
              <div className="intelligence-language-layout">
                <div className="intelligence-donut">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={regionData} dataKey="total" nameKey="value" outerRadius="92%" paddingAngle={3} stroke="none">
                        {regionData.map((entry, index) => <Cell key={entry.value} fill={LANGUAGE_COLORS[index % LANGUAGE_COLORS.length]} />)}
                      </Pie>
                      <Tooltip formatter={(value, name) => [`${value} articles`, distributionLabel(name)]} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div className="intelligence-legend">
                  {regionData.map((entry, index) => (
                    <div key={entry.value}>
                      <span style={{ background: LANGUAGE_COLORS[index % LANGUAGE_COLORS.length] }} />
                      <label>{distributionLabel(entry.value)}</label>
                      <strong>{percent(entry.total, total)}%</strong>
                    </div>
                  ))}
                </div>
              </div>
            ) : <p className="intelligence-empty">No region detected on analyzed articles yet.</p>}
          </article>

          <article className="glass-card intelligence-card intelligence-language-card">
            <h3>Gender distribution</h3>
            {genderData.length ? (
              <div className="intelligence-language-layout">
                <div className="intelligence-donut">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={genderData} dataKey="total" nameKey="value" outerRadius="92%" paddingAngle={3} stroke="none">
                        {genderData.map((entry, index) => <Cell key={entry.value} fill={LANGUAGE_COLORS[index % LANGUAGE_COLORS.length]} />)}
                      </Pie>
                      <Tooltip formatter={(value, name) => [`${value} articles`, distributionLabel(name)]} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div className="intelligence-legend">
                  {genderData.map((entry, index) => (
                    <div key={entry.value}>
                      <span style={{ background: LANGUAGE_COLORS[index % LANGUAGE_COLORS.length] }} />
                      <label>{distributionLabel(entry.value)}</label>
                      <strong>{percent(entry.total, total)}%</strong>
                    </div>
                  ))}
                </div>
              </div>
            ) : <p className="intelligence-empty">No gender detected on analyzed articles yet.</p>}
          </article>

          <article className="glass-card intelligence-card intelligence-language-card">
            <h3>Age range distribution</h3>
            {ageRangeData.length ? (
              <div className="intelligence-language-layout">
                <div className="intelligence-donut">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={ageRangeData} dataKey="total" nameKey="value" outerRadius="92%" paddingAngle={3} stroke="none">
                        {ageRangeData.map((entry, index) => <Cell key={entry.value} fill={LANGUAGE_COLORS[index % LANGUAGE_COLORS.length]} />)}
                      </Pie>
                      <Tooltip formatter={(value, name) => [`${value} articles`, distributionLabel(name)]} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div className="intelligence-legend">
                  {ageRangeData.map((entry, index) => (
                    <div key={entry.value}>
                      <span style={{ background: LANGUAGE_COLORS[index % LANGUAGE_COLORS.length] }} />
                      <label>{distributionLabel(entry.value)}</label>
                      <strong>{percent(entry.total, total)}%</strong>
                    </div>
                  ))}
                </div>
              </div>
            ) : <p className="intelligence-empty">No age range detected on analyzed articles yet.</p>}
          </article>

          <article className="glass-card intelligence-card intelligence-language-card">
            <h3>Segment distribution</h3>
            {segmentData.length ? (
              <div className="intelligence-language-layout">
                <div className="intelligence-donut">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={segmentData} dataKey="total" nameKey="value" outerRadius="92%" paddingAngle={3} stroke="none">
                        {segmentData.map((entry, index) => <Cell key={entry.value} fill={LANGUAGE_COLORS[index % LANGUAGE_COLORS.length]} />)}
                      </Pie>
                      <Tooltip formatter={(value, name) => [`${value} articles`, distributionLabel(name)]} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div className="intelligence-legend">
                  {segmentData.map((entry, index) => (
                    <div key={entry.value}>
                      <span style={{ background: LANGUAGE_COLORS[index % LANGUAGE_COLORS.length] }} />
                      <label>{distributionLabel(entry.value)}</label>
                      <strong>{percent(entry.total, total)}%</strong>
                    </div>
                  ))}
                </div>
              </div>
            ) : <p className="intelligence-empty">No life-situation/occupation segment detected on analyzed articles yet.</p>}
          </article>

          <article className="glass-card intelligence-card intelligence-language-card">
            <h3>Source verification</h3>
            {verifiedData.length ? (
              <div className="intelligence-language-layout">
                <div className="intelligence-donut">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={verifiedData} dataKey="total" nameKey="value" outerRadius="92%" paddingAngle={3} stroke="none">
                        {verifiedData.map((entry) => <Cell key={entry.value} fill={VERIFIED_COLORS[entry.value]} />)}
                      </Pie>
                      <Tooltip formatter={(value, name) => [`${value} articles`, distributionLabel(name)]} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div className="intelligence-legend">
                  {verifiedData.map((entry) => (
                    <div key={entry.value}>
                      <span style={{ background: VERIFIED_COLORS[entry.value] }} />
                      <label>{distributionLabel(entry.value)}</label>
                      <strong>{percent(entry.total, total)}%</strong>
                    </div>
                  ))}
                </div>
              </div>
            ) : <p className="intelligence-empty">No analyzed articles yet.</p>}
          </article>
        </section>

        <section className="intelligence-middle-grid">
          <article className="glass-card intelligence-card"><h3>Where it’s being said</h3><div className="intelligence-platform-list">{platformData.map((item) => <div key={item.platform}><div><strong>{item.platform}</strong></div><div className="intelligence-track"><span style={{ width: `${percent(item.total, total)}%` }} /></div><div className="intelligence-platform-count"><strong>{item.total.toLocaleString()}</strong><small>{item.total === 1 ? 'article' : 'articles'}</small></div></div>)}</div></article>
          <article className="glass-card intelligence-card intelligence-ideas-card"><div className="intelligence-card-heading"><h3>Most talked-about ideas</h3><span>Grouped by theme</span></div>{(data.insights?.frequent_ideas || []).slice(0, 6).map((idea) => <IdeaRow key={idea.idea} idea={idea} maxFrequency={Math.max(1, data.insights?.frequent_ideas?.[0]?.frequency_estimate || 1)} projectId={selectedProjectId} />)}{!(data.insights?.frequent_ideas || []).length && <p className="intelligence-empty">No repeated ideas detected yet.</p>}</article>
          <article className="glass-card intelligence-card"><h3>Sentiment by platform</h3><div className="intelligence-platform-sentiment">{platformData.map((item) => <div key={item.platform}><span>{item.platform}</span><div>{['positive', 'neutral', 'negative', 'mixed'].map((tone) => <i key={tone} title={`${tone}: ${item[tone] || 0}`} style={{ width: `${percent(item[tone], Math.max(1, item.total))}%`, background: SENTIMENT_COLORS[tone] }} />)}</div></div>)}</div></article>
        </section>

        <section className="intelligence-bottom-grid">
          <article className="glass-card intelligence-card"><h3>Trending keywords &amp; hashtags</h3><div className="intelligence-term-list">{(data.trending_terms || []).filter((term) => term.mentions > 0).map((term) => <Link key={`${term.kind}-${term.term}`} to={`/articles?search=${encodeURIComponent(term.term.replace(/^#/, ''))}${selectedProjectId != null ? `&project_id=${selectedProjectId}` : ''}`} className={`intelligence-term-link ${term.kind}`} title={`See articles mentioning ${term.term}`}><b>{term.term}</b> <em>{term.mentions}</em></Link>)}{!(data.trending_terms || []).some((term) => term.mentions > 0) && <p className="intelligence-empty">None of this project’s configured terms were mentioned in this period.</p>}</div></article>
          <article className="glass-card intelligence-card intelligence-pipeline-card"><div className="intelligence-card-heading"><h3>Articles analyzed by run</h3>{latestRun && <Change value={latestRun.change_pct} />}</div>{(data.pipeline_discovery || []).length ? <ResponsiveContainer width="100%" height={210}><LineChart data={data.pipeline_discovery}><CartesianGrid strokeDasharray="3 3" stroke="rgba(15,23,42,.09)" /><XAxis dataKey="completed_at" tickFormatter={(value, index) => pipelineRunShortLabel(data.pipeline_discovery[index], index)} minTickGap={18} /><YAxis allowDecimals={false} /><Tooltip labelFormatter={(value, payload) => { const item = payload?.[0]?.payload; return item ? `${pipelineRunShortLabel(item, 0)} · ${formatDate(item.completed_at)}` : value; }} formatter={(value) => [`${value} articles`, 'Discovered']} /><Line type="monotone" dataKey="articles_discovered" stroke="#2563eb" strokeWidth={3} dot={{ r: 4 }} /></LineChart></ResponsiveContainer> : <p className="intelligence-empty">Complete a successful analysis run to compare article volume.</p>}</article>
        </section>

        <section className="intelligence-run-sentiment-grid">
          <article className="glass-card intelligence-card intelligence-run-sentiment-card">
            <h3>Sentiment variation across analysis runs</h3>
            {(data.sentiment_by_pipeline_run || []).some((run) => run.total > 0) ? <ResponsiveContainer width="100%" height={240}><LineChart data={data.sentiment_by_pipeline_run}><CartesianGrid strokeDasharray="3 3" stroke="rgba(15,23,42,.09)" /><XAxis dataKey="completed_at" tickFormatter={(value, index) => pipelineRunShortLabel(data.sentiment_by_pipeline_run[index], index)} minTickGap={18} /><YAxis domain={[-100, 100]} tickFormatter={(value) => `${value > 0 ? '+' : ''}${value}`} /><Tooltip labelFormatter={(value, payload) => { const item = payload?.[0]?.payload; return item ? `${pipelineRunShortLabel(item, 0)} · ${formatDate(item.completed_at)}` : value; }} formatter={(value) => [`${value > 0 ? '+' : ''}${value}`, 'Net sentiment']} /><ReferenceLine y={0} stroke="rgba(15,23,42,.25)" /><Line type="monotone" dataKey="net_sentiment" name="Net sentiment" stroke={SENTIMENT_COLORS.positive} strokeWidth={2} dot={{ r: 4 }} /></LineChart></ResponsiveContainer> : <p className="intelligence-empty">Complete an analysis run with analyzed articles to compare sentiment across runs.</p>}
          </article>
        </section>
      </>}
    </>) : null}
  </div>;
}
