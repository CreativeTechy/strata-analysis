/**
 * Client for session auth endpoints.
 *
 * Unlike the other domain modules, each of these keeps its own tailored
 * response handling rather than sharing a generic request()/requestForm()
 * pair (see AuthContext.jsx, the only caller): getCurrentUser() treats any
 * failure as "not signed in" rather than throwing, login()'s error message
 * comes straight from the body, and logout() doesn't check the response at
 * all - the caller clears local state regardless of whether the request
 * itself succeeded.
 */

const BASE = '/api/auth';

export async function getCurrentUser() {
  try {
    const response = await fetch(`${BASE}/me`);
    if (!response.ok) return null;
    const data = await response.json().catch(() => ({}));
    return data?.user ?? null;
  } catch {
    return null;
  }
}

export async function login(username, password) {
  const response = await fetch(`${BASE}/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data?.error || data?.detail || 'Login failed.');
  }
  return data?.user ?? null;
}

export async function logout() {
  await fetch(`${BASE}/logout`, { method: 'POST' });
}
