import React from 'react';
import { Activity, MessageSquare, TrendingUp } from 'lucide-react';
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts';
import { motion } from 'framer-motion';

const COLORS = ['#2ed573', '#ff4757', '#747d8c'];

export default function StatsOverview({ articles }) {
  const total = articles.length;
  
  const sentimentCounts = articles.reduce((acc, curr) => {
    const s = curr.sentiment?.toLowerCase() || 'neutral';
    if (s.includes('positive')) acc.positive++;
    else if (s.includes('negative')) acc.negative++;
    else acc.neutral++;
    return acc;
  }, { positive: 0, negative: 0, neutral: 0 });

  const data = [
    { name: 'Positive', value: sentimentCounts.positive },
    { name: 'Negative', value: sentimentCounts.negative },
    { name: 'Neutral', value: sentimentCounts.neutral },
  ];

  const avgRelevance = articles.length ? 
    (articles.reduce((acc, curr) => acc + (curr.relevance_score || 0), 0) / total).toFixed(1) : 0;

  return (
    <div className="stats-grid">
      <motion.div className="glass-card stat-card" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
        <div className="stat-icon">
          <Activity size={24} />
        </div>
        <div className="stat-info">
          <h4>Total Articles</h4>
          <p>{total}</p>
        </div>
      </motion.div>

      <motion.div className="glass-card stat-card" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}>
        <div className="stat-icon" style={{ background: 'linear-gradient(135deg, rgba(46, 213, 115, 0.1), rgba(46, 134, 222, 0.1))', color: '#2ed573' }}>
          <TrendingUp size={24} />
        </div>
        <div className="stat-info">
          <h4>Avg Relevance Score</h4>
          <p>{avgRelevance} / 10</p>
        </div>
      </motion.div>

      <motion.div className="glass-card stat-card" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }} initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }}>
        <div className="stat-info">
          <h4>Sentiment Mix</h4>
          <div style={{ display: 'flex', gap: '10px', marginTop: '5px', fontSize: '0.8rem', color: 'var(--text-light)' }}>
            <span style={{ color: '#2ed573' }}>● {sentimentCounts.positive}</span>
            <span style={{ color: '#ff4757' }}>● {sentimentCounts.negative}</span>
            <span style={{ color: '#747d8c' }}>● {sentimentCounts.neutral}</span>
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
