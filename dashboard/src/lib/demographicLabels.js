/**
 * Display labels for the demographic breakdown buckets (region / gender /
 * age_range / segment) - see backend/services/articles/articles_analytics.py's
 * _demographic_sentiment_breakdown. Shared by every chart, legend and
 * evidence chip that shows one, so a bucket reads the same everywhere.
 *
 * Each kind of value translates its own way:
 *   - gender / age_range are closed enums (backend/analysis/labels.py's
 *     VALID_GENDERS / VALID_AGE_RANGES) -> dashboard:demographics.*
 *   - a region that names a country - its canonical English name (what the
 *     backend's normalize_region stores and buckets by), its ISO code, or
 *     its name as Intl knows it in English or Arabic - is mapped to its code
 *     and named in the active locale (Intl.DisplayNames; offline, no catalog
 *     to maintain).
 *   - "other"/"unknown" are app-generated buckets -> dashboard:distributions.bucket.*
 * Everything else (segments, regions that aren't a country) is free model
 * output with no catalog to look up, so useDemographicLabels() has it
 * translated server-side (i18n/useTranslatedLabels.js) and shows a
 * capitalize transform of the raw value until that arrives.
 *
 * Values are cleaned first (cleanLabelValue) the same way the backend's
 * analysis.normalize.clean_label does, so an invisible right-to-left mark
 * around "Lebanon" can't make it miss the country lookup.
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
const COUNTRY_NAMES_BY_CODE = new Map(COUNTRIES.map((country) => [country.code, country.name]));

export function titleCase(value) {
  return String(value || '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

// Compatibility-normalized, invisible format characters (RLM/LRM, bidi
// embeddings, zero-width, BOM) dropped, whitespace collapsed - mirrors the
// backend's analysis.normalize.clean_label.
export function cleanLabelValue(value) {
  return String(value ?? '')
    .normalize('NFKC')
    .replace(/\p{Cf}/gu, '')
    .replace(/\s+/g, ' ')
    .trim();
}

// Spelling-insensitive Arabic: no diacritics/tatweel, one alef form, taa
// marbuta as haa, alef maqsura as yaa - mirrors the backend's
// country_names_ar.normalize_arabic.
function normalizeArabic(text) {
  return text
    .replace(/[ً-ٰٟـ]/g, '')
    .replace(/[أإآٱ]/g, 'ا')
    .replace(/ة/g, 'ه')
    .replace(/ى/g, 'ي');
}

function lookupKey(text) {
  return normalizeArabic(text.toLowerCase());
}

let countryCodesByName = null;

// Every name a country is known by here -> its ISO code: the canonical
// English names, plus what Intl calls it in English and in Arabic. Built
// once, on first use.
function countryCodesByNameMap() {
  if (countryCodesByName) return countryCodesByName;
  countryCodesByName = new Map();
  const add = (name, code) => {
    if (name && name !== code) countryCodesByName.set(lookupKey(cleanLabelValue(name)), code);
  };
  for (const locale of ['en', 'ar']) {
    let names;
    try {
      names = new Intl.DisplayNames([locale], { type: 'region' });
    } catch {
      names = null;
    }
    if (!names) continue;
    for (const { code } of COUNTRIES) add(names.of(code), code);
  }
  // The canonical names win over Intl's variants of the same country.
  for (const { code, name } of COUNTRIES) add(name, code);
  return countryCodesByName;
}

// The ISO code a region value names, or null when it isn't a country.
export function countryCodeFor(value) {
  const text = cleanLabelValue(value);
  if (!text) return null;
  for (const candidate of new Set([text, text.replace(/[.,;:،؛]+$/u, '').trim()])) {
    if (/^[A-Za-z]{2}$/.test(candidate) && COUNTRY_NAMES_BY_CODE.has(candidate.toUpperCase())) {
      return candidate.toUpperCase();
    }
    const code = countryCodesByNameMap().get(lookupKey(candidate));
    if (code) return code;
  }
  return null;
}

function fixedBucket(lower) {
  return lower === 'other' || lower === 'unknown' || GENDER_VALUES.has(lower) || AGE_RANGE_VALUES.has(lower);
}

// True for a value with no catalog/Intl translation - the ones
// useDemographicLabels() sends for server-side translation.
export function isFreeTextValue(value) {
  const text = cleanLabelValue(value);
  if (!text) return false;
  return !fixedBucket(text.toLowerCase()) && !countryCodeFor(text);
}

// `translated` is the server-side translation of a free-text value, when
// one has arrived (see useDemographicLabels()).
export function demographicLabel(t, locale, value, translated = null) {
  const key = cleanLabelValue(value) || 'unknown';
  const lower = key.toLowerCase();
  if (lower === 'other' || lower === 'unknown') return t(`dashboard:distributions.bucket.${lower}`);
  if (GENDER_VALUES.has(lower)) return t(`dashboard:demographics.gender.${lower}`);
  if (AGE_RANGE_VALUES.has(lower)) return t(`dashboard:demographics.ageRange.${lower}`);
  const countryCode = countryCodeFor(key);
  if (countryCode) {
    // English keeps the canonical name rather than Intl's variant of it
    // ("Congo (DRC)" vs "Congo - Kinshasa"), so the English UI is unchanged.
    if (String(locale || '').startsWith('en')) return COUNTRY_NAMES_BY_CODE.get(countryCode);
    return formatRegionName(countryCode, locale) || COUNTRY_NAMES_BY_CODE.get(countryCode);
  }
  return translated || titleCase(key);
}

/**
 * `labelFor(value)` for a set of demographic bucket values in the active
 * locale - demographicLabel() plus server-side translation of whichever of
 * `values` are free text. Pass every value the component will label.
 * `projectId` overrides the LabelProjectContext project the free-text
 * translations are requested for (see useTranslatedLabels()).
 */
export function useDemographicLabels(values, { projectId } = {}) {
  const { t, i18n } = useTranslation('dashboard');
  const locale = i18n.language;
  const freeText = (values || []).filter(isFreeTextValue).map(cleanLabelValue);
  const translatedFor = useTranslatedLabels(freeText, { projectId });
  return useCallback(
    (value) => demographicLabel(t, locale, value, isFreeTextValue(value) ? translatedFor(cleanLabelValue(value)) : null),
    [t, locale, translatedFor],
  );
}
