import { useMemo } from 'react';
import {
  Activity, CalendarClock, FolderKanban, Gauge, Network, Rss, Sparkles, TrendingDown, TrendingUp,
} from 'lucide-react';
import {
  CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, Radar, RadarChart,
  PolarAngleAxis, PolarGrid, PolarRadiusAxis, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import '../styles/IntelligenceDashboard.css';
import CompetitorPulseCard from './CompetitorPulseCard.jsx';
import CompetitorStudySummary from './CompetitorStudySummary.jsx';

const PERIODS = [
  { key: '7d', label: 'Last 7 days' },
  { key: '30d', label: 'Last 30 days' },
  { key: 'all', label: 'All time' },
];
const SENTIMENT_COLORS = { positive: '#16a34a', neutral: '#64748b', negative: '#e11d48', mixed: '#f59e0b' };

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

export default function DashboardOverview({
  projects, selectedProjectId, onProjectChange, period, onPeriodChange, intelligence,
  loading, error, totalProjects, pipelineHealth, nextScheduledRun,
}) {
  const data = intelligence || {};
  const total = Number(data.total || 0);
  const sentimentData = ['positive', 'neutral', 'negative', 'mixed'].map((name) => ({ name, value: Number(data[name] || 0) }));
  const latestRun = data.pipeline_discovery?.[data.pipeline_discovery.length - 1];
  const platformData = data.platforms || [];
  const selectedProject = useMemo(() => projects.find((project) => Number(project.id) === Number(selectedProjectId)), [projects, selectedProjectId]);

  return <div className="content-shell intelligence-page">
    <header className="intelligence-header">
      <div><span className="intelligence-eyebrow"><Sparkles size={14} /> Intelligence dashboard</span><h2>Project intelligence</h2><p className="subtitle">Signals from the articles and sources already monitored for this project.</p></div>
      <div className="intelligence-controls">
        <select className="filter-select" value={selectedProjectId ?? ''} onChange={(event) => onProjectChange(Number(event.target.value))} disabled={!projects.length} aria-label="Dashboard project">
          {projects.map((project) => <option value={project.id} key={project.id}>{project.name}</option>)}
        </select>
        <div className="source-type-tabs" role="tablist" aria-label="Dashboard date range">
          {PERIODS.map((item) => <button key={item.key} type="button" role="tab" aria-selected={period === item.key} className={`source-type-tab ${period === item.key ? 'active' : ''}`} onClick={() => onPeriodChange(item.key)}>{item.label}</button>)}
        </div>
      </div>
    </header>

    <CompetitorPulseCard />

    {!selectedProject ? <div className="glass-card admin-empty-state"><strong>No project selected</strong><p className="subtitle">Create a project to begin tracking intelligence.</p></div> : null}
    {error ? <div className="glass-card admin-empty-state"><strong>Couldn’t load project intelligence</strong><p className="subtitle">{error}</p></div> : null}

    {selectedProject && !error ? (selectedProject.mode === 'competitor' ? <CompetitorStudySummary studyId={selectedProject.id} /> : <>
      <section className="intelligence-metric-grid" aria-busy={loading}>
        <MetricCard icon={<FolderKanban size={18} />} label="Total projects" value={Number(totalProjects || 0).toLocaleString()} detail="Across your workspace" />
        <MetricCard icon={<Activity size={18} />} label="Pipeline health" value={pipelineHealth?.lastRun?.status || 'No runs'} detail={pipelineHealth?.lastFinished ? `Last completed ${formatDate(pipelineHealth.lastFinished.finished_at)}` : 'No completed runs yet'} tone="blue" />
        <MetricCard icon={<CalendarClock size={18} />} label="Next run" value={nextScheduledRun ? formatDate(nextScheduledRun.nextRunAt) : 'Not scheduled'} detail={nextScheduledRun ? 'Selected project' : 'Enable a repeat schedule'} tone="orange" />
        <MetricCard icon={<Network size={18} />} label="Analyzed articles" value={loading ? '—' : total.toLocaleString()} detail={PERIODS.find((item) => item.key === period)?.label} tone="blue" />
        <MetricCard icon={<Gauge size={18} />} label="Net sentiment" value={loading ? '—' : `${Number(data.net_sentiment || 0) >= 0 ? '+' : ''}${data.net_sentiment || 0}`} detail="Positive minus negative" tone={Number(data.net_sentiment || 0) >= 0 ? 'positive' : 'negative'} />
        <MetricCard icon={<Rss size={18} />} label="Active sources" value={loading ? '—' : Number(data.active_sources || 0).toLocaleString()} detail="Assigned to this project" tone="blue" />
      </section>

      {loading ? <div className="glass-card intelligence-loading">Loading intelligence…</div> : total === 0 ? <div className="glass-card admin-empty-state"><strong>No analyzed articles in this period</strong><p className="subtitle">Run the pipeline or choose a broader time range to populate this dashboard.</p></div> : <>
        <section className="intelligence-top-grid">
          <article className="glass-card intelligence-card intelligence-sentiment-card"><h3>Sentiment breakdown</h3><div className="intelligence-sentiment-layout"><div className="intelligence-donut"><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={sentimentData} dataKey="value" innerRadius="63%" outerRadius="84%" paddingAngle={3} stroke="none">{sentimentData.map((entry) => <Cell key={entry.name} fill={SENTIMENT_COLORS[entry.name]} />)}</Pie><Tooltip formatter={(value, name) => [`${value} articles`, name]} /></PieChart></ResponsiveContainer><strong>{data.net_sentiment >= 0 ? '+' : ''}{data.net_sentiment}</strong><span>net sentiment</span></div><div className="intelligence-legend">{sentimentData.map((entry) => <div key={entry.name}><span style={{ background: SENTIMENT_COLORS[entry.name] }} /><label>{entry.name}</label><strong>{percent(entry.value, total)}%</strong></div>)}</div></div></article>
          <article className="glass-card intelligence-card intelligence-line-card"><h3>Article volume &amp; sentiment over time</h3><ResponsiveContainer width="100%" height={260}><LineChart data={data.sentiment_over_time || []}><CartesianGrid strokeDasharray="3 3" stroke="rgba(15,23,42,.09)" /><XAxis dataKey="date" tickFormatter={formatDate} minTickGap={24} /><YAxis allowDecimals={false} /><Tooltip labelFormatter={formatDate} /><Legend /><Line type="monotone" dataKey="total" name="Total" stroke="#2563eb" strokeWidth={2.5} dot={false} /><Line type="monotone" dataKey="positive" name="Positive" stroke={SENTIMENT_COLORS.positive} strokeWidth={2} dot={false} /><Line type="monotone" dataKey="negative" name="Negative" stroke={SENTIMENT_COLORS.negative} strokeWidth={2} dot={false} /></LineChart></ResponsiveContainer></article>
          <article className="glass-card intelligence-card intelligence-radar-card"><h3>Emotional signature</h3><ResponsiveContainer width="100%" height={285}><RadarChart data={data.emotional_signature || []}><PolarGrid /><PolarAngleAxis dataKey="axis" tickFormatter={(value) => value.charAt(0).toUpperCase() + value.slice(1)} /><PolarRadiusAxis angle={30} domain={[0, 100]} tick={false} /><Radar dataKey="value" stroke="#2563eb" fill="#2563eb" fillOpacity={0.22} /></RadarChart></ResponsiveContainer><p>Derived from the emotional tone of analyzed articles.</p></article>
        </section>

        <section className="intelligence-middle-grid">
          <article className="glass-card intelligence-card"><h3>Where it’s being said</h3><div className="intelligence-platform-list">{platformData.map((item) => <div key={item.platform}><div><strong>{item.platform}</strong><small>{item.total.toLocaleString()} articles</small></div><div className="intelligence-track"><span style={{ width: `${percent(item.total, total)}%` }} /></div><strong className={item.net_sentiment >= 0 ? 'positive-text' : 'negative-text'}>{item.net_sentiment >= 0 ? '+' : ''}{item.net_sentiment}</strong></div>)}</div></article>
          <article className="glass-card intelligence-card intelligence-ideas-card"><div className="intelligence-card-heading"><h3>Most talked-about ideas</h3><span>Grouped by theme</span></div>{(data.insights?.frequent_ideas || []).slice(0, 6).map((idea) => <div className={`intelligence-idea ${idea.type || 'issue'}`} key={idea.idea}><div><strong>{idea.idea}</strong><span>{idea.type || 'issue'}</span></div><strong>{Number(idea.frequency_estimate || 0).toLocaleString()}</strong><div className="intelligence-track"><span style={{ width: `${Math.max(8, percent(idea.frequency_estimate, Math.max(1, data.insights?.frequent_ideas?.[0]?.frequency_estimate || 1)))}%` }} /></div></div>)}{!(data.insights?.frequent_ideas || []).length && <p className="intelligence-empty">No repeated ideas detected yet.</p>}</article>
          <article className="glass-card intelligence-card"><h3>Sentiment by platform</h3><div className="intelligence-platform-sentiment">{platformData.map((item) => <div key={item.platform}><span>{item.platform}</span><div>{['positive', 'neutral', 'negative', 'mixed'].map((tone) => <i key={tone} title={`${tone}: ${item[tone] || 0}`} style={{ width: `${percent(item[tone], Math.max(1, item.total))}%`, background: SENTIMENT_COLORS[tone] }} />)}</div></div>)}</div></article>
        </section>

        <section className="intelligence-bottom-grid">
          <article className="glass-card intelligence-card"><h3>Trending keywords &amp; hashtags</h3><div className="intelligence-term-list">{(data.trending_terms || []).filter((term) => term.mentions > 0).map((term) => <span key={`${term.kind}-${term.term}`} className={term.kind}><b>{term.term}</b> <em>{term.mentions}</em></span>)}{!(data.trending_terms || []).some((term) => term.mentions > 0) && <p className="intelligence-empty">None of this project’s configured terms were mentioned in this period.</p>}</div></article>
          <article className="glass-card intelligence-card intelligence-pipeline-card"><div className="intelligence-card-heading"><h3>Article discovery by pipeline run</h3>{latestRun && <Change value={latestRun.change_pct} />}</div>{(data.pipeline_discovery || []).length ? <ResponsiveContainer width="100%" height={210}><LineChart data={data.pipeline_discovery}><CartesianGrid strokeDasharray="3 3" stroke="rgba(15,23,42,.09)" /><XAxis dataKey="completed_at" tickFormatter={formatDate} minTickGap={18} /><YAxis allowDecimals={false} /><Tooltip labelFormatter={formatDate} formatter={(value) => [`${value} articles`, 'Discovered']} /><Line type="monotone" dataKey="articles_discovered" stroke="#2563eb" strokeWidth={3} dot={{ r: 4 }} /></LineChart></ResponsiveContainer> : <p className="intelligence-empty">Complete a successful pipeline run to compare article discovery.</p>}</article>
        </section>
      </>}
    </>) : null}
  </div>;
}
