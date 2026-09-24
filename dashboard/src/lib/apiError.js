/**
 * Every backend failure the dashboard's API clients (src/api/*.js) see
 * arrives in one of two shapes:
 *  - a plain English string (`{ error: "..." }` / `{ detail: "..." }`, or the
 *    Copilot/trend-summary soft-error convention `{ error: "...", error_code: "..." }`)
 *  - a stable {code, params} object (backend/services/common/api_errors.py's
 *    api_error(), used by newer endpoints) - main.py's global HTTPException
 *    handler wraps this as `{ error: { code, params } }` on the wire.
 *
 * apiErrorFromPayload() is the one place that tells these apart, so each
 * api/*.js client's request()/requestSoftError() stays a thin wrapper
 * instead of duplicating the check - see projectsApi.js's `request()` for a
 * caller. translateApiError() then turns either shape into display text
 * through the `errors` namespace (CLAUDE.md: "Translate API errors in the
 * frontend using their error codes" / "Prefer stable API error codes ...
 * over English-only error messages") - a code neither shape recognizes
 * falls back to whatever English text the backend sent, so nothing that
 * used to show a message goes silent.
 */
export function apiErrorFromPayload(payload, fallbackMessage) {
  const raw = payload?.error ?? payload?.detail;
  const code = (raw && typeof raw === 'object' && typeof raw.code === 'string')
    ? raw.code
    : (typeof payload?.error_code === 'string' ? payload.error_code : null);
  const params = (raw && typeof raw === 'object' && raw.params) || {};
  const englishMessage = (typeof raw === 'string' && raw) || fallbackMessage;

  const error = new Error(englishMessage);
  if (code) {
    error.code = code;
    error.params = params;
  }
  return error;
}

/** `t` must be a translator bound to (or including) the `errors` namespace,
 *  e.g. `useTranslation('errors').t`, or `i18nInstance.getFixedT(null, 'errors')`
 *  outside a component. */
export function translateApiError(t, error) {
  if (!error) return t('unknown');
  if (error.code) {
    return t(error.code, { ...error.params, defaultValue: error.message || t('unknown') });
  }
  return error.message || t('unknown');
}
