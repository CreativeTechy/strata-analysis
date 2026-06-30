import { Activity, TrendingUp, Database, Sparkles, MessageCircle, ThumbsUp, ThumbsDown, ListOrdered, Layers3 } from 'lucide-react';
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid } from 'recharts';
import { motion } from 'framer-motion';

const COLORS = ['#16a34a', '#e11d48', '#64748b'];

const prettyLabel = (value) => String(value || '')
  .replace(/_/g, ' ')
  .replace(/\b\w/g, (char) => char.toUpperCase());

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

export default function StatsOverview({ stats = {}, crawlCount = null, scopeLabel = 'Current event', loading = false }) {
  const total = Number(stats.total) || 0;
  const positive = Number(stats.positive) || 0;
  const negative = Number(stats.negative) || 0;
  const neutral = Number(stats.neutral) || 0;
  const insights = stats.insights || {};
  const categoryBreakdown = Array.isArray(insights.article_category_breakdown) ? insights.article_category_breakdown : [];
  const positiveFeedback = Array.isArray(insights.positive_feedback) ? insights.positive_feedback : [];
  const negativeFeedback = Array.isArray(insights.negative_feedback) ? insights.negative_feedback : [];
  const requests = Array.isArray(insights.nice_to_have_features) ? insights.nice_to_have_features : [];
  const frequentIdeas = Array.isArray(insights.frequent_ideas) ? insights.frequent_ideas : [];
  const summary = insights.summary || '';
  const dominantInsight = prettyLabel(insights.article_category || 'general_article');
  const balance = positive - negative;
  const positivePct = total ? Math.round((positive / total) * 100) : 0;
  const negativePct = total ? Math.round((negative / total) * 100) : 0;
  const neutralPct = total ? Math.round((neutral / total) * 100) : 0;
  const dominant = total ? [
    { label: 'Positive', value: positive, pct: positivePct, color: '#16a34a' },
    { label: 'Negative', value: negative, pct: negativePct, color: '#e11d48' },
    { label: 'Neutral', value: neutral, pct: neutralPct, color: '#64748b' },
  ].sort((a, b) => b.value - a.value)[0] : { label: 'Positive', pct: 0 };

  const data = [
    { name: 'Positive', value: positive },
    { name: 'Negative', value: negative },
    { name: 'Neutral', value: neutral },
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
    ...frequentIdeas.map((item) => Number(item.frequency_estimate) || 0)
  );

  const renderInsightList = (title, icon, items, color, tone = 'neutral') => (
    <section className="source-mini-list" style={{ marginTop: 14 }}>
      <div className="mini-list-title">
        <span className="mini-list-title-icon" style={{ color }}>{icon}</span>
        <span>{title}</span>
      </div>
      {items.length ? (
        items.slice(0, 4).map((item) => {
          const text = item.text || item.idea || item.opinion || 'Unknown';
          const count = Number(item.count || item.frequency_estimate) || 1;
          const pct = Math.max(12, Math.round((count / maxInsightCount) * 100));
          const category = item.category ? prettyLabel(item.category) : '';
          return (
            <article key={`${title}-${text}`} className={`mini-list-row tone-${tone}`}>
              <div className="mini-list-row-copy">
                <span className="mini-list-row-text">{text}</span>
                {category ? <span className="mini-list-row-subtle">{category}</span> : null}
              </div>
              <div className="mini-list-row-meta">
                <span className="mini-list-row-badge" style={{ background: `${color}14`, color }}>
                  {count}
                </span>
              </div>
              <div className="mini-list-row-track">
                <div className="mini-list-row-fill" style={{ width: `${pct}%`, background: color }} />
              </div>
            </article>
          );
        })
      ) : (
        <div className="mini-empty">No items yet.</div>
      )}
    </section>
  );

  if (loading) {
    return (
      <section className="stats-grid">
        <StatSkeleton />
        <StatSkeleton />
        <StatSkeleton />
        <div className="glass-card stat-card sentiment-report stat-report-skeleton" aria-hidden="true">
          <div className="sentiment-report-layout">
            <div className="sentiment-visuals">
              <article className="sentiment-visual">
                <div className="sentiment-visual-head">
                  <div>
                    <div className="skeleton-line skeleton-shimmer stat-skeleton-title" style={{ width: '52%' }} />
                    <div className="skeleton-line skeleton-shimmer stat-skeleton-subtitle" style={{ width: '72%', marginTop: 10 }} />
                  </div>
                </div>
                <div className="sentiment-chart-shell">
                  <div className="sentiment-chart-skeleton skeleton-shimmer" />
                  <div className="sentiment-center-copy">
                    <div className="skeleton-line skeleton-shimmer" style={{ width: '38%', height: 24 }} />
                    <div className="skeleton-line skeleton-shimmer" style={{ width: '26%', height: 12, marginTop: 8 }} />
                  </div>
                </div>
                <div className="sentiment-chip-row">
                  {Array.from({ length: 3 }).map((_, index) => (
                    <div key={index} className="sentiment-chip">
                      <div className="skeleton-line skeleton-shimmer" style={{ width: 72, height: 14 }} />
                    </div>
                  ))}
                </div>
              </article>

              <article className="sentiment-visual">
                <div className="sentiment-visual-head">
                  <div>
                    <div className="skeleton-line skeleton-shimmer stat-skeleton-title" style={{ width: '48%' }} />
                    <div className="skeleton-line skeleton-shimmer stat-skeleton-subtitle" style={{ width: '64%', marginTop: 10 }} />
                  </div>
                </div>
                <div className="sentiment-chart-bars-skeleton">
                  {Array.from({ length: 4 }).map((_, index) => (
                    <div
                      key={index}
                      className="skeleton-line skeleton-shimmer"
                      style={{ width: `${84 - index * 10}%`, height: 16, borderRadius: 999 }}
                    />
                  ))}
                </div>
              </article>
            </div>

            <aside className="sentiment-report-aside">
              <article className="sentiment-summary-card">
                <div className="skeleton-line skeleton-shimmer stat-skeleton-title" style={{ width: '36%' }} />
                <div className="skeleton-line skeleton-shimmer stat-skeleton-value" style={{ width: '88%', marginTop: 8 }} />
                <div className="skeleton-line skeleton-shimmer stat-skeleton-subtitle" style={{ width: '74%', marginTop: 8 }} />
              </article>

              <div className="sentiment-report-breakdown">
                {Array.from({ length: 4 }).map((_, index) => (
                  <div key={index} className="sentiment-row">
                    <div className="sentiment-row-top">
                      <div className="skeleton-line skeleton-shimmer" style={{ width: '42%', height: 14 }} />
                      <div className="skeleton-line skeleton-shimmer" style={{ width: '18%', height: 14 }} />
                    </div>
                    <div className="sentiment-bar-track">
                      <div className="sentiment-bar-fill skeleton-shimmer" style={{ width: '72%' }} />
                    </div>
                    <div className="skeleton-line skeleton-shimmer" style={{ width: '28%', height: 12 }} />
                  </div>
                ))}
              </div>
            </aside>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="stats-grid">
      <motion.article className="glass-card stat-card" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
        <div className="stat-icon">
          <Activity size={24} />
        </div>
        <div className="stat-info">
          <h4>Curated Articles</h4>
          <p>{total.toLocaleString()}</p>
          <span style={{ fontSize: '0.72rem', color: 'var(--text-light)' }}>{scopeLabel}</span>
        </div>
      </motion.article>

      <motion.article className="glass-card stat-card" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}>
        <div className="stat-icon" style={{ background: 'linear-gradient(135deg, rgba(255,107,53,0.12), rgba(255,71,87,0.12))', color: '#e87d34' }}>
          <Database size={24} />
        </div>
        <div className="stat-info">
          <h4>Crawl Corpus</h4>
          <p>{crawlCount == null ? '-' : crawlCount.toLocaleString()}</p>
          <span style={{ fontSize: '0.72rem', color: 'var(--text-light)' }}>spider pages to Spark</span>
        </div>
      </motion.article>

      <motion.article className="glass-card stat-card" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}>
        <div className="stat-icon" style={{ background: 'linear-gradient(135deg, rgba(22, 163, 74, 0.1), rgba(46, 134, 222, 0.1))', color: '#16a34a' }}>
          <TrendingUp size={24} />
        </div>
        <div className="stat-info">
          <h4>Sentiment Balance</h4>
          <p>{balance > 0 ? '+' : ''}{balance.toLocaleString()}</p>
          <span style={{ fontSize: '0.72rem', color: 'var(--text-light)' }}>
            +{positive} / -{negative} / {neutral} neutral
          </span>
        </div>
      </motion.article>

      <motion.article
        className="glass-card stat-card sentiment-report"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3 }}
        style={{ minHeight: 560 }}
      >
        <div className="sentiment-report-layout">
          <div className="sentiment-visuals">
            <article className="sentiment-visual sentiment-visual-mix">
              <div className="sentiment-visual-head">
                <div className="stat-info">
                  <h4>Sentiment Mix</h4>
                  <p>{total.toLocaleString()}</p>
                  <span style={{ fontSize: '0.72rem', color: 'var(--text-light)' }}>
                    {dominant.label} leads with {dominant.pct}% of the current set
                  </span>
                </div>
              </div>

              <div className="sentiment-chart-shell">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={data}
                      innerRadius={58}
                      outerRadius={82}
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

              <div className="sentiment-chip-row">
                {[
                  { label: 'Positive', pct: positivePct, color: '#16a34a' },
                  { label: 'Negative', pct: negativePct, color: '#e11d48' },
                  { label: 'Neutral', pct: neutralPct, color: '#64748b' },
                ].map((item) => (
                  <div key={item.label} className="sentiment-chip">
                    <span className="sentiment-dot" style={{ background: item.color }} />
                    <span>{item.label}</span>
                    <strong>{item.pct}%</strong>
                  </div>
                ))}
              </div>
            </article>

            <article className="sentiment-visual">
              <div className="sentiment-visual-head">
                <div className="mini-list-title" style={{ margin: 0 }}>
                  <Layers3 size={14} />
                  <span>Article categories</span>
                </div>
              </div>

              <div className="sentiment-chart-bars">
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
            </article>
          </div>

          <aside className="sentiment-report-aside">
            <article className="sentiment-summary-card">
              <div className="panel-kicker" style={{ marginBottom: 10 }}>
                <Sparkles size={14} /> Insight summary
              </div>
              <div style={{ fontSize: '1.05rem', fontWeight: 700, lineHeight: 1.45, color: 'var(--text-dark)' }}>
                {summary || 'No summary insight was generated for this scope yet.'}
              </div>
              <div style={{ marginTop: 10, color: 'var(--text-light)', fontSize: '0.82rem' }}>
                Dominant article category: <strong style={{ color: 'var(--secondary-color)' }}>{dominantInsight}</strong>
              </div>
            </article>

            {renderInsightList('Top praised features', <ThumbsUp size={14} color="#16a34a" />, positiveFeedback, '#16a34a', 'positive')}
            {renderInsightList('Top complaints', <ThumbsDown size={14} color="#e11d48" />, negativeFeedback, '#e11d48', 'negative')}
            {renderInsightList('Requested improvements', <MessageCircle size={14} color="#f59e0b" />, requests, '#f59e0b', 'requested')}
            {renderInsightList('Repeated ideas', <ListOrdered size={14} color="#64748b" />, frequentIdeas, '#64748b', 'neutral')}
          </aside>
        </div>
      </motion.article>
    </section>
  );
}
