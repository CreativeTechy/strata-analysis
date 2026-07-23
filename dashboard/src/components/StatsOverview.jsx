import { Link } from 'react-router-dom';
import { AlertTriangle, ArrowUpRight, CircleMinus, Heart, ThumbsDown, ThumbsUp } from 'lucide-react';
import { CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import '../styles/IntelligenceDashboard.css';

const COLORS = { positive: '#16a34a', neutral: '#64748b', negative: '#e11d48', mixed: '#f59e0b' };

function percent(value, total) { return total ? Math.round((Number(value || 0) / total) * 100) : 0; }
function formatDate(value) { const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }); }

function Section({ number, title, children }) {
  return <section className="report-brief-section"><header><span>{number}</span><h3>{title}</h3></header>{children}</section>;
}

function FeedbackColumn({ title, icon, tone, items }) {
  return <article className={`report-feedback-column ${tone}`}><h4>{icon}{title}</h4>{items.length ? <ul>{items.slice(0, 5).map((item) => <li key={item.text || item.idea}>{item.text || item.idea}<strong>{item.count || item.frequency_estimate || 1}</strong></li>)}</ul> : <p>No signals in this category yet.</p>}</article>;
}

export default function StatsOverview({ intelligence = {}, scopeLabel, loading, error, onRetry }) {
  if (loading) return <section className="report-brief glass-card intelligence-loading">Loading the live intelligence brief…</section>;
  if (error) return <section className="report-brief"><div className="glass-card admin-empty-state report-error-state" role="alert"><div className="admin-empty-state-icon"><AlertTriangle size={20} /></div><strong>Couldn’t load this report</strong><p className="subtitle">{error}</p>{onRetry && <button className="btn-secondary" type="button" onClick={onRetry}>Try again</button>}</div></section>;

  const total = Number(intelligence.total || 0);
  if (!total) return <section className="report-brief"><div className="glass-card admin-empty-state"><strong>No analyzed articles yet</strong><p className="subtitle">Run the pipeline for {scopeLabel || 'this project'} or broaden the date range to generate a report.</p><Link to="/workflow" className="btn-secondary">Go to Workflow</Link></div></section>;

  const sentiments = ['positive', 'neutral', 'negative', 'mixed'].map((name) => ({ name, value: Number(intelligence[name] || 0) }));
  const insights = intelligence.insights || {};
  const leadingIdea = insights.frequent_ideas?.[0]?.idea;
  const leadingConcern = insights.negative_feedback?.[0]?.text || insights.complaints?.[0]?.text;
  const headline = leadingIdea
    ? `${scopeLabel} generated ${total.toLocaleString()} analyzed articles. The leading conversation theme is ${leadingIdea}${leadingConcern ? `, while ${leadingConcern} is the primary concern` : ''}.`
    : `${scopeLabel} generated ${total.toLocaleString()} analyzed articles with a net sentiment of ${intelligence.net_sentiment >= 0 ? '+' : ''}${intelligence.net_sentiment}.`;

  return <section className="report-brief">
    <Section number="01" title="Executive summary">
      <p className="report-brief-summary">{headline}</p>
      <div className="report-brief-metrics">
        <div><strong>{total.toLocaleString()}</strong><span>Analyzed articles</span></div>
        <div><strong className={intelligence.net_sentiment >= 0 ? 'positive-text' : 'negative-text'}>{intelligence.net_sentiment >= 0 ? '+' : ''}{intelligence.net_sentiment}</strong><span>Net sentiment</span></div>
        <div><strong>{Number(intelligence.active_sources || 0).toLocaleString()}</strong><span>Active sources</span></div>
      </div>
    </Section>

    <Section number="02" title="Sentiment analysis">
      <div className="report-sentiment-grid"><div className="report-donut"><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={sentiments} dataKey="value" innerRadius="58%" outerRadius="82%" paddingAngle={3} stroke="none">{sentiments.map((entry) => <Cell key={entry.name} fill={COLORS[entry.name]} />)}</Pie><Tooltip formatter={(value, name) => [`${value} articles`, name]} /></PieChart></ResponsiveContainer></div><div className="report-sentiment-bars">{sentiments.map((entry) => <div key={entry.name}><span><i style={{ background: COLORS[entry.name] }} />{entry.name}</span><div><b style={{ width: `${percent(entry.value, total)}%`, background: COLORS[entry.name] }} /></div><strong>{percent(entry.value, total)}%</strong></div>)}<p>Sentiment is calculated from the analyzed article content already stored for this project.</p></div></div>
    </Section>

    <Section number="03" title="Volume trend">
      <ResponsiveContainer width="100%" height={285}><LineChart data={intelligence.sentiment_over_time || []}><CartesianGrid strokeDasharray="3 3" stroke="rgba(15,23,42,.09)" /><XAxis dataKey="date" tickFormatter={formatDate} minTickGap={24} /><YAxis allowDecimals={false} /><Tooltip labelFormatter={formatDate} /><Legend /><Line dataKey="total" name="Total" type="monotone" stroke="#2563eb" strokeWidth={2.5} dot={false} /><Line dataKey="positive" name="Positive" type="monotone" stroke={COLORS.positive} strokeWidth={2} dot={false} /><Line dataKey="negative" name="Negative" type="monotone" stroke={COLORS.negative} strokeWidth={2} dot={false} /></LineChart></ResponsiveContainer>
    </Section>

    <Section number="04" title="Categorized feedback">
      <div className="report-feedback-grid"><FeedbackColumn title="Positive drivers" icon={<ThumbsUp size={16} />} tone="positive" items={insights.positive_feedback || []} /><FeedbackColumn title="Negative drivers" icon={<ThumbsDown size={16} />} tone="negative" items={insights.negative_feedback || []} /><FeedbackColumn title="Neutral / mixed" icon={<CircleMinus size={16} />} tone="neutral" items={(insights.frequent_ideas || []).filter((item) => !['praise', 'complaint'].includes(item.type))} /></div>
    </Section>

    <Section number="05" title="Most talked-about ideas">
      <div className="report-idea-list">{(insights.frequent_ideas || []).slice(0, 8).map((idea) => <article key={idea.idea} className={idea.type || 'issue'}><span>{idea.type === 'praise' ? <Heart size={16} /> : <ArrowUpRight size={16} />}</span><div><strong>{idea.idea}</strong><small>{idea.category || idea.type || 'Theme'}</small></div><b>{idea.frequency_estimate || 1}</b></article>)}{!(insights.frequent_ideas || []).length && <p className="intelligence-empty">No repeated ideas have been detected yet.</p>}</div>
    </Section>
  </section>;
}
