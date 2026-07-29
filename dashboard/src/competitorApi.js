/**
 * Client for the competitor-study API.
 *
 * One place that knows the endpoint shapes and how this backend reports errors:
 * failures come back as `{ error, detail }` with a non-2xx status, so every call
 * funnels through `request()` and throws an Error carrying the server's message.
 * Components then only handle `try/catch`, never response plumbing.
 */

const BASE = '/api/competitor';

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
    payload = null;   // empty or non-JSON body (e.g. 204, or an HTML error page)
  }

  if (!response.ok) {
    const message =
      payload?.detail || payload?.error || `Request failed (${response.status})`;
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return payload ?? {};
}

// --- studies ---------------------------------------------------------------
export const listStudies = () => request('/studies');
/** Cross-study totals + recent findings, for the Dashboard/Reports pulse card. */
export const getOverview = () => request('/overview');
export const createStudy = (body) => request('/studies', { method: 'POST', body });
export const getStudy = (id) => request(`/studies/${id}`);

// --- business profile ------------------------------------------------------
export const getProfile = (id) => request(`/studies/${id}/profile`);
/** Scrapes the website and derives market context — expect this to take a while. */
export const buildProfile = (id, body) => request(`/studies/${id}/profile`, { method: 'POST', body });
export const saveProfile = (id, body) => request(`/studies/${id}/profile`, { method: 'PUT', body });

// --- competitors -----------------------------------------------------------
/** Queues discovery as a background job; returns { run_id, status } immediately.
 *  Poll getDiscoveryStatus(id, run_id) until status is 'success' or 'failed'. */
export const discoverCompetitors = (id, body) => request(`/studies/${id}/discover`, { method: 'POST', body });
export const getDiscoveryStatus = (id, runId) => request(`/studies/${id}/discover/${runId}`);
export const listCompetitors = (id) => request(`/studies/${id}/competitors`);
export const addCompetitor = (id, body) => request(`/studies/${id}/competitors`, { method: 'POST', body });
export const setCompetitorStatus = (competitorId, status) =>
  request(`/competitors/${competitorId}/status`, { method: 'POST', body: { status } });
export const deleteCompetitor = (competitorId) =>
  request(`/competitors/${competitorId}`, { method: 'DELETE' });

// --- accounts --------------------------------------------------------------
export const listAccounts = (competitorId) => request(`/competitors/${competitorId}/accounts`);
export const discoverAccounts = (competitorId) =>
  request(`/competitors/${competitorId}/accounts/discover`, { method: 'POST' });
export const addAccount = (competitorId, body) =>
  request(`/competitors/${competitorId}/accounts`, { method: 'POST', body });
export const validateAccount = (accountId, status, reason = '') =>
  request(`/accounts/${accountId}/validate`, { method: 'POST', body: { status, reason } });
export const deleteAccount = (accountId) => request(`/accounts/${accountId}`, { method: 'DELETE' });

// --- analysis --------------------------------------------------------------
export const analyze = (id, body) => request(`/studies/${id}/analyze`, { method: 'POST', body });
export const listFindings = (id, params = {}) => {
  const query = new URLSearchParams(
    Object.entries(params).filter(([, value]) => value !== undefined && value !== null && value !== ''),
  ).toString();
  return request(`/studies/${id}/findings${query ? `?${query}` : ''}`);
};
export const getFinding = (findingId) => request(`/findings/${findingId}`);
export const validateFinding = (findingId, status, notes = '') =>
  request(`/findings/${findingId}/validate`, { method: 'POST', body: { status, notes } });

// --- scheduling ------------------------------------------------------------
export const getSchedule = (id) => request(`/studies/${id}/schedule`);
export const setSchedule = (id, body) => request(`/studies/${id}/schedule`, { method: 'PUT', body });
export const syncSources = (id) => request(`/studies/${id}/sync-sources`, { method: 'POST' });

// --- shared presentation helpers ------------------------------------------
export const SIZE_TIER_LABELS = {
  enterprise: 'Enterprise',
  mid_market: 'Mid-market',
  smb: 'SMB',
  startup: 'Startup',
  unknown: 'Unknown size',
};

export const IMPACT_LABELS = { high: 'High impact', medium: 'Medium impact', low: 'Low impact' };

export const URGENCY_LABELS = { now: 'Now', this_quarter: 'This quarter', watch: 'Watch' };

export const EFFORT_LABELS = { low: 'Low effort', medium: 'Medium effort', high: 'High effort' };

/** Initials for a competitor avatar, e.g. "Blue Yonder" -> "BY". */
export function initials(name) {
  const words = String(name || '')
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (!words.length) return '?';
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[1][0]).toUpperCase();
}

/** Stable per-competitor avatar colour, so a company looks the same everywhere. */
export function avatarGradient(name) {
  const palette = [
    ['#6366f1', '#4338ca'],
    ['#0ea5e9', '#0369a1'],
    ['#14b8a6', '#0f766e'],
    ['#f59e0b', '#b45309'],
    ['#ec4899', '#be185d'],
    ['#8b5cf6', '#6d28d9'],
  ];
  let hash = 0;
  const text = String(name || '');
  for (let i = 0; i < text.length; i += 1) {
    hash = (hash * 31 + text.charCodeAt(i)) % 997;
  }
  const [from, to] = palette[hash % palette.length];
  return `linear-gradient(135deg, ${from}, ${to})`;
}

export function relativeTime(value) {
  if (!value) return null;
  const diff = Date.now() - new Date(value).getTime();
  if (!Number.isFinite(diff)) return null;
  if (diff < 60_000) return 'just now';
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(value).toLocaleDateString();
}

export function formatDate(value) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}
