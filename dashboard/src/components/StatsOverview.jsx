import { useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Activity, Sparkles, MessageCircle, ThumbsUp, ThumbsDown, ListOrdered, Layers3, Smile, Mic, Percent, Inbox, TrendingUp, TrendingDown, Minus, AlertTriangle, RefreshCw, ExternalLink } from 'lucide-react';
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid } from 'recharts';
import { motion } from 'framer-motion';
import '../styles/Stats.css';

// Key metrics / Sentiment mix / Article categories are hidden for now so
// Audience Insights can be the primary focus of the reports page. The
// sections are left in place (not deleted) so they're a one-line flip away
// from coming back.
const SHOW_KPI_SENTIMENT_CATEGORY_SECTIONS = false;

const COLORS = ['#16a34a', '#e11d48', '#64748b', '#f59e0b'];

const prettyLabel = (value) => String(value || '')
  .replace(/_/g, ' ')
  .replace(/\b\w/g, (char) => char.toUpperCase());

function computeDelta(current, previous) {
  if (previous == null) return null;
  if (previous === 0) {
    return current === 0 ? { pct: 0, direction: 'flat' } : { pct: 100, direction: 'up' };
  }
  const pct = Math.round(((current - previous) / previous) * 100);
  if (pct === 0) return { pct: 0, direction: 'flat' };
  return { pct: Math.abs(pct), direction: pct > 0 ? 'up' : 'down' };
}

function DeltaBadge({ delta, comparePeriodLabel }) {
  if (!delta) return null;
  const Icon = delta.direction === 'up' ? TrendingUp : delta.direction === 'down' ? TrendingDown : Minus;
  return (
    <span className={`report-delta report-delta-${delta.direction}`}>
      <Icon size={12} aria-hidden="true" />
      {delta.direction === 'flat' ? 'No change' : `${delta.pct}%`} vs previous {comparePeriodLabel || 'period'}
    </span>
  );
}

function SectionHeader({ icon, title, caption }) {
  return (
    <div className="report-section-header">
      <div className="report-section-heading">
        <span className="report-section-icon">{icon}</span>
        <h3 className="report-section-title">{title}</h3>
      </div>
      {caption ? <p className="report-section-caption">{caption}</p> : null}
    </div>
  );
}

function StatSkeleton() {
  return (
    <div className="glass-card stat-card stat-card-skeleton" aria-hidden="true">
      <div className="stat-icon skeleton-shimmer" />
      <div className="stat-info">
        <div className="skeleton-line skeleton-shimmer stat-skeleton-title" />
        <div className="skeleton-line skeleton-shimmer stat-skeleton-value" />
        <div className="skeleton-line skeleton-shimmer stat-skeleton-subtitle" />
      </div>
    </div>
  );
}

function SectionSkeleton({ lines = 3 }) {
  return (
    <div className="glass-card report-section" aria-hidden="true">
      <div className="skeleton-line skeleton-shimmer stat-skeleton-title" style={{ width: '32%' }} />
      <div className="skeleton-line skeleton-shimmer stat-skeleton-subtitle" style={{ width: '58%', marginTop: 10 }} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 18 }}>
        {Array.from({ length: lines }).map((_, index) => (
          <div
            key={index}
            className="skeleton-line skeleton-shimmer"
            style={{ width: `${88 - index * 12}%`, height: 16, borderRadius: 999 }}
          />
        ))}
      </div>
    </div>
  );
}

