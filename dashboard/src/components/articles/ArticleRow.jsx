import { useTranslation } from 'react-i18next';
import { motion } from 'framer-motion';
import { ExternalLink, Calendar, CarFront, Tag, ChevronDown, Info } from 'lucide-react';
import {
  prettyLabel, formatMatchScore, highlightMatches,
  articleSourceLink, articleSourceLabel, sentimentBadgeState,
} from '../../lib/articleHelpers.jsx';
import { formatDate, formatDateTime, formatNumber, formatLanguageName } from '../../lib/i18nFormat.js';

// Bounded enum (positive/negative/neutral/mixed) - only the displayed label
// is translated, never the underlying article.sentiment code itself.
const SENTIMENT_KEYS = {
  positive: 'sentiment.positive',
  negative: 'sentiment.negative',
  neutral: 'sentiment.neutral',
  mixed: 'sentiment.mixed',
};

function sentimentLabel(t, sentiment) {
  if (sentiment === 'pending') return t('sentiment.pending');
  if (sentiment === 'failed') return t('sentiment.failed');
  if (sentiment === 'not_assessed') return t('sentiment.notAssessed');
  return t(SENTIMENT_KEYS[sentiment] || 'sentiment.neutral');
}

// articleHelpers.jsx's articleDate()/addedAtLabel() are ad hoc,
// locale-unaware toLocaleDateString()/toLocaleString() wrappers - these use
// the shared, locale-explicit formatters instead (see lib/i18nFormat.js),
// falling back to the same "Unknown date"/raw-value behavior those helpers had.
function displayDate(value, t, locale) {
  if (!value) return t('common.unknownDate');
  const formatted = formatDate(value, locale);
  return formatted || value;
}

function displayDateTime(value, t, locale) {
  if (!value) return t('common:misc.unknown');
  const formatted = formatDateTime(value, locale);
  return formatted || value;
}

// One row in the ("List") view mode - collapsed to a summary line by
// default, expanding in place to the same detail an ArticleCard shows.
export default function ArticleRow({ article, search, index, isExpanded, isRefreshing, onToggleExpanded, onShowDetails }) {
  const { t, i18n } = useTranslation(['articles', 'common']);
  const locale = i18n.language;
  const sourceLink = articleSourceLink(article);
  const sentimentState = sentimentBadgeState(article);
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
        <span className={`badge ${sentimentState}`}>
          {sentimentLabel(t, sentimentState)}
        </span>
        <span className="article-row-title" dir="auto">{highlightMatches(article.title || t('common.untitledArticle'), search)}</span>
        <span className="article-row-source" dir="auto">{articleSourceLabel(article)}</span>
        <span className="article-row-date">
          <Calendar size={13} /> {displayDate(article.published, t, locale)}
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
              <span className="panel-chip muted" style={{ textTransform: 'none', letterSpacing: 0 }} title={t('common.authorTitle')} dir="auto">
                {t('common.byAuthor', { author: article.author })}
              </span>
            ) : null}
            {article.region && article.region !== 'unknown' ? (
              <span className="panel-chip muted" style={{ textTransform: 'none', letterSpacing: 0 }} title={t('common.regionTitle')}>
                {t('common.regionLabel', { region: prettyLabel(article.region) })}
              </span>
            ) : null}
            {article.source_language ? (
              <span className="panel-chip muted" style={{ textTransform: 'none', letterSpacing: 0 }} title={t('common.languageTitle')}>
                {t('common.languageLabel', { language: formatLanguageName(article.source_language, locale) })}
              </span>
            ) : null}
            {article.source_run_snapshot?.started_at ? (
              <span
                className="panel-chip muted"
                style={{ textTransform: 'none', letterSpacing: 0 }}
                title={t('common.collectedTitle', { runId: article.source_run_snapshot.id })}
              >
                {t('common.collectedLabel', { date: displayDate(article.source_run_snapshot.started_at, t, locale) })}
              </span>
            ) : null}
            <span className="panel-chip muted" style={{ textTransform: 'none', letterSpacing: 0 }} title={t('common.addedTitle')}>
              <Calendar size={11} style={{ marginRight: 4 }} /> {t('common.addedLabel', { date: displayDateTime(article.fetched_at, t, locale) })}
            </span>
            {article.relevance_score != null && (
              <span className="badge score">
                {t('common.scoreLabel', { score: formatNumber(article.relevance_score, locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 }) })}
              </span>
            )}
            {article.project_similarity_score != null && (
              <span className="badge score">{t('common.projectMatchLabel', { score: formatMatchScore(article.project_similarity_score) })}</span>
            )}
          </div>

          <p className="article-summary" dir="auto">
            {highlightMatches(
              article.summary || article.insight_json?.summary || (article.text ? `${article.text.substring(0, 220)}...` : t('common.noSummaryAvailable')),
              search
            )}
          </p>

          {article.insight_json?.frequent_ideas?.length ? (
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
              {article.insight_json.frequent_ideas.slice(0, 3).map((item) => (
                <span key={item.idea} className="panel-chip muted" style={{ textTransform: 'none', letterSpacing: 0 }} dir="auto">
                  {item.idea}
                </span>
              ))}
            </div>
          ) : null}

          {(article.brands?.length > 0 || article.car_models?.length > 0) && (
            <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', marginTop: 5 }}>
              {article.brands?.slice(0, 4).map((brand) => (
                <span key={brand} style={{ fontSize: '0.75rem', color: 'var(--secondary-color)', display: 'flex', alignItems: 'center', gap: 3 }} dir="auto">
                  <Tag size={12} /> {brand}
                </span>
              ))}
              {article.car_models?.slice(0, 4).map((model) => (
                <span key={model} style={{ fontSize: '0.75rem', color: 'var(--primary-color)', display: 'flex', alignItems: 'center', gap: 3 }} dir="auto">
                  <CarFront size={12} /> {model}
                </span>
              ))}
            </div>
          )}

          <div className="article-row-details-actions">
            {sourceLink ? (
              <a href={sourceLink} target="_blank" rel="noopener noreferrer" className="btn-secondary" style={{ textDecoration: 'none' }}>
                <ExternalLink size={13} /> {t('row.openOriginal')}
              </a>
            ) : null}
            <button
              type="button"
              className="btn-secondary"
              onClick={onShowDetails}
              title={t('card.viewAnalysisDetailsTitle')}
            >
              <Info size={13} /> {t('row.analysisDetailsButton')}
            </button>
          </div>
        </div>
      ) : null}
    </motion.div>
  );
}
