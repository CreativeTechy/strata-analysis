/**
 * Client for user/role/permission administration.
 *
 * Same request() shape as competitorApi.js/projectDocumentsApi.js - see those
 * for the shared `{ error, detail }` failure convention. The pages this
 * replaces previously wrote their own per-call fallback message text (e.g.
 * "Failed to load users (404)"); that text only ever surfaced when the
 * backend response carried neither `error` nor `detail`, which none of these
 * routes' error paths do - main.py's exception handlers always set one.
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

// --- users -------------------------------------------------------------
/** Roster used by the project<->user linkage UI (App.jsx) - every user
 *  annotated with the project ids they're already linked to. */
export const listLinkableUsers = () => request('/users/linkable');
export const listUsers = () => request('/users');
export const createUser = (body) => request('/users', { method: 'POST', body });
export const updateUser = (userId, body) => request(`/users/${userId}`, { method: 'PATCH', body });
export const deleteUser = (userId) => request(`/users/${userId}`, { method: 'DELETE' });

// --- roles & permissions -------------------------------------------------
export const listPermissions = () => request('/permissions');
export const listRoles = () => request('/roles');
export const createRole = (body) => request('/roles', { method: 'POST', body });
export const updateRole = (roleId, body) => request(`/roles/${roleId}`, { method: 'PATCH', body });
export const deleteRole = (roleId) => request(`/roles/${roleId}`, { method: 'DELETE' });
