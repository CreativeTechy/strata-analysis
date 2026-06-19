import React, { useState, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ExternalLink, Calendar, CarFront, Tag } from 'lucide-react';

export default function FeedView({ articles, isScraping }) {
  const [filterSentiment, setFilterSentiment] = useState('All');
  const [filterCategory, setFilterCategory] = useState('All');
  const [visibleCount, setVisibleCount] = useState(9);

  const categories = ['All', ...new Set(articles.map(a => a.category).filter(Boolean))];

  const filteredArticles = useMemo(() => {
    return articles.filter(article => {
      const matchSentiment = filterSentiment === 'All' || 
        (article.sentiment && article.sentiment.toLowerCase() === filterSentiment.toLowerCase());
      const matchCategory = filterCategory === 'All' || 
        article.category === filterCategory;
      return matchSentiment && matchCategory;
    }).sort((a, b) => new Date(b.published) - new Date(a.published));
  }, [articles, filterSentiment, filterCategory]);

  if (isScraping) {
    return (
      <div className="articles-grid">
        {[...Array(6)].map((_, i) => (
          <div key={i} className="glass-card" style={{ height: '250px', animation: 'pulse 1.5s infinite', background: 'rgba(255,255,255,0.4)' }} />
        ))}
      </div>
    );
  }

  return (
    <div>
      <div className="filters">
        <select 
          className="filter-select" 
          value={filterSentiment} 
          onChange={(e) => setFilterSentiment(e.target.value)}
        >
          <option value="All">All Sentiments</option>
          <option value="Positive">Positive</option>
          <option value="Negative">Negative</option>
          <option value="Neutral">Neutral</option>
        </select>

        <select 
          className="filter-select" 
          value={filterCategory} 
          onChange={(e) => setFilterCategory(e.target.value)}
        >
          {categories.map(c => (
            <option key={c} value={c}>{c === 'All' ? 'All Categories' : c}</option>
          ))}
        </select>
      </div>

      <div className="articles-grid">
        <AnimatePresence>
          {filteredArticles.slice(0, visibleCount).map((article, i) => (
            <motion.div 
              key={article.url}
              layout
              initial={{ opacity: 0, scale: 0.95, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95 }}
              transition={{ duration: 0.3, delay: Math.min((i % 9) * 0.05, 0.5) }}
              className="glass-card article-card"
            >
              <div className="article-header">
                <div className="article-meta">
                  <span className={`badge ${article.sentiment?.toLowerCase() || 'neutral'}`}>
                    {article.sentiment || 'Neutral'}
                  </span>
                  <span className="badge category">
                    {article.category || 'News'}
                  </span>
                  {article.relevance_score > 0 && (
                    <span className="badge score">Score: {article.relevance_score}/10</span>
                  )}
                </div>
              </div>

              <h3 className="article-title">
                <a href={article.url} target="_blank" rel="noopener noreferrer" style={{ color: 'inherit', textDecoration: 'none' }}>
                  {article.title} <ExternalLink size={14} style={{ opacity: 0.5 }} />
                </a>
              </h3>

              <p className="article-summary">{article.summary || (article.text ? article.text.substring(0, 120) + '...' : '')}</p>

              {(article.brands?.length > 0 || article.car_models?.length > 0) && (
                <div style={{ display: 'flex', gap: '5px', flexWrap: 'wrap', marginTop: '5px' }}>
                  {article.brands?.slice(0, 2).map(b => (
                    <span key={b} style={{ fontSize: '0.75rem', color: 'var(--secondary-color)', display: 'flex', alignItems: 'center', gap: '3px' }}>
                      <Tag size={12} /> {b}
                    </span>
                  ))}
                  {article.car_models?.slice(0, 2).map(m => (
                    <span key={m} style={{ fontSize: '0.75rem', color: 'var(--primary-color)', display: 'flex', alignItems: 'center', gap: '3px' }}>
                      <CarFront size={12} /> {m}
                    </span>
                  ))}
                </div>
              )}

              <div className="article-footer">
                <span style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                  <Calendar size={14} /> {new Date(article.published).toLocaleDateString()}
                </span>
                <span>{article.source}</span>
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
      
      {visibleCount < filteredArticles.length && (
        <div style={{ display: 'flex', justifyContent: 'center', marginTop: '30px' }}>
          <button 
            className="btn-secondary" 
            onClick={() => setVisibleCount(prev => prev + 9)}
            style={{ padding: '12px 30px', fontSize: '1rem' }}
          >
            Load More Articles
          </button>
        </div>
      )}
      
      {filteredArticles.length === 0 && (
        <div style={{ textAlign: 'center', padding: '50px', color: 'var(--text-light)' }}>
          No articles found matching the current filters.
        </div>
      )}
    </div>
  );
}
