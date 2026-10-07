/**
 * Display labels for the demographic breakdown buckets (region / gender /
 * age_range / segment) - see backend/services/articles/articles_analytics.py's
 * _demographic_sentiment_breakdown. Shared by every chart, legend and
 * evidence chip that shows one, so a bucket reads the same everywhere.
 *
 * Each kind of value translates its own way:
 *   - gender / age_range are closed enums (backend/analysis/labels.py's
 *     VALID_GENDERS / VALID_AGE_RANGES) -> dashboard:demographics.*
 *   - region is canonicalized to a country name from the same ISO list as
 *     constants/countries.js where it can be, so a country name is mapped
 *     back to its code and named by Intl.DisplayNames (offline, no catalog
 *     to maintain).
 *   - "other"/"unknown" are app-generated buckets -> dashboard:distributions.bucket.*
 * Everything else (segments, regions that aren't a country) is free model
 * output with no catalog to look up, so useDemographicLabels() has it
 * translated server-side (i18n/useTranslatedLabels.js) and shows a
 * capitalize transform of the raw value until that arrives.
 *
 * Bucket values never collide across dimensions, so callers don't need to
 * say which dimension a value came from.
 */
import { useCallback } from 'react';
import { useTranslation } from 'react-i18next';

import { COUNTRIES } from '../constants/countries.js';
import { useTranslatedLabels } from '../i18n/useTranslatedLabels.js';
import { formatRegionName } from './i18nFormat.js';

const GENDER_VALUES = new Set(['male', 'female']);
const AGE_RANGE_VALUES = new Set(['under_18', '18-24', '25-34', '35-44', '45-54', '55-64', '65_plus']);
const COUNTRY_CODES_BY_NAME = new Map(COUNTRIES.map((country) => [country.name.toLowerCase(), country.code]));

export function titleCase(value) {
  return String(value || '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

// True for a value with no catalog/Intl translation - the ones
// useDemographicLabels() sends for server-side translation.
export function isFreeTextValue(value) {
  const lower = String(value || 'unknown').trim().toLowerCase();
  return !(lower === 'other' || lower === 'unknown' || GENDER_VALUES.has(lower)
    || AGE_RANGE_VALUES.has(lower) || COUNTRY_CODES_BY_NAME.has(lower));
}

// `translated` is the server-side translation of a free-text value, when
// one has arrived (see useDemographicLabels()).
export function demographicLabel(t, locale, value, translated = null) {
  const key = String(value || 'unknown');
  const lower = key.toLowerCase();
  if (lower === 'other' || lower === 'unknown') return t(`dashboard:distributions.bucket.${lower}`);
  if (GENDER_VALUES.has(lower)) return t(`dashboard:demographics.gender.${lower}`);
  if (AGE_RANGE_VALUES.has(lower)) return t(`dashboard:demographics.ageRange.${lower}`);
  const countryCode = COUNTRY_CODES_BY_NAME.get(lower);
  // English keeps the stored canonical name rather than Intl's variant of it
  // ("Congo (DRC)" vs "Congo - Kinshasa"), so the English UI is unchanged.
  if (countryCode && !String(locale || '').startsWith('en')) {
    return formatRegionName(countryCode, locale) || key;
  }
  return translated || titleCase(key);
}

/**
 * `labelFor(value)` for a set of demographic bucket values in the active
 * locale - demographicLabel() plus server-side translation of whichever of
 * `values` are free text. Pass every value the component will label.
 */
export function useDemographicLabels(values) {
  const { t, i18n } = useTranslation('dashboard');
  const locale = i18n.language;
  const translatedFor = useTranslatedLabels((values || []).filter(isFreeTextValue));
  return useCallback(
    (value) => demographicLabel(t, locale, value, isFreeTextValue(value) ? translatedFor(String(value)) : null),
    [t, locale, translatedFor],
  );
}
