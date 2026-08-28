/**
 * Client for the article library: search/filter/list, per-article analysis
 * detail/reprocessing, bulk delete, JSONL export/import, the analysis-health
 * dashboard, and the Intelligence Copilot chat.
 *
 * Most exports share the same request() shape as competitorApi.js/
 * projectDocumentsApi.js/adminApi.js/pipelineRunsApi.js/projectsApi.js - see
 * those for the `{ error, detail }` failure convention. A few endpoints
 * (marked below) don't follow that convention exactly and keep bespoke
 * handling instead, same reasoning as projectsApi.js's getTrendSummary().
 */

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
    const message = payload?.detail || payload?.error || `Request failed (${response.status})`;
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return payload ?? {};
}

/** Same as request(), but also throws when the body carries `error` on an
 *  otherwise-200 response - the shape POST /articles/import and its status
 *  endpoint use, since a job can fail after being successfully queued. */
async function requestSoftError(path, opts = {}) {
  const data = await request(path, opts);
  if (data?.error) {
    throw new Error(data?.detail || data?.error);
  }
  return data;
}

function query(params = {}) {
  const search = new URLSearchParams(
    Object.entries(params).filter(([, value]) => value !== undefined && value !== null && value !== ''),
  ).toString();
  return search ? `?${search}` : '';
}

// --- articles ----------------------------------------------------------
export const listArticles = (params, signal) => request(`/articles${query(params)}`, { signal });
export const getArticleAnalysis = (articleId, signal) => request(`/articles/${articleId}/analysis`, { signal });
export const reprocessArticle = (articleId) => request(`/articles/${articleId}/reprocess`, { method: 'POST' });
/** Batch retry: force-reruns analysis for the given article ids regardless of
 *  their current status. */
export const analyzeArticles = (body) => request('/articles/analyze', { method: 'POST', body });
export const deleteAllArticles = () => requestSoftError('/articles', { method: 'DELETE' });

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

// --- export/import -----------------------------------------------------
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
export const importArticles = (formData) => requestSoftError('/articles/import', { method: 'POST', body: formData, form: true });
export const getImportStatus = (runId) => requestSoftError(`/articles/import/${runId}`);

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
