/**
 * Client for the display-label translation endpoint
 * (backend/services/i18n/label_translation.py). Only ever used through
 * i18n/useTranslatedLabels.js, which batches and caches these calls.
 */

export async function translateLabels(projectId, locale, values, { signal } = {}) {
  const response = await fetch('/api/i18n/labels', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_id: projectId, locale, values }),
    signal,
  });
  if (!response.ok) throw new Error(`Label translation failed (${response.status})`);
  const payload = await response.json();
  return payload?.labels && typeof payload.labels === 'object' ? payload.labels : {};
}
