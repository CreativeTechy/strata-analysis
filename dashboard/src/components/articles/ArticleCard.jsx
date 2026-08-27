import { motion } from 'framer-motion';
import { ExternalLink, Calendar, CarFront, Tag, Info } from 'lucide-react';
import { computeOverallTone } from '../../lib/tone.js';
import { prettyLabel, articleDate, addedAtLabel, formatMatchScore, highlightMatches } from '../../lib/articleHelpers.jsx';

// One card in the grid ("Cards") view mode.
export default function ArticleCard({ article, search, index, isRefreshing, onShowDetails }) {
  return (
    <motion.div
      layout
      initial={{ opacity: 0, scale: 0.96, y: 16 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.96 }}
      transition={{ duration: 0.25, delay: Math.min((index % 12) * 0.03, 0.4) }}
      className="glass-card article-card"
      style={isRefreshing ? { opacity: 0.72, pointerEvents: 'none' } : undefined}
    >
      <div className="article-header">
        <div className="article-meta">
          <span className={`badge ${article.sentiment?.toLowerCase() || 'neutral'}`}>
            {article.sentiment || 'Neutral'}
          </span>
          <span className="badge category">
            {prettyLabel(article.article_category || article.category || 'general_article')}
          </span>
          {article.source_language ? (
            <span className="panel-chip muted" style={{ textTransform: 'none', letterSpacing: 0 }} title="Detected source language">
              Language: {article.source_language.toUpperCase()}
            </span>
          ) : null}
          {article.source_run_snapshot?.started_at ? (
            <span
              className="panel-chip muted"
              style={{ textTransform: 'none', letterSpacing: 0 }}
              title={`Collected by scraper-app pipeline run ${article.source_run_snapshot.id}`}
            >
              Collected: {articleDate(article.source_run_snapshot.started_at)}
            </span>
          ) : null}
          <span className="panel-chip muted" style={{ textTransform: 'none', letterSpacing: 0 }} title="Writer tone">
            Writer: {prettyLabel(article.writer_tone || 'neutral')}
          </span>
          <span className="panel-chip muted" style={{ textTransform: 'none', letterSpacing: 0 }} title="Article tone">
            Article: {prettyLabel(article.article_tone || 'neutral')}
          </span>
          <span className="panel-chip muted" style={{ textTransform: 'none', letterSpacing: 0 }} title="Overall tone (derived from writer + article tone)">
            Overall: {prettyLabel(computeOverallTone(article.article_tone, article.writer_tone))}
          </span>
          <span className="panel-chip muted" style={{ textTransform: 'none', letterSpacing: 0 }} title="When this article entered the system">
            <Calendar size={11} style={{ marginRight: 4 }} /> Added: {addedAtLabel(article.fetched_at)}
          </span>
          {article.relevance_score != null && (
            <span className="badge score">Score: {Number(article.relevance_score).toFixed(1)}/10</span>
          )}
          {article.project_similarity_score != null && (
            <span className="badge score">Project match: {formatMatchScore(article.project_similarity_score)}</span>
          )}
        </div>
        <button
          type="button"
          className="btn-secondary"
          style={{ padding: '4px 8px', fontSize: '0.72rem', flexShrink: 0 }}
          onClick={onShowDetails}
          title="View analysis details"
        >
          <Info size={13} /> Details
        </button>
      </div>

      <h3 className="article-title">
        <a href={article.url} target="_blank" rel="noopener noreferrer" style={{ color: 'inherit', textDecoration: 'none' }}>
          {highlightMatches(article.title || 'Untitled article', search)} <ExternalLink size={14} style={{ opacity: 0.5 }} />
        </a>
      </h3>

      <p className="article-summary">
        {highlightMatches(
          article.summary || article.insight_json?.summary || (article.text ? `${article.text.substring(0, 160)}...` : 'No summary available.'),
          search
        )}
      </p>

      {article.insight_json?.frequent_ideas?.length ? (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
          {article.insight_json.frequent_ideas.slice(0, 3).map((item) => (
            <span key={item.idea} className="panel-chip muted" style={{ textTransform: 'none', letterSpacing: 0 }}>
              {item.idea}
            </span>
          ))}
        </div>
      ) : null}

      {(article.brands?.length > 0 || article.car_models?.length > 0) && (
        <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', marginTop: 5 }}>
          {article.brands?.slice(0, 2).map((brand) => (
            <span key={brand} style={{ fontSize: '0.75rem', color: 'var(--secondary-color)', display: 'flex', alignItems: 'center', gap: 3 }}>
              <Tag size={12} /> {brand}
            </span>
          ))}
          {article.car_models?.slice(0, 2).map((model) => (
            <span key={model} style={{ fontSize: '0.75rem', color: 'var(--primary-color)', display: 'flex', alignItems: 'center', gap: 3 }}>
              <CarFront size={12} /> {model}
            </span>
          ))}
        </div>
      )}

      <div className="article-footer">
        <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <Calendar size={14} /> {articleDate(article.published)}
        </span>
        <span>{article.source || 'Unknown source'}</span>
      </div>
    </motion.div>
  );
}