export default function StatsOverview({
  stats = {},
  compareStats = null,
  comparePeriodLabel = null,
  scopeLabel = 'Current project',
  loading = false,
  error = null,
  onRetry = null,
}) {
  const [activeInsightTab, setActiveInsightTab] = useState('positive');
  const insightTabRefs = useRef([]);

  const total = Number(stats.total) || 0;
  const positive = Number(stats.positive) || 0;
  const negative = Number(stats.negative) || 0;
  const neutral = Number(stats.neutral) || 0;
  const mixed = Number(stats.mixed) || 0;
  const insights = stats.insights || {};
  const categoryBreakdown = Array.isArray(insights.article_category_breakdown) ? insights.article_category_breakdown : [];
  const positiveFeedback = Array.isArray(insights.positive_feedback) ? insights.positive_feedback : [];
  const negativeFeedback = Array.isArray(insights.negative_feedback) ? insights.negative_feedback : [];
  const requests = Array.isArray(insights.nice_to_have_features) ? insights.nice_to_have_features : [];
  const frequentIdeas = Array.isArray(insights.frequent_ideas) ? insights.frequent_ideas : [];
  const writerToneBreakdown = Array.isArray(insights.writer_tone_breakdown) ? insights.writer_tone_breakdown : [];
  const articleToneBreakdown = Array.isArray(insights.article_tone_breakdown) ? insights.article_tone_breakdown : [];
  const summary = insights.summary || '';
  const dominantInsight = prettyLabel(insights.article_category || 'general_article');
  const overallMood = prettyLabel(insights.overall_mood || 'neutral');
  const overallTone = prettyLabel(insights.overall_tone || 'neutral');
  const positivePct = total ? Math.round((positive / total) * 100) : 0;
  const negativePct = total ? Math.round((negative / total) * 100) : 0;
  const neutralPct = total ? Math.round((neutral / total) * 100) : 0;
  const mixedPct = total ? Math.round((mixed / total) * 100) : 0;
  const dominant = total ? [
    { label: 'Positive', value: positive, pct: positivePct, color: '#16a34a' },
    { label: 'Negative', value: negative, pct: negativePct, color: '#e11d48' },
    { label: 'Neutral', value: neutral, pct: neutralPct, color: '#64748b' },
    { label: 'Mixed', value: mixed, pct: mixedPct, color: '#f59e0b' },
  ].sort((a, b) => b.value - a.value)[0] : { label: 'Positive', pct: 0 };

  const totalDelta = compareStats ? computeDelta(total, Number(compareStats.total) || 0) : null;

  const data = [
    { name: 'Positive', value: positive },
    { name: 'Negative', value: negative },
    { name: 'Neutral', value: neutral },
    { name: 'Mixed', value: mixed },
  ];

  const categoryData = categoryBreakdown.map((item) => ({
    category: prettyLabel(item.category || 'general_article'),
    count: Number(item.count) || 0,
  }));

  const maxInsightCount = Math.max(
    1,
    ...positiveFeedback.map((item) => Number(item.count) || 0),
    ...negativeFeedback.map((item) => Number(item.count) || 0),
    ...requests.map((item) => Number(item.count) || 0),
    ...frequentIdeas.map((item) => Number(item.frequency_estimate) || 0),
    ...writerToneBreakdown.map((item) => Number(item.count) || 0),
    ...articleToneBreakdown.map((item) => Number(item.count) || 0)
  );

  const insightTabs = [
    {
      key: 'positive',
      label: 'Praised features',
      icon: <ThumbsUp size={16} />,
      color: '#16a34a',
      tone: 'positive',
      items: positiveFeedback,
      emptyText: 'No praised features have been detected for this scope yet.',
    },
    {
      key: 'negative',
      label: 'Complaints',
      icon: <ThumbsDown size={16} />,
      color: '#e11d48',
      tone: 'negative',
      items: negativeFeedback,
      emptyText: 'No complaints have been detected for this scope yet.',
    },
    {
      key: 'requests',
      label: 'Requested improvements',
      icon: <MessageCircle size={16} />,
      color: '#f59e0b',
      tone: 'requested',
      items: requests,
      emptyText: 'No requested improvements have been detected for this scope yet.',
    },
    {
      key: 'ideas',
      label: 'Repeated ideas',
      icon: <ListOrdered size={16} />,
      color: '#64748b',
      tone: 'neutral',
      items: frequentIdeas,
      emptyText: 'No repeated ideas have been detected for this scope yet.',
    },
    {
      key: 'writerTone',
      label: 'Writer tone',
      icon: <Mic size={16} />,
      color: '#2e86de',
      tone: 'neutral',
      items: writerToneBreakdown,
      emptyText: 'Not enough data to break down writer tone yet.',
    },
    {
      key: 'articleTone',
      label: 'Article tone',
      icon: <Smile size={16} />,
      color: '#f97316',
      tone: 'neutral',
      items: articleToneBreakdown,
      emptyText: 'Not enough data to break down article tone yet.',
    },
  ];
  const activeTab = insightTabs.find((tab) => tab.key === activeInsightTab) || insightTabs[0];

  const focusInsightTab = (index) => {
    const nextTab = insightTabs[index];
    if (!nextTab) return;
    setActiveInsightTab(nextTab.key);
    insightTabRefs.current[index]?.focus();
  };

  const handleInsightTabKeyDown = (event, index) => {
    switch (event.key) {
      case 'ArrowRight':
        event.preventDefault();
        focusInsightTab((index + 1) % insightTabs.length);
        break;
      case 'ArrowLeft':
        event.preventDefault();
        focusInsightTab((index - 1 + insightTabs.length) % insightTabs.length);
        break;
      case 'Home':
        event.preventDefault();
        focusInsightTab(0);
        break;
      case 'End':
        event.preventDefault();
        focusInsightTab(insightTabs.length - 1);
        break;
      default:
        break;
    }
  };

  const renderInsightList = (tab) => {
    if (!tab.items.length) {
      return <div className="mini-empty">{tab.emptyText}</div>;
    }
    return (
      <div className="report-insight-list">
        {tab.items.slice(0, 6).map((item) => {
          const text = item.text || item.idea || item.opinion || (item.tone ? prettyLabel(item.tone) : 'Unknown');
          const count = Number(item.count || item.frequency_estimate) || 1;
          const pct = Math.max(12, Math.round((count / maxInsightCount) * 100));
          const category = item.category ? prettyLabel(item.category) : '';
          const ideaType = item.type ? prettyLabel(item.type) : '';
          const sources = Array.isArray(item.sources) ? item.sources.filter((source) => source?.url) : [];

          return (
            <article key={`${tab.key}-${text}`} className={`report-insight-card tone-${tab.tone}`}>
              <div className="report-insight-card-top">
                <div className="report-insight-card-copy">
                  <p className="report-insight-card-text">{text}</p>
                  <div className="report-insight-card-tags">
                    <span className="report-insight-card-tag" style={{ background: `${tab.color}14`, color: tab.color }}>
                      {tab.icon} {tab.label}
                    </span>
                    {ideaType ? <span className="report-insight-card-tag muted">{ideaType}</span> : null}
                    {category ? <span className="report-insight-card-tag muted">{category}</span> : null}
                  </div>
                </div>
                <div className="report-insight-card-count" title="Mentions across analyzed articles in this scope">
                  <strong style={{ color: tab.color }}>{count}</strong>
                  <span>{count === 1 ? 'mention' : 'mentions'}</span>
                </div>
              </div>

              <div className="report-insight-track">
                <div className="report-insight-fill" style={{ width: `${pct}%`, background: tab.color }} />
              </div>

              <div className="report-insight-card-footer">
                <span className="report-insight-card-source-count">
                  {sources.length ? `${sources.length} source${sources.length === 1 ? '' : 's'}` : 'No linked source'}
                </span>
                {sources.length ? (
                  <div className="report-insight-card-links">
                    {sources.slice(0, 3).map((source) => (
                      <a
                        key={`${text}-${source.url}`}
                        href={source.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="report-insight-card-cta"
                        title={source.title || source.url}
                      >
                        <ExternalLink size={13} aria-hidden="true" />
                        {sources.length === 1 ? 'View related article' : (source.title || 'Open article')}
                      </a>
                    ))}
                  </div>
                ) : null}
              </div>
            </article>
          );
        })}
      </div>
    );
  };

  if (loading) {
    return (
      <section className="report-body stats-overview" aria-busy="true">
        <SectionSkeleton lines={6} />
        {SHOW_KPI_SENTIMENT_CATEGORY_SECTIONS ? (
          <>
            <div className="stats-grid" style={{ marginBottom: 0 }}>
              <StatSkeleton />
              <StatSkeleton />
              <StatSkeleton />
            </div>
            <div className="report-section-row">
              <SectionSkeleton lines={4} />
              <SectionSkeleton lines={4} />
            </div>
          </>
        ) : null}
      </section>
    );
  }

  if (error) {
    return (
      <section className="report-body stats-overview">
        <div className="glass-card admin-empty-state report-error-state" role="alert">
          <div className="admin-empty-state-icon">
            <AlertTriangle size={20} />
          </div>
          <strong>Couldn't load this report</strong>
          <p className="subtitle">{error} Check your connection and try again.</p>
          {onRetry ? (
            <button type="button" className="btn-secondary" onClick={onRetry}>
              <RefreshCw size={14} /> Try again
            </button>
          ) : null}
        </div>
      </section>
    );
  }

  if (!total) {
    return (
      <section className="report-body stats-overview">
        <div className="glass-card admin-empty-state">
          <div className="admin-empty-state-icon">
            <Inbox size={20} />
          </div>
          <strong>No analyzed articles yet</strong>
          <p className="subtitle">
            {scopeLabel ? `Nothing has been analyzed for ${scopeLabel} yet.` : 'Nothing has been analyzed yet.'}{' '}
            Run the pipeline for this project, or pick a different project scope, to see report data here.
          </p>
          <Link to="/workflow" className="btn-secondary">
            Go to Workflow
          </Link>
        </div>
      </section>
    );
  }

  return (
    <section className="report-body stats-overview">
      <motion.section
        className="glass-card report-section report-insights-hero"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
      >
        <div className="report-insights-hero-header">
          <span className="report-kicker">
            <Sparkles size={13} /> Core Report
          </span>
          <h2 className="report-insights-hero-title">Audience Insights</h2>
          {summary ? (
            <p className="report-summary-text">{summary}</p>
          ) : (
            <p className="report-summary-text report-summary-text-empty">
              What people are saying about {scopeLabel}, grouped by theme - no AI summary sentence has been generated for this scope yet.
            </p>
          )}
          <div className="report-summary-facts">
            <span className="report-chip">
              <span className="report-chip-label">Category</span>
              <strong>{dominantInsight}</strong>
            </span>
            <span className="report-chip">
              <span className="report-chip-label">Mood</span>
              <strong>{overallMood}</strong>
            </span>
            <span className="report-chip">
              <span className="report-chip-label">Tone</span>
              <strong>{overallTone}</strong>
            </span>
          </div>
        </div>

        <div className="source-type-tabs report-insight-tabs" role="tablist" aria-label="Insight categories">
          {insightTabs.map((tab, index) => (
            <button
              key={tab.key}
              ref={(el) => { insightTabRefs.current[index] = el; }}
              type="button"
              role="tab"
              id={`insight-tab-${tab.key}`}
              aria-selected={activeTab.key === tab.key}
              aria-controls={`insight-panel-${tab.key}`}
              tabIndex={activeTab.key === tab.key ? 0 : -1}
              className={`source-type-tab ${activeTab.key === tab.key ? 'active' : ''}`}
              onClick={() => setActiveInsightTab(tab.key)}
              onKeyDown={(event) => handleInsightTabKeyDown(event, index)}
            >
              <span style={{ color: tab.color, display: 'inline-flex' }}>{tab.icon}</span>
              {tab.label}
              <span className="source-type-tab-count">{tab.items.length}</span>
            </button>
          ))}
        </div>

        <div
          className="report-insight-panel"
          role="tabpanel"
          id={`insight-panel-${activeTab.key}`}
          aria-labelledby={`insight-tab-${activeTab.key}`}
        >
          {renderInsightList(activeTab)}
        </div>
      </motion.section>

      {SHOW_KPI_SENTIMENT_CATEGORY_SECTIONS ? (
        <>
          <div className="glass-card report-section">
            <SectionHeader
              icon={<Activity size={16} />}
              title="Key metrics"
              caption={
                compareStats
                  ? `Snapshot for ${scopeLabel}, compared with the previous ${comparePeriodLabel || 'period'}.`
                  : `Snapshot for ${scopeLabel}.`
              }
            />
            <div className="stats-grid" style={{ marginBottom: 0 }}>
              <motion.article className="glass-card stat-card" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
                <div className="stat-icon">
                  <Activity size={24} />
                </div>
                <div className="stat-info">
                  <h4>Analyzed Articles</h4>
                  <p>{total.toLocaleString()}</p>
                  <span style={{ fontSize: '0.72rem', color: 'var(--text-light)' }}>{scopeLabel}</span>
                  <DeltaBadge delta={totalDelta} comparePeriodLabel={comparePeriodLabel} />
                </div>
              </motion.article>

              <motion.article className="glass-card stat-card" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}>
                <div className="stat-icon" style={{ background: 'linear-gradient(135deg, rgba(249, 115, 22, 0.1), rgba(245, 158, 11, 0.1))', color: '#f97316' }}>
                  <Smile size={24} />
                </div>
                <div className="stat-info">
                  <h4>Overall Mood</h4>
                  <p>{overallMood}</p>
                  <span style={{ fontSize: '0.72rem', color: 'var(--text-light)' }}>{scopeLabel}</span>
                </div>
              </motion.article>

              <motion.article className="glass-card stat-card" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }}>
                <div className="stat-icon" style={{ background: 'linear-gradient(135deg, rgba(46, 134, 222, 0.1), rgba(22, 163, 74, 0.1))', color: '#2e86de' }}>
                  <Mic size={24} />
                </div>
                <div className="stat-info">
                  <h4>Overall Tone</h4>
                  <p>{overallTone}</p>
                  <span style={{ fontSize: '0.72rem', color: 'var(--text-light)' }}>{scopeLabel}</span>
                </div>
              </motion.article>
            </div>
          </div>

          <div className="report-section-row">
            <motion.article className="glass-card report-section" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.4 }}>
              <SectionHeader
                icon={<Percent size={16} />}
                title="Sentiment mix"
                caption={`Share of positive, negative, neutral, and mixed sentiment across ${total.toLocaleString()} analyzed articles. ${dominant.label} leads at ${dominant.pct}%.`}
              />

              <div className="sentiment-visual-mix">
                <div className="sentiment-chart-shell">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={data}
                        innerRadius="42%"
                        outerRadius="60%"
                        paddingAngle={4}
                        dataKey="value"
                        stroke="none"
                      >
                        {data.map((_, index) => (
                          <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip
                        formatter={(value, name) => [`${Number(value).toLocaleString()} articles`, name]}
                        contentStyle={{
                          borderRadius: '10px',
                          border: 'none',
                          boxShadow: '0 4px 15px rgba(0,0,0,0.1)',
                        }}
                      />
                    </PieChart>
                  </ResponsiveContainer>

                  <div className="sentiment-center-copy">
                    <strong>{total.toLocaleString()}</strong>
                    <span>articles</span>
                  </div>
                </div>

                <aside className="sentiment-legend-panel">
                  <div className="mini-list-title" style={{ margin: 0 }}>
                    <Sparkles size={14} />
                    <span>Legend &amp; stats</span>
                  </div>

                  <div className="sentiment-legend-list">
                    {[
                      { label: 'Positive', pct: positivePct, value: positive, color: '#16a34a' },
                      { label: 'Negative', pct: negativePct, value: negative, color: '#e11d48' },
                      { label: 'Neutral', pct: neutralPct, value: neutral, color: '#64748b' },
                      { label: 'Mixed', pct: mixedPct, value: mixed, color: '#f59e0b' },
                    ].map((item) => (
                      <div key={item.label} className="sentiment-legend-row">
                        <div className="sentiment-legend-label">
                          <span className="sentiment-dot" style={{ background: item.color }} />
                          <div>
                            <strong>{item.label}</strong>
                            <span>{item.value.toLocaleString()} articles</span>
                          </div>
                        </div>
                        <strong>{item.pct}%</strong>
                        <div className="sentiment-legend-track">
                          <div className="sentiment-legend-fill" style={{ width: `${Math.max(item.pct, 8)}%`, background: item.color }} />
                        </div>
                      </div>
                    ))}
                  </div>
                </aside>
              </div>
            </motion.article>

            <motion.article className="glass-card report-section" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.45 }}>
              <SectionHeader
                icon={<Layers3 size={16} />}
                title="Article categories"
                caption="Volume of articles auto-tagged into each detected category, most common first."
              />

              {categoryData.length ? (
                <div className="sentiment-chart-bars">
                  <div className="sentiment-chart-bars-inner">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={categoryData} layout="vertical" margin={{ top: 4, right: 18, bottom: 4, left: 12 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(15,23,42,0.06)" horizontal={false} />
                        <XAxis type="number" allowDecimals={false} hide />
                        <YAxis type="category" dataKey="category" width={130} tick={{ fontSize: 12 }} />
                        <Tooltip
                          labelFormatter={(label) => label}
                          formatter={(value) => [`${Number(value).toLocaleString()} articles`, 'Articles']}
                        />
                        <Bar dataKey="count" fill="#f97316" radius={[0, 8, 8, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              ) : (
                <div className="mini-empty">No category data is available for this scope yet.</div>
              )}
            </motion.article>
          </div>
        </>
      ) : null}
    </section>
  );
}
