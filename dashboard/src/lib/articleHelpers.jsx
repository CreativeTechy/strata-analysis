// Pure formatting/matching helpers and shared constants for ArticlesPage and
// its extracted subcomponents. highlightMatches returns JSX (a <mark> tree),
// so this file is .jsx rather than .js even though nothing here is a
// component.

export const SENTIMENTS = ['all', 'positive', 'negative', 'neutral', 'mixed'];
export const SORT_OPTIONS = [
  { value: 'published.desc', label: 'Newest first' },
  { value: 'published.asc', label: 'Oldest first' },
  { value: 'relevance_score.desc', label: 'Highest relevance' },
  { value: 'relevance_score.asc', label: 'Lowest relevance' },
  { value: 'created_at.desc', label: 'Recently saved' },
];

export const PAGE_SIZES = [12, 24, 48, 96];

// How often to poll a running import for its counters. Matches the cadence the
// competitor workspace polls its discovery/analysis jobs at.
export const IMPORT_POLL_MS = 900;

// Folder pickers hand back every file under the folder regardless of the
// input's `accept` filter, so JSONL exports have to be picked out client-side.
export const JSONL_NAME_RE = /\.(jsonl|ndjson)$/i;

// The broader formats the project-create wizard accepts (see ProjectWizard.jsx's
// dropzone) - these need extraction/LLM-splitting via the project-documents
// pipeline, so they only work once a specific project is in scope (see
// ArticlesPage's importDocumentFiles), unlike JSONL exports which import unlinked too.
export const DOCUMENT_NAME_RE = /\.(pdf|docx?|xlsx?|csv|png|jpe?g|json)$/i;
export const FULL_IMPORT_ACCEPT = '.pdf,.doc,.docx,.xls,.xlsx,.csv,.png,.jpg,.jpeg,.json,.jsonl,.ndjson';
export const JSONL_ONLY_ACCEPT = '.jsonl,.ndjson,application/x-ndjson';

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
