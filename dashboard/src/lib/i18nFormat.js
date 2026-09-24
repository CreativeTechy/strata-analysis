/**
 * Locale-aware date/time/number/percentage/language-name formatting,
 * centralized so components stop calling toLocaleDateString()/toLocaleString()
 * ad hoc with an implicit (browser-default) locale - see the ~20 call sites
 * this replaces across ArticlesPage, DashboardOverview, ProjectDetailPage,
 * TopicDetailPage, etc. Every formatter takes the active i18next locale
 * explicitly (from useTranslation()'s `i18n.language`) rather than reading
 * global state itself, so it stays a plain function, easy to unit test and
 * to call from outside a component (e.g. inside a non-hook helper).
 *
 * These only affect *display* - the underlying stored value (an ISO date
 * string, a raw number) is never mutated, so switching locale never touches
 * canonical data, filters, or anything sent back to the API.
 */
import { DEFAULT_LOCALE } from '../i18n/locales.js';

// Intl needs BCP-47 tags, not i18next's bare locale codes - both current
// locales resolve to a real region so date/number conventions are Gregorian
// and Arabic-Indic-digit-free by default (western Arabic numerals, which is
// what MSA news/UI text overwhelmingly uses).
const INTL_LOCALE_TAGS = {
  en: 'en-US',
  ar: 'ar-SA-u-nu-latn',
};

function resolveIntlLocale(locale) {
  return INTL_LOCALE_TAGS[locale] || INTL_LOCALE_TAGS[DEFAULT_LOCALE];
}

function toDate(value) {
  if (value instanceof Date) return value;
  if (value == null || value === '') return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDate(value, locale, options = { year: 'numeric', month: 'short', day: 'numeric' }) {
  const date = toDate(value);
  if (!date) return '';
  return new Intl.DateTimeFormat(resolveIntlLocale(locale), options).format(date);
}

export function formatDateTime(value, locale, options = {
  year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
}) {
  const date = toDate(value);
  if (!date) return '';
  return new Intl.DateTimeFormat(resolveIntlLocale(locale), options).format(date);
}

export function formatTime(value, locale, options = { hour: 'numeric', minute: '2-digit' }) {
  const date = toDate(value);
  if (!date) return '';
  return new Intl.DateTimeFormat(resolveIntlLocale(locale), options).format(date);
}

export function formatRelativeTime(value, locale) {
  const date = toDate(value);
  if (!date) return '';
  const diffSeconds = (date.getTime() - Date.now()) / 1000;
  const rtf = new Intl.RelativeTimeFormat(resolveIntlLocale(locale), { numeric: 'auto' });
  const thresholds = [
    ['year', 60 * 60 * 24 * 365],
    ['month', 60 * 60 * 24 * 30],
    ['day', 60 * 60 * 24],
    ['hour', 60 * 60],
    ['minute', 60],
  ];
  for (const [unit, seconds] of thresholds) {
    if (Math.abs(diffSeconds) >= seconds) {
      return rtf.format(Math.round(diffSeconds / seconds), unit);
    }
  }
  return rtf.format(Math.round(diffSeconds), 'second');
}

export function formatNumber(value, locale, options) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '';
  return new Intl.NumberFormat(resolveIntlLocale(locale), options).format(number);
}

/** `value` is a plain ratio (0-1) unless `alreadyWhole` is set (e.g. an
 *  already-computed "62" meaning 62%, as several call sites currently
 *  compute by hand via Math.round((count/total)*100)). */
export function formatPercent(value, locale, { alreadyWhole = false, maximumFractionDigits = 0 } = {}) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '';
  const ratio = alreadyWhole ? number / 100 : number;
  return new Intl.NumberFormat(resolveIntlLocale(locale), {
    style: 'percent',
    maximumFractionDigits,
  }).format(ratio);
}

export function formatLanguageName(languageCode, locale) {
  if (!languageCode) return '';
  try {
    return new Intl.DisplayNames([resolveIntlLocale(locale)], { type: 'language' }).of(languageCode);
  } catch {
    return languageCode;
  }
}
