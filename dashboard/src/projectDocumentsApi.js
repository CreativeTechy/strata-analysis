/**
 * Client for the offline (document-upload) opinion-monitor project API.
 *
 * Mirrors competitorApi.js's document-related exports (same endpoint shapes,
 * same `{ error, detail }` failure convention), pointed at `/api/projects`
 * instead of `/api/competitor/studies` - see backend/services/projects/
 * project_documents_api.py. The one real difference: each candidate here
 * carries `article_analysis_status`/`article_analysis_error` (the
 * materialized article's own sentiment-analysis progress), since approving a
 * candidate queues real analysis rather than just becoming raw evidence for a
 * later "generate findings" pass.
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
    const message = payload?.detail || payload?.error || `Request failed (${response.status})`;
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return payload ?? {};
}

// --- documents (offline projects) ------------------------------------------
/** `status` moves uploaded -> processing -> processed/failed as chunked
 *  extraction (per page/sheet, text-library or OCR, decided server-side) runs
 *  in the background — see pollDocumentExtraction below. `total_chunks`/
 *  `processed_chunks` are progress while active. `extraction_error` is a
 *  summary of every chunk that failed and is set whenever any did, even if
 *  status ends up 'processed' from the chunks that succeeded — always show it,
 *  a partial failure shouldn't hide behind a plain success pill. Raw extracted
 *  text isn't in this list — use getDocumentText/getDocumentChunks. */
export const listDocuments = (projectId) => request(`/${projectId}/documents`);
export const uploadDocuments = (projectId, files) => {
  const formData = new FormData();
  for (const file of files) formData.append('files', file);
  return requestForm(`/${projectId}/documents`, formData);
};
export const deleteDocument = (documentId) => request(`/documents/${documentId}`, { method: 'DELETE' });
export const getDocumentText = (documentId) => request(`/documents/${documentId}/text`);
export const getDocumentChunks = (documentId) => request(`/documents/${documentId}/chunks`);

// --- document articles (candidates split out of extracted text) -----------
/** A document's extracted text is split into one or more candidate "articles"
 *  in the background — `articles_status` on the document (pending ->
 *  generating -> ready/failed/skipped) tracks that, same polling shape as
 *  extraction. Each candidate starts 'pending'; approving materializes it
 *  into a real article and queues sentiment analysis for it
 *  (`article_analysis_status`: pending -> processing -> success/failed),
 *  rejecting just marks it — see pollArticleCandidates/pollArticleAnalysis. */
export const listDocumentArticles = (projectId) => request(`/${projectId}/document-articles`);
export const setDocumentArticleStatus = (candidateId, status) =>
  request(`/document-articles/${candidateId}/status`, { method: 'POST', body: { status } });
export const approveAllDocumentArticles = (projectId) =>
  request(`/${projectId}/document-articles/approve-all`, { method: 'POST' });
/** Starts a tracked analysis run over this project's approved articles that
 *  haven't been analyzed successfully — a manual retry for whichever ones
 *  failed. Returns { run_id }, visible on the Analysis Runs page. */
export const reanalyzeDocumentArticles = (projectId) =>
  request(`/${projectId}/document-articles/reanalyze`, { method: 'POST' });

const POLL_MS = 2500;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

const DOCUMENT_ACTIVE_STATUSES = new Set(['uploaded', 'processing']);

/** Extraction has no separate run object — the document row's own `status` is
 *  the only progress signal, so this just re-lists until none of the given
 *  document ids are still uploaded/processing. `onUpdate` is called with the
 *  full current list on every poll. */
export async function pollDocumentExtraction(projectId, documentIds, onUpdate) {
  const pending = new Set(documentIds);
  for (;;) {
    const { documents } = await listDocuments(projectId);
    if (onUpdate) onUpdate(documents);
    const stillActive = documents.some(
      (document) => pending.has(document.id) && DOCUMENT_ACTIVE_STATUSES.has(document.status),
    );
    if (!stillActive) return documents;
    await sleep(POLL_MS);
  }
}

const ARTICLES_ACTIVE_STATUSES = new Set(['pending', 'generating']);

/** Candidate-article generation chains after extraction in the same
 *  background task, so it can still be running after pollDocumentExtraction
 *  above has already returned. Polls a document's `articles_status` instead —
 *  same shape, different field. Terminal values are 'ready'/'failed'/
 *  'skipped', so this always converges even for documents whose extraction
 *  failed outright. */
export async function pollArticleCandidates(projectId, documentIds, onUpdate) {
  const pending = new Set(documentIds);
  for (;;) {
    const { documents } = await listDocuments(projectId);
    if (onUpdate) onUpdate(documents);
    const stillActive = documents.some(
      (document) => pending.has(document.id) && ARTICLES_ACTIVE_STATUSES.has(document.articles_status),
    );
    if (!stillActive) return documents;
    await sleep(POLL_MS);
  }
}

const ANALYSIS_ACTIVE_STATUSES = new Set(['pending', 'processing']);

/** Polls the candidate list until no approved candidate's materialized
 *  article is still pending/processing analysis. `onUpdate` receives the full
 *  candidate list (each with `article_analysis_status`) on every poll. */
export async function pollArticleAnalysis(projectId, onUpdate) {
  for (;;) {
    const { articles } = await listDocumentArticles(projectId);
    if (onUpdate) onUpdate(articles);
    const stillActive = articles.some(
      (candidate) => candidate.status === 'approved' && ANALYSIS_ACTIVE_STATUSES.has(candidate.article_analysis_status),
    );
    if (!stillActive) return articles;
    await sleep(POLL_MS);
  }
}
