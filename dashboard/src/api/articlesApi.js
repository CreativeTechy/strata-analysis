/**
 * Client for the article library: search/filter/list, per-article analysis
 * detail/reprocessing, per-project removal, JSONL export/import, the analysis-health
 * dashboard, and the Intelligence Copilot chat.
 *
 * Most exports share the same request() shape as competitorApi.js/
 * projectDocumentsApi.js/adminApi.js/pipelineRunsApi.js/projectsApi.js - see
 * those for the `{ error, detail }` failure convention. A few endpoints
 * (marked below) don't follow that convention exactly and keep bespoke
 * handling instead, same reasoning as projectsApi.js's getTrendSummary().
 */

import { apiErrorFromPayload } from '../lib/apiError.js';

const BASE = '/api';

async function request(path, { method = 'GET', body, signal, form } = {}) {
  const response = await fetch(`${BASE}${path}`, {
    method,
    credentials: 'include',
    headers: !form && body ? { 'Content-Type': 'application/json' } : undefined,
    body: form ? body : (body ? JSON.stringify(body) : undefined),
    signal,
  });

  let payload;
  try {
    payload = await response.json();
  } catch {
    payload = null; // empty or non-JSON body (e.g. 204, or an HTML error page)
  }

  if (!response.ok) {
    const error = apiErrorFromPayload(payload, `Request failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return payload ?? {};
}

function query(params = {}) {
  const search = new URLSearchParams(
    Object.entries(params).filter(([, value]) => value !== undefined && value !== null && value !== ''),
  ).toString();
  return search ? `?${search}` : '';
}

// --- articles ----------------------------------------------------------
export const listArticles = (params, signal) => request(`/articles${query(params)}`, { signal });
export const getArticleAnalysis = (articleId, params, signal) =>
  request(`/articles/${articleId}/analysis${query(params)}`, { signal });
export const reprocessArticle = (articleId) => request(`/articles/${articleId}/reprocess`, { method: 'POST' });
/** Batch retry: force-reruns analysis for the given article ids regardless of
 *  their current status. */
export const analyzeArticles = (body) => request('/articles/analyze', { method: 'POST', body });
/** What removing one project's articles would affect (counts + any in-flight
 *  analysis run) - shown in the confirmation dialog before committing. */
export const getProjectArticleRemovalPreview = (projectId, signal) =>
  request(`/projects/${projectId}/articles/removal-preview`, { signal });
/** Removes every article from one project. `confirm` must be the project's
 *  exact name - the backend rejects anything else with a 400. */
export const removeProjectArticles = (projectId, confirm) =>
  request(`/projects/${projectId}/articles`, { method: 'DELETE', body: { confirm } });
export const deleteArticle = (articleId) => request(`/articles/${articleId}`, { method: 'DELETE' });

// --- analysis health (Performance Logs page) --------------------------------
export const getAnalysisStatus = (params, signal) => request(`/analysis/status${query(params)}`, { signal });
export const listAnalysisErrors = (params, signal) => request(`/articles/analysis-errors${query(params)}`, { signal });

// --- stats -------------------------------------------------------------
/** Unlike every other export here, a non-ok response isn't treated as an
 *  error at all - the caller has never surfaced a stats-load failure, only a
 *  quietly empty state, so this returns null instead of throwing. An abort
 *  (the caller's own AbortController) still propagates, so the caller can
 *  tell "cancelled because a newer request superseded this one" apart from
 *  "actually failed" and avoid clobbering fresher state with a stale null. */
export async function getArticleStats(params, signal) {
  const response = await fetch(`${BASE}/articles/stats${query(params)}`, { credentials: 'include', signal });
  const data = await response.json().catch(() => null);
  return data && typeof data === 'object' ? data : null;
}

// --- export --------------------------------------------------------------
/** Streams the export as a Blob - the endpoint returns newline-delimited
 *  JSON for direct download, not a parsed JSON body. */
export async function exportArticles(params) {
  const response = await fetch(`${BASE}/articles/export${query(params)}`, { credentials: 'include' });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data?.detail || data?.error || `Failed to export articles (${response.status})`);
  }
  return response.blob();
}

// --- copilot -------------------------------------------------------------
/** Every handled outcome (a real reply, or an LLM failure reported as a soft
 *  error) comes back as a 200 - the caller branches on `data.error`/
 *  `data.reply` itself to render the right chat bubble, so this just returns
 *  { ok, data } rather than throwing. */
export async function sendChatMessage(body) {
  const response = await fetch(`${BASE}/chat`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  return { ok: response.ok, data };
}
