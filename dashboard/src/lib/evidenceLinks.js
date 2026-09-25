/**
 * Evidence links: every dashboard/report number or chart selection opens the
 * Articles page on the articles it counted, with the project and the scope
 * it was counted in (a date period, or one analysis run) carried along.
 *
 * The backend resolves these params with the same rows and bucketing the
 * dashboard aggregates over (backend/services/intelligence/evidence_links.py),
 * so the Articles total matches the number that was clicked.
 */

// Chart dimensions a selection can carry, beyond the Articles page's own
// sentiment filter. Order is the order their chips show in.
export const EVIDENCE_DIMENSIONS = ['platform', 'language', 'region', 'gender', 'age_range', 'segment', 'trust', 'emotion', 'date'];
export const EVIDENCE_SCOPE_KEYS = ['period', 'run_id'];
export const EVIDENCE_PERIODS = ['7d', '30d', 'all'];

/**
 * `/articles?...` for one selection. `runId` wins over `period`, same as the
 * dashboard's own scope (its run tab replaces the date tabs). `filters` keys
 * are EVIDENCE_DIMENSIONS plus `sentiment`; blank values are dropped.
 */
export function articlesEvidencePath({ projectId, period, runId, filters = {} } = {}) {
  const params = new URLSearchParams();
  if (projectId != null && projectId !== '') params.set('project_id', String(projectId));
  if (runId) params.set('run_id', String(runId));
  else if (period) params.set('period', String(period));
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value));
  });
  const query = params.toString();
  return query ? `/articles?${query}` : '/articles';
}

/** The evidence scope + dimensions present in a URLSearchParams, as a plain object. */
export function readEvidenceParams(searchParams) {
  const evidence = {};
  [...EVIDENCE_SCOPE_KEYS, ...EVIDENCE_DIMENSIONS].forEach((key) => {
    const value = (searchParams.get(key) || '').trim();
    if (value) evidence[key] = value;
  });
  if (evidence.period && !EVIDENCE_PERIODS.includes(evidence.period)) delete evidence.period;
  // A run scope replaces the period rather than narrowing it.
  if (evidence.run_id) delete evidence.period;
  return evidence;
}

/** Recharts slice/legend "other" folds the long tail together - there is no single bucket to open. */
export function isLinkableBucket(value) {
  return value !== undefined && value !== null && value !== '' && value !== 'other';
}
