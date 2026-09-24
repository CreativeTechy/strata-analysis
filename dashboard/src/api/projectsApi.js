/**
 * Client for project CRUD, linkage, and intelligence-report endpoints.
 *
 * Most of these share the same request() shape as competitorApi.js/
 * projectDocumentsApi.js/adminApi.js/pipelineRunsApi.js - see those for the
 * `{ error, detail }` failure convention. getKeywordExistence() and
 * getTrendSummary() keep their own bespoke handling instead (see each) since
 * their backend routes don't follow that convention exactly.
 */

const BASE = '/api/projects';

async function request(path, { method = 'GET', body, signal } = {}) {
  const response = await fetch(`${BASE}${path}`, {
    method,
    credentials: 'include',
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
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

function query(params = {}) {
  const search = new URLSearchParams(
    Object.entries(params).filter(([, value]) => value !== undefined && value !== null && value !== ''),
  ).toString();
  return search ? `?${search}` : '';
}

/** create/update/delete/suggest below report some failures (invalid payload,
 *  a DB connection problem, a missing project name) as a 200 response
 *  carrying `{ error, detail }` rather than an HTTPException - a plain
 *  `response.ok` check would treat those as success. This mirrors request()
 *  but also throws on a 200 that carries `error`, joining `error`/`detail`
 *  the same way App.jsx's old formatApiError() did. */
async function requestSoftError(path, { method = 'GET', body } = {}, fallback) {
  const response = await fetch(`${BASE}${path}`, {
    method,
    credentials: 'include',
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data?.error) {
    const parts = [data?.error, data?.detail].filter(Boolean);
    throw new Error(parts.length > 0 ? parts.join(' - ') : `${fallback} (${response.status})`);
  }
  return data;
}

// --- projects --------------------------------------------------------------
export const listProjects = () => request('');
export const createProject = (body) => requestSoftError('', { method: 'POST', body }, 'Failed to add project');
export const updateProject = (projectId, body) =>
  requestSoftError(`/${projectId}`, { method: 'PUT', body }, 'Failed to update project');
export const deleteProject = (projectId) =>
  requestSoftError(`/${projectId}`, { method: 'DELETE' }, 'Failed to delete project');
export const setProjectUsers = (projectId, userIds) =>
  requestSoftError(`/${projectId}/users`, { method: 'POST', body: { user_ids: userIds } }, 'Failed to update linked users');
export const suggestProjectMetadata = (body) =>
  requestSoftError('/suggest', { method: 'POST', body }, 'Failed to generate suggestions');

// --- intelligence & reports --------------------------------------------------
export const getProjectIntelligence = (projectId, params) => request(`/${projectId}/intelligence${query(params)}`);
export const listIdeaClusters = (projectId, params, signal) =>
  request(`/${projectId}/idea-clusters${query(params)}`, { signal });
export const listIdeaClusterArticles = (projectId, clusterId, params) =>
  request(`/${projectId}/idea-clusters/${clusterId}/articles${query(params)}`);
export const getEvidenceWorkspace = (projectId, params, signal) =>
  request(`/${projectId}/evidence${query(params)}`, { signal });
export const getEvidenceClaim = (projectId, claimId, signal) =>
  request(`/${projectId}/evidence/claims/${claimId}`, { signal });
export const compareEvidenceRuns = (projectId, params, signal) =>
  request(`/${projectId}/evidence/compare${query(params)}`, { signal });
export const reviewEvidenceClaim = (projectId, claimId, body) =>
  request(`/${projectId}/evidence/claims/${claimId}/review`, { method: 'POST', body });
export const reviewEvidenceRelevance = (projectId, claimId, body) =>
  request(`/${projectId}/evidence/claims/${claimId}/relevance-review`, { method: 'POST', body });
export const reviewEvidenceProvenance = (projectId, articleId, body) =>
  request(`/${projectId}/evidence/articles/${articleId}/provenance-review`, { method: 'POST', body });
export const reviewEvidenceArticleScreening = (projectId, runId, articleId, body) =>
  request(`/${projectId}/evidence/runs/${runId}/articles/${articleId}/screening-review`, { method: 'POST', body });
export const retryEvidenceRun = (projectId, runId) =>
  request(`/${projectId}/evidence/runs/${runId}/retry`, { method: 'POST' });
export const updateEvidenceScope = (projectId, runId, body) =>
  request(`/${projectId}/evidence/runs/${runId}/scope`, { method: 'PUT', body });
export const listProjectSources = (projectId, { limit, offset } = {}) => (
  request(`/${projectId}/sources${query({ limit, offset })}`)
);
/** Sets one Sources-tab group's trust tier (see backend's source_trust.py).
 *  `key`/`type` are a source group's own fields, exactly as listProjectSources()
 *  returns them - there is no separate trust-management page or endpoint. */
export const setSourceTrust = (projectId, { key, type, tier, reason }) => (
  request(`/${projectId}/sources/trust`, { method: 'POST', body: { key, type, tier, reason } })
);

/** Cross-source idea comparison cards (see backend/services/articles/idea_comparisons.py).
 *  Like getTrendSummary(), a 200 response can still carry a soft `{ error }`
 *  (an LLM failure during `regenerate`) alongside whatever was already
 *  cached - returns { ok, data } so the caller can show both. */
export async function getIdeaComparisons(projectId, { regenerate, run_id } = {}, signal) {
  const response = await fetch(`${BASE}/${projectId}/idea-comparisons${query({ regenerate, run_id })}`, { signal });
  const data = await response.json().catch(() => ({}));
  return { ok: response.ok && !data?.error, data };
}

/** Unlike the rest of this module, a non-2xx here just means "couldn't reach
 *  the keyword-existence route at all" - the thrown message is a generic
 *  status-code string rather than anything read from the response body (this
 *  route doesn't carry a caller-facing error message the way the others do). */
export async function getKeywordExistence(projectId, params) {
  const response = await fetch(`${BASE}/${projectId}/keyword-existence${query(params)}`);
  if (!response.ok) throw new Error(`Keyword existence request failed: ${response.status}`);
  return response.json();
}

/** The backend can return this with a 200 status AND an `error` field (an
 *  LLM failure reported as a soft error, not an HTTPException) - so unlike
 *  every other export here, a successful HTTP response isn't the same thing
 *  as a successful result. Returns { ok, data } so the caller decides. */
export async function getTrendSummary(projectId, params) {
  const response = await fetch(`${BASE}/${projectId}/trend-summary${query(params)}`);
  const data = await response.json().catch(() => ({}));
  return { ok: response.ok && !data?.error, data };
}

/** Selected analysis run compared with the immediately preceding eligible
 * run. The response may be `unavailable` or `llm_failed` while still carrying
 * verified metrics, so callers inspect its status rather than treating those
 * states as transport failures. */
export const getReportVariation = (projectId, params, signal) =>
  request(`/${projectId}/reports/variation${query(params)}`, { signal });

/** Reports page's "Export Summary" button. Like exportArticles() in
 *  articlesApi.js, this streams a Blob (the PDF itself) rather than a parsed
 *  JSON body on success - a non-ok response is still plain JSON (the usual
 *  {error, detail} shape), so that branch mirrors this module's request(). */
export async function exportReportSummaryPdf(projectId, params) {
  const response = await fetch(`${BASE}/${projectId}/reports/summary.pdf${query(params)}`, {
    method: 'POST',
    credentials: 'include',
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data?.detail || data?.error || `Failed to export the report summary (${response.status})`);
  }
  return response.blob();
}
