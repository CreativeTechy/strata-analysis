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

/** Same error/response shape as request(), but for a FormData body — request()
 *  always JSON-encodes, which would mangle a multipart upload and also fights
 *  the browser's auto-generated Content-Type boundary if set manually. */
async function requestForm(path, formData) {
  const response = await fetch(`${BASE}${path}`, {
    method: 'POST',
    credentials: 'include',
    body: formData,
  });

  let payload;
  try {
    payload = await response.json();
  } catch {
    payload = null;
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
export const createStudy = (body) => request('/studies', { method: 'POST', body });
export const getStudy = (id) => request(`/studies/${id}`);
export const updateStudy = (id, body) => request(`/studies/${id}`, { method: 'PUT', body });
export const deleteStudy = (id) => request(`/studies/${id}`, { method: 'DELETE' });
/** Paginated findings for one study, highest impact first — powers the Dashboard/Reports pulse card. */
export const listStudyFindings = (id, { limit = 10, offset = 0 } = {}) =>
  request(`/studies/${id}/findings/recent?limit=${limit}&offset=${offset}`);

// --- business profile ------------------------------------------------------
export const getProfile = (id) => request(`/studies/${id}/profile`);
/** Scrapes the website and derives market context — expect this to take a while. */
export const buildProfile = (id, body) => request(`/studies/${id}/profile`, { method: 'POST', body });
export const saveProfile = (id, body) => request(`/studies/${id}/profile`, { method: 'PUT', body });

// --- documents (offline studies) --------------------------------------------
/** `status` moves uploaded -> processing -> processed/failed as chunked
 *  extraction (per page/sheet, text-library or OCR, decided server-side) runs
 *  in the background — see pollDocumentExtraction below. `total_chunks`/
 *  `processed_chunks` are progress while active. `extraction_error` is a
 *  summary of every chunk that failed and is set whenever any did, even if
 *  status ends up 'processed' from the chunks that succeeded — always show it,
 *  a partial failure shouldn't hide behind a plain success pill. Raw extracted
 *  text isn't in this list — use getDocumentText/getDocumentChunks. */
export const listDocuments = (id) => request(`/studies/${id}/documents`);
export const uploadDocuments = (id, files) => {
  const formData = new FormData();
  for (const file of files) formData.append('files', file);
  return requestForm(`/studies/${id}/documents`, formData);
};
export const deleteDocument = (documentId) => request(`/documents/${documentId}`, { method: 'DELETE' });
export const getDocumentText = (documentId) => request(`/documents/${documentId}/text`);
/** Per-page/sheet detail behind a document's rolled-up status — which part
 *  failed and why, not just that something did. */
export const getDocumentChunks = (documentId) => request(`/documents/${documentId}/chunks`);

// --- document articles (candidates split out of extracted text) -----------
/** A document's extracted text is split into one or more candidate "articles"
 *  in the background — `articles_status` on the document (pending ->
 *  generating -> ready/failed/skipped) tracks that, same polling shape as
 *  extraction. Each candidate starts 'pending'; approving materializes it
 *  into a real article (usable by the existing analysis pipeline), rejecting
 *  just marks it — see pollArticleCandidates below. */
export const listDocumentArticles = (id) => request(`/studies/${id}/document-articles`);
export const setDocumentArticleStatus = (candidateId, status) =>
  request(`/document-articles/${candidateId}/status`, { method: 'POST', body: { status } });
export const approveAllDocumentArticles = (id) =>
  request(`/studies/${id}/document-articles/approve-all`, { method: 'POST' });

// --- competitors -----------------------------------------------------------
/** Queues discovery as a background job; returns { run_id, status } immediately.
 *  Poll getDiscoveryStatus(id, run_id) until status is 'success' or 'failed'. */
export const discoverCompetitors = (id, body) => request(`/studies/${id}/discover`, { method: 'POST', body });
export const getDiscoveryStatus = (id, runId) => request(`/studies/${id}/discover/${runId}`);
/** Phase 3: finds channels for every tracked competitor that doesn't have one yet.
 *  Same queued/poll shape as discoverCompetitors — reuse pollDiscoveryRun on the result. */
export const discoverTrackedAccounts = (id) => request(`/studies/${id}/discover-accounts`, { method: 'POST' });
export const listCompetitors = (id) => request(`/studies/${id}/competitors`);
export const addCompetitor = (id, body) => request(`/studies/${id}/competitors`, { method: 'POST', body });
/** Creates a competitor and validates+links its sources in one call — the
 *  manual-first path, as opposed to addCompetitor()+addAccount() one at a time. */
export const addCompetitorManual = (id, body) =>
  request(`/studies/${id}/competitors/manual`, { method: 'POST', body });
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
/** Offline studies: names the competitors an offline study's approved
 *  document articles are actually about, tracks them, then runs the same
 *  finding generation `analyze()` triggers for an online study. */
export const analyzeDocuments = (id) => request(`/studies/${id}/analyze-documents`, { method: 'POST' });
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

/** The source kinds a manually-added competitor account can be — the same
 *  scrapeable vocabulary as the project wizard's SOURCE_TYPE_OPTIONS
 *  (dashboard/src/components/ProjectsPage.jsx) and backend
 *  config.KNOWN_SOURCE_TYPES; mirrors backend PLATFORM_SOURCE_TYPE
 *  (services/competitors/competitors_store.py). */
export const SOURCE_KIND_OPTIONS = [
  { value: 'rss', label: 'RSS' },
  { value: 'web', label: 'Web' },
  { value: 'social', label: 'Social' },
  { value: 'hashtag', label: 'Hashtag' },
  { value: 'keyword', label: 'Keyword' },
  { value: 'username', label: 'X Account' },
  { value: 'reddit', label: 'Reddit' },
  { value: 'telegram', label: 'Telegram' },
];

/** These take a bare name/term instead of a URL — the source row hides its
 *  URL field and derives the real URL server-side. */
export const TERM_SOURCE_TYPES = new Set(['hashtag', 'keyword', 'username']);

export const TERM_SOURCE_PLACEHOLDERS = {
  hashtag: 'Hashtag, without # (e.g. EVSummit)',
  username: 'X account, without @ (e.g. elonmusk)',
  keyword: 'Keyword or phrase (e.g. electric vehicles)',
};

export const PLATFORM_LABELS = Object.fromEntries(
  SOURCE_KIND_OPTIONS.map((option) => [option.value, option.label]),
);

/** Shape-only check mirroring the backend's normalize_source_url — enough to
 *  catch an obviously-broken entry before it round-trips to the server. */
export function isPlausibleUrl(value) {
  const text = String(value || '').trim();
  if (!text) return false;
  const withScheme = /^https?:\/\//i.test(text) ? text : `https://${text}`;
  try {
    const { hostname } = new URL(withScheme);
    return hostname.includes('.');
  } catch {
    return false;
  }
}

const DISCOVERY_POLL_MS = 2500;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Discovery runs as a backend job that can take minutes (LLM call + live web
 *  corroboration + per-competitor account lookups), so it's queued rather than
 *  awaited directly - poll until it reaches a terminal status. Shared by
 *  onboarding and the workspace, which both trigger discovery.
 *  `onUpdate`, if given, is called with the run on every poll (not just the
 *  terminal one) so a caller can render its live `run.logs` as they arrive. */
export async function pollDiscoveryRun(studyId, runId, onUpdate) {
  for (;;) {
    const { run } = await getDiscoveryStatus(studyId, runId);
    if (onUpdate) onUpdate(run);
    if (run.status === 'success' || run.status === 'failed') return run;
    await sleep(DISCOVERY_POLL_MS);
  }
}

const DOCUMENT_ACTIVE_STATUSES = new Set(['uploaded', 'processing']);

/** Extraction has no separate run object like discovery does — the document
 *  row's own `status` is the only progress signal, so this just re-lists until
 *  none of the given document ids are still uploaded/processing.
 *  `onUpdate` is called with the full current list on every poll. */
export async function pollDocumentExtraction(studyId, documentIds, onUpdate) {
  const pending = new Set(documentIds);
  for (;;) {
    const { documents } = await listDocuments(studyId);
    if (onUpdate) onUpdate(documents);
    const stillActive = documents.some(
      (document) => pending.has(document.id) && DOCUMENT_ACTIVE_STATUSES.has(document.status),
    );
    if (!stillActive) return documents;
    await sleep(DISCOVERY_POLL_MS);
  }
}

const ARTICLES_ACTIVE_STATUSES = new Set(['pending', 'generating']);

/** Candidate-article generation chains after extraction in the same
 *  background task, so it can still be running after pollDocumentExtraction
 *  above has already returned (extraction's own status left 'processing').
 *  Polls a document's `articles_status` instead — same shape, different
 *  field. Terminal values are 'ready'/'failed'/'skipped', so this always
 *  converges even for documents whose extraction failed outright. */
export async function pollArticleCandidates(studyId, documentIds, onUpdate) {
  const pending = new Set(documentIds);
  for (;;) {
    const { documents } = await listDocuments(studyId);
    if (onUpdate) onUpdate(documents);
    const stillActive = documents.some(
      (document) => pending.has(document.id) && ARTICLES_ACTIVE_STATUSES.has(document.articles_status),
    );
    if (!stillActive) return documents;
    await sleep(DISCOVERY_POLL_MS);
  }
}

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
