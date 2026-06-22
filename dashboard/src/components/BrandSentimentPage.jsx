import React, { useState, useEffect } from 'react';
import { supabase } from '../supabaseClient';
import { motion } from 'framer-motion';
import { BarChart3, TrendingUp, TrendingDown } from 'lucide-react';

const sentColor = (s) => (s > 0.15 ? '#2ed573' : s < -0.15 ? '#ff4757' : '#9aa0aa');
const confBadge = { high: '#2ed573', medium: '#ffb13b', low: '#9aa0aa' };

export default function BrandSentimentPage() {
  const [rows, setRows] = useState([]);
  const [crawlCount, setCrawlCount] = useState(null);

  useEffect(() => {
    (async () => {
      const { data } = await supabase
        .from('sentiment_rollup')
        .select('*')
        .order('mentions', { ascending: false });
      if (data) setRows(data);
      const { count } = await supabase
        .from('crawl_pages')
        .select('*', { count: 'exact', head: true });
      if (typeof count === 'number') setCrawlCount(count);
    })();
  }, []);

  const maxMentions = Math.max(1, ...rows.map((r) => r.mentions || 0));

  return (
    <div style={{ minHeight: '100vh', background: '#0d0f14', color: '#e8eaed', padding: '70px 28px 40px' }}>
      <div style={{ maxWidth: 1000, margin: '0 auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 4 }}>
          <BarChart3 size={26} color="#ff6b35" />
          <h1 style={{ fontSize: '1.7rem', fontWeight: 800, margin: 0 }}>Brand Sentiment</h1>
        </div>
        <p style={{ color: '#9aa0aa', marginBottom: 28 }}>
          Deduped + scored by Spark over the spider's crawl
          {crawlCount != null && <> — <b style={{ color: '#4aa3ff' }}>{crawlCount.toLocaleString()}</b> pages in <code style={{ color: '#ffb13b' }}>crawl_pages</code></>}.
        </p>

        {rows.length === 0 ? (
          <div style={{ color: '#9aa0aa', padding: 40, textAlign: 'center', border: '1px dashed rgba(255,255,255,0.12)', borderRadius: 14 }}>
            No rollup yet. Crawl with Spider Mode (Save on), then run the Spark Sentiment Rollup workflow.
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {rows.map((r, i) => {
              const s = Number(r.avg_sentiment) || 0;
              const total = (r.positive || 0) + (r.negative || 0) + (r.neutral || 0) || 1;
              return (
                <motion.div key={r.brand}
                  initial={{ opacity: 0, x: -16 }} animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: i * 0.025 }}
                  style={{ display: 'grid', gridTemplateColumns: '130px 1fr 90px 70px', alignItems: 'center', gap: 14,
                           background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.07)',
                           borderRadius: 12, padding: '12px 16px' }}>
                  <div style={{ fontWeight: 700, textTransform: 'capitalize', display: 'flex', alignItems: 'center', gap: 6 }}>
                    {s >= 0 ? <TrendingUp size={15} color="#2ed573" /> : <TrendingDown size={15} color="#ff4757" />}
                    {r.brand}
                  </div>
                  {/* sentiment bar from center */}
                  <div style={{ position: 'relative', height: 22, background: 'rgba(0,0,0,0.3)', borderRadius: 6 }}>
                    <div style={{ position: 'absolute', left: '50%', top: 0, bottom: 0, width: 1, background: 'rgba(255,255,255,0.15)' }} />
                    <div style={{ position: 'absolute', top: 3, bottom: 3, borderRadius: 4,
                                  background: sentColor(s),
                                  left: s >= 0 ? '50%' : `${50 + s * 50}%`,
                                  width: `${Math.abs(s) * 50}%` }} />
                    <span style={{ position: 'absolute', right: 8, top: 2, fontSize: '0.75rem', color: '#c4c9d2' }}>
                      {s > 0 ? '+' : ''}{s.toFixed(2)}
                    </span>
                  </div>
                  <div style={{ textAlign: 'right', fontSize: '0.8rem' }}>
                    <span style={{ color: '#2ed573' }}>{Math.round((r.positive || 0) / total * 100)}%+</span>{' '}
                    <span style={{ color: '#ff6b6b' }}>{Math.round((r.negative || 0) / total * 100)}%−</span>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div style={{ fontWeight: 700 }}>{(r.mentions || 0).toLocaleString()}</div>
                    <div style={{ fontSize: '0.62rem', color: confBadge[r.confidence] || '#9aa0aa', textTransform: 'uppercase' }}>{r.confidence}</div>
                  </div>
                </motion.div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
