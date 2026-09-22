/**
 * Client for pipeline (analysis) runs: the queued/running/finished history of
 * a project's AI-analysis passes over its articles.
 *
 * Two endpoint families share this module: /api/pipeline-runs (the run
 * records themselves - list/detail/stop/delete) and POST /api/analysis-runs
 * (starts a new one) - kept together since every page that reads pipeline
 * runs is also a page that can trigger one. Same request() shape as
 * competitorApi.js/projectDocumentsApi.js/adminApi.js - see those for the
 * shared `{ error, detail }` failure convention.
 */

const BASE = '/api';

async function request(path, { method = 'GET', body } = {}) {
  const response = await fetch(`${BASE}${path}`, {
    method,
    credentials: 'include',
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
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

export const listPipelineRuns = ({ limit, projectId } = {}) => {
  const params = new URLSearchParams();
  if (limit != null) params.set('limit', limit);
  if (projectId != null) params.set('project_id', projectId);
  const query = params.toString();
  return request(`/pipeline-runs${query ? `?${query}` : ''}`);
};
export const getPipelineRun = (runId) => request(`/pipeline-runs/${runId}`);
export const stopPipelineRun = (runId) => request(`/pipeline-runs/${runId}/stop`, { method: 'POST' });
/** Removes the run and what was recorded about it (per-document breakdown,
 *  per-article snapshots) - the articles it analyzed keep whatever analysis
 *  they currently hold. */
export const deletePipelineRun = (runId) => request(`/pipeline-runs/${runId}`, { method: 'DELETE' });
/** Starts a tracked analysis run for one project. `scope` is 'pending'
 *  (only articles that haven't succeeded yet) or 'all'. */
export const startAnalysisRun = (body) => request('/analysis-runs', { method: 'POST', body });
