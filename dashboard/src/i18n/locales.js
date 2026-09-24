/**
 * The closed set of interface locales this app supports, and their native
 * display names for the language switcher. Adding a language means adding an
 * entry here (and its namespace files under ./locales/<code>/) - nothing
 * else in the i18n setup is locale-count-specific.
 *
 * Mirrors backend/config.py's SUPPORTED_LOCALES - kept as two independent,
 * hand-written lists rather than one shared file because the frontend
 * bundle and the Python backend never share source, but they must agree on
 * the same codes (see backend/services/i18n/locales.py for the AI-output
 * side of this same contract).
 */
export const SUPPORTED_LOCALES = ['en', 'ar'];
export const DEFAULT_LOCALE = 'en';

export const LOCALE_NATIVE_NAMES = {
  en: 'English',
  ar: 'العربية',
};

export const RTL_LOCALES = new Set(['ar']);

export function isRtlLocale(locale) {
  return RTL_LOCALES.has(locale);
}

export function isSupportedLocale(value) {
  return SUPPORTED_LOCALES.includes(value);
}
