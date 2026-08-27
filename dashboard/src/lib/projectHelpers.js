// Pure formatting/normalization helpers shared by ProjectsPage's list view
// and its create/edit wizard - no React, so these are unit-testable directly.

export const emptyDraft = {
  name: '',
  status: 'draft',
  description: '',
  location: '',
  location_type: '',
  target_audience: '',
  keywords: [],
  start_date: '',
  end_date: '',
  user_ids: [],
};

export const STATUS_OPTIONS = ['draft', 'active', 'archived'];
export const LOCATION_TYPE_OPTIONS = [
  { value: 'on_site', label: 'On site' },
  { value: 'remote', label: 'Remote' },
  { value: 'hybrid', label: 'Hybrid' },
];
export const PAGE_SIZE = 10;

export function formatDateTime(value) {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed.toLocaleString();
}

export function toDateInput(value) {
  if (!value) return '';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '';
  return parsed.toISOString().slice(0, 10);
}

export function sanitizeTermArray(values) {
  return [
    ...new Set(
      (Array.isArray(values) ? values : [])
        .map((item) => String(item || '').trim())
        .filter(Boolean)
    ),
  ];
}

export function normalizeTermListForCompare(values) {
  return sanitizeTermArray(values).sort();
}

export function normalizeDraftForCompare(value) {
  return {
    name: String(value?.name || '').trim(),
    status: String(value?.status || 'draft').trim().toLowerCase(),
    description: String(value?.description || '').trim(),
    location: String(value?.location || '').trim(),
    location_type: String(value?.location_type || '').trim().toLowerCase(),
    target_audience: String(value?.target_audience || '').trim(),
    usernames: normalizeTermListForCompare(value?.usernames),
    hashtags: normalizeTermListForCompare(value?.hashtags),
    keywords: normalizeTermListForCompare(value?.keywords),
    start_date: String(value?.start_date || ''),
    end_date: String(value?.end_date || ''),
    source_ids: Array.isArray(value?.source_ids)
      ? [...new Set(value.source_ids.map((item) => Number(item)).filter((item) => Number.isFinite(item)))].sort((a, b) => a - b)
      : [],
    user_ids: Array.isArray(value?.user_ids)
      ? [...new Set(value.user_ids.map((item) => Number(item)).filter((item) => Number.isFinite(item)))].sort((a, b) => a - b)
      : [],
    repeat_enabled: Boolean(value?.repeat_enabled),
    repeat_interval_value: Number(value?.repeat_interval_value) || 0,
    repeat_interval_unit: String(value?.repeat_interval_unit || 'minutes').trim().toLowerCase(),
    first_run_at: String(value?.first_run_at || ''),
    repeat_weekdays: normalizeTermListForCompare(value?.repeat_weekdays),
  };
}
