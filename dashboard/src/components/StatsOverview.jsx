import { Activity, TrendingUp, Database } from 'lucide-react';
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts';
import { motion } from 'framer-motion';

const COLORS = ['#2ed573', '#ff4757', '#747d8c'];

export default function StatsOverview({ stats = {}, crawlCount = null, scopeLabel = 'Current event' }) {
  const total = Number(stats.total) || 0;
  const positive = Number(stats.positive) || 0;
  const negative = Number(stats.negative) || 0;
  const neutral = Number(stats.neutral) || 0;
  const balance = positive - negative;
  const positivePct = total ? Math.round((positive / total) * 100) : 0;
  const negativePct = total ? Math.round((negative / total) * 100) : 0;
  const neutralPct = total ? Math.round((neutral / total) * 100) : 0;
  const dominant = total ? [
    { label: 'Positive', value: positive, pct: positivePct, color: '#2ed573' },
    { label: 'Negative', value: negative, pct: negativePct, color: '#ff4757' },
    { label: 'Neutral', value: neutral, pct: neutralPct, color: '#747d8c' },
  ].sort((a, b) => b.value - a.value)[0] : { label: 'Positive', pct: 0 };

  const data = [
    { name: 'Positive', value: positive },
    { name: 'Negative', value: negative },
    { name: 'Neutral', value: neutral },
  ];

  return (
    <div className="stats-grid">
      <motion.div className="glass-card stat-card" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
        <div className="stat-icon">
          <Activity size={24} />
        </div>
        <div className="stat-info">
          <h4>Curated Articles</h4>
          <p>{total.toLocaleString()}</p>
          <span style={{ fontSize: '0.72rem', color: 'var(--text-light)' }}>{scopeLabel}</span>
        </div>
      </motion.div>

      <motion.div className="glass-card stat-card" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}>
        <div className="stat-icon" style={{ background: 'linear-gradient(135deg, rgba(255,107,53,0.12), rgba(255,71,87,0.12))', color: '#ff6b35' }}>
          <Database size={24} />
        </div>
        <div className="stat-info">
          <h4>Crawl Corpus</h4>
          <p>{crawlCount == null ? '-' : crawlCount.toLocaleString()}</p>
          <span style={{ fontSize: '0.72rem', color: 'var(--text-light)' }}>spider pages to Spark</span>
        </div>
      </motion.div>

      <motion.div className="glass-card stat-card" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}>
        <div className="stat-icon" style={{ background: 'linear-gradient(135deg, rgba(46, 213, 115, 0.1), rgba(46, 134, 222, 0.1))', color: '#2ed573' }}>
          <TrendingUp size={24} />
        </div>
        <div className="stat-info">
          <h4>Sentiment Balance</h4>
          <p>{balance > 0 ? '+' : ''}{balance.toLocaleString()}</p>
          <span style={{ fontSize: '0.72rem', color: 'var(--text-light)' }}>
            +{positive} / -{negative} / {neutral} neutral
          </span>
        </div>
      </motion.div>

      <motion.div
        className="glass-card stat-card sentiment-report"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3 }}
      >
        <div className="sentiment-report-chart">
          <div className="sentiment-report-head">
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
        </div>

        <div className="sentiment-report-breakdown">
          {[
            { label: 'Positive', value: positive, pct: positivePct, color: '#2ed573' },
            { label: 'Negative', value: negative, pct: negativePct, color: '#ff4757' },
            { label: 'Neutral', value: neutral, pct: neutralPct, color: '#747d8c' },
          ].map((item) => (
            <div key={item.label} className="sentiment-row">
              <div className="sentiment-row-top">
                <span className="sentiment-label">
                  <span className="sentiment-dot" style={{ background: item.color }} />
                  {item.label}
                </span>
                <strong style={{ color: item.color }}>
                  {item.value.toLocaleString()}
                </strong>
              </div>
              <div className="sentiment-bar-track">
                <div
                  className="sentiment-bar-fill"
                  style={{ width: `${item.pct}%`, background: item.color }}
                />
              </div>
              <div className="sentiment-row-meta">
                <span>{item.pct}% of articles</span>
              </div>
            </div>
          ))}

          <div className="sentiment-footer">
            <span>Net balance</span>
            <strong style={{ color: balance > 0 ? '#2ed573' : balance < 0 ? '#ff4757' : '#747d8c' }}>
              {balance > 0 ? '+' : ''}{balance.toLocaleString()}
            </strong>
          </div>
        </div>
      </motion.div>
    </div>
  );
}
