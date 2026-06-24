import React from 'react';
import { Activity, TrendingUp, Database } from 'lucide-react';
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts';
import { motion } from 'framer-motion';

const COLORS = ['#2ed573', '#ff4757', '#747d8c'];

export default function StatsOverview({ stats = {}, crawlCount = null }) {
  const total = Number(stats.total) || 0;
  const positive = Number(stats.positive) || 0;
  const negative = Number(stats.negative) || 0;
  const neutral = Number(stats.neutral) || 0;
  const balance = positive - negative;

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

      <motion.div className="glass-card stat-card" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }} initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }}>
        <div className="stat-info">
          <h4>Sentiment Mix</h4>
          <div style={{ display: 'flex', gap: '10px', marginTop: '5px', fontSize: '0.8rem', color: 'var(--text-light)' }}>
            <span style={{ color: '#2ed573' }}>- {positive}</span>
            <span style={{ color: '#ff4757' }}>- {negative}</span>
            <span style={{ color: '#747d8c' }}>- {neutral}</span>
          </div>
        </div>
        <div style={{ width: '80px', height: '80px' }}>
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={data} innerRadius={25} outerRadius={35} paddingAngle={5} dataKey="value" stroke="none">
                {data.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip contentStyle={{ borderRadius: '10px', border: 'none', boxShadow: '0 4px 15px rgba(0,0,0,0.1)' }} />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </motion.div>
    </div>
  );
}
