// Pure formatting/matching helpers and shared constants for ArticlesPage and
// its extracted subcomponents. highlightMatches returns JSX (a <mark> tree),
// so this file is .jsx rather than .js even though nothing here is a
// component.

export const SENTIMENTS = ['all', 'positive', 'negative', 'neutral', 'mixed'];
export const ARTICLE_STATUSES = ['all', 'assessed', 'pending', 'failed', 'not_assessed'];

export function sentimentBadgeState(article = {}) {
  const analysisStatus = String(article.analysis_status || '').toLowerCase();
  const stageStatus = article.sentiment_status;
  if (analysisStatus === 'pending' || analysisStatus === 'processing') return 'pending';
  if (analysisStatus === 'failed' || analysisStatus === 'partial' || stageStatus === 'failed') return 'failed';
  if (!(Object.prototype.hasOwnProperty.call(article, 'sentiment_status')) && article.sentiment) {
    return String(article.sentiment).toLowerCase();
  }
  if (stageStatus !== 'ran') {
    return 'not_assessed';
  }
  return String(article.sentiment || 'neutral').toLowerCase();
}
export const SORT_OPTIONS = [
  { value: 'published.desc', label: 'Newest first' },
  { value: 'published.asc', label: 'Oldest first' },
  { value: 'relevance_score.desc', label: 'Highest relevance' },
  { value: 'relevance_score.asc', label: 'Lowest relevance' },
  { value: 'created_at.desc', label: 'Recently saved' },
];

export const PAGE_SIZES = [12, 24, 48, 96];

// The formats the project-create wizard accepts (see ProjectWizard.jsx's
// dropzone) - all of them, including JSONL/NDJSON exports, go through the
// project-documents extraction/LLM-split pipeline (see ArticlesPage's
// importDocumentFiles), so they only work once a specific project is in
// scope and every resulting article gets a document_id to filter on.
export const DOCUMENT_NAME_RE = /\.(pdf|docx?|xlsx?|csv|png|jpe?g|json|jsonl|ndjson)$/i;
export const FULL_IMPORT_ACCEPT = '.pdf,.doc,.docx,.xls,.xlsx,.csv,.png,.jpg,.jpeg,.json,.jsonl,.ndjson';

// project_document_articles._materialize() (backend) writes this scheme onto
// article.url whenever an article has no real one of its own (an LLM split
// of an uploaded document) - article.source/source_url always point at the
// document either way. These three helpers are the one place the dashboard
// reconciles that into "the source" a human would actually want to see or
// click through to.
export const SYNTHETIC_SOURCE_PREFIX = 'document://';

export function isSyntheticUrl(url) {
  return !url || String(url).startsWith(SYNTHETIC_SOURCE_PREFIX);
}

// The article's own real URL, or null when it only has the synthetic
// document:// one - callers use this to decide whether to render a link at
// all rather than pointing one at an unnavigable custom scheme.
export function articleSourceLink(article) {
  const url = article?.url;
  return isSyntheticUrl(url) ? null : url;
}

export function articleSourceLabel(article) {
  const link = articleSourceLink(article);
  if (link) {
    try {
      return new URL(link).hostname.replace(/^www\./, '');
    } catch {
      // Malformed url - fall through to the document-level label below.
    }
  }
  return article?.source || 'Unknown source';
}

export function prettyLabel(value) {
  return String(value || '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

export function articleDate(value) {
  if (!value) return 'Unknown date';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString();
}

export function addedAtLabel(value) {
  if (!value) return 'Unknown';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

export function formatMatchScore(value) {
  const score = Number(value);
  if (!Number.isFinite(score)) return '';
  return score.toFixed(2);
}

export function confidencePct(value) {
  const score = Number(value);
  return Number.isFinite(score) ? `${Math.round(score * 100)}%` : null;
}

export function escapeRegExp(value) {
  return String(value || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// Wraps every case-insensitive occurrence of each word of `term` in `text`
// with a <mark> - matching the backend's own AND-of-tokens search (see
// _score_search_row in articles_search.py), which matches an article when
// all the search's words appear anywhere in it, not just as one contiguous
// phrase. So "Stellantis battery" highlights "Stellantis" and "battery"
// separately wherever each shows up, even far apart in the text.
export function highlightMatches(text, term) {
  const value = text == null ? '' : String(text);
  const needle = String(term || '').trim();
  if (!needle) return value;
  const tokens = [...new Set(needle.split(/\W+/).filter((token) => token.length > 1))];
  const alternatives = (tokens.length ? tokens : [needle]).map(escapeRegExp).sort((a, b) => b.length - a.length);
  const parts = value.split(new RegExp(`(${alternatives.join('|')})`, 'gi'));
  if (parts.length === 1) return value;
  return parts.map((part, index) =>
    index % 2 === 1 ? <mark key={index} className="article-search-highlight">{part}</mark> : part
  );
}

export function getPageNumbers(currentPage, totalPages) {
  if (totalPages <= 7) {
    return Array.from({ length: totalPages }, (_, i) => i + 1);
  }
  const pages = [1];
  if (currentPage > 3) pages.push('...');
  const start = Math.max(2, currentPage - 1);
  const end = Math.min(totalPages - 1, currentPage + 1);
  for (let page = start; page <= end; page += 1) pages.push(page);
  if (currentPage < totalPages - 2) pages.push('...');
  pages.push(totalPages);
  return pages;
}
