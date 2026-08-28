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
