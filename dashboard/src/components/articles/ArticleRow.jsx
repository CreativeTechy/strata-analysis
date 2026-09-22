import { motion } from 'framer-motion';
import { ExternalLink, Calendar, CarFront, Tag, ChevronDown, Info } from 'lucide-react';
import {
  prettyLabel, articleDate, addedAtLabel, formatMatchScore, highlightMatches,
  articleSourceLink, articleSourceLabel,
} from '../../lib/articleHelpers.jsx';

// One row in the ("List") view mode - collapsed to a summary line by
// default, expanding in place to the same detail an ArticleCard shows.
export default function ArticleRow({ article, search, index, isExpanded, isRefreshing, onToggleExpanded, onShowDetails }) {
  const sourceLink = articleSourceLink(article);
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.2, delay: Math.min((index % 24) * 0.015, 0.3) }}
      className={`glass-card article-row ${isExpanded ? 'expanded' : ''}`}
      style={isRefreshing ? { opacity: 0.72, pointerEvents: 'none' } : undefined}
    >
      <button
        type="button"
        className="article-row-summary"
        onClick={onToggleExpanded}
        aria-expanded={isExpanded}
      >
        <span className={`badge ${article.sentiment?.toLowerCase() || 'neutral'}`}>
          {article.sentiment || 'Neutral'}
        </span>
        <span className="article-row-title">{highlightMatches(article.title || 'Untitled article', search)}</span>
        <span className="article-row-source">{articleSourceLabel(article)}</span>
        <span className="article-row-date">
          <Calendar size={13} /> {articleDate(article.published)}
        </span>
        <ChevronDown size={16} className="article-row-chevron" />
      </button>

      {isExpanded ? (
        <div className="article-row-details">
          <div className="article-meta">
            <span className="badge category">
              {prettyLabel(article.article_category || article.category || 'general_article')}
            </span>
            {article.author ? (
              <span className="panel-chip muted" style={{ textTransform: 'none', letterSpacing: 0 }} title="Author">
                By {article.author}
              </span>
            ) : null}
            {article.region && article.region !== 'unknown' ? (
              <span className="panel-chip muted" style={{ textTransform: 'none', letterSpacing: 0 }} title="Region">
                Region: {prettyLabel(article.region)}
              </span>
            ) : null}
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

          <p className="article-summary">
            {highlightMatches(
              article.summary || article.insight_json?.summary || (article.text ? `${article.text.substring(0, 220)}...` : 'No summary available.'),
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
              {article.brands?.slice(0, 4).map((brand) => (
                <span key={brand} style={{ fontSize: '0.75rem', color: 'var(--secondary-color)', display: 'flex', alignItems: 'center', gap: 3 }}>
                  <Tag size={12} /> {brand}
                </span>
              ))}
              {article.car_models?.slice(0, 4).map((model) => (
                <span key={model} style={{ fontSize: '0.75rem', color: 'var(--primary-color)', display: 'flex', alignItems: 'center', gap: 3 }}>
                  <CarFront size={12} /> {model}
                </span>
              ))}
            </div>
          )}

          <div className="article-row-details-actions">
            {sourceLink ? (
              <a href={sourceLink} target="_blank" rel="noopener noreferrer" className="btn-secondary" style={{ textDecoration: 'none' }}>
                <ExternalLink size={13} /> Open original
              </a>
            ) : null}
            <button
              type="button"
              className="btn-secondary"
              onClick={onShowDetails}
              title="View analysis details"
            >
              <Info size={13} /> Analysis details
            </button>
          </div>
        </div>
      ) : null}
    </motion.div>
  );
}
