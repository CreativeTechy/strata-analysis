import { useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';

import { isRtlLocale, isSupportedLocale, DEFAULT_LOCALE } from './locales.js';
import { LOCALE_STORAGE_KEY } from './index.js';

/** Sets <html lang>/<html dir> from the active i18next locale, and exposes a
 *  validated setLocale() that persists the choice (i18next's own
 *  LanguageDetector `caches: ['localStorage']` already does the persistence;
 *  this just also rejects anything outside the supported list before it
 *  reaches i18next, so a corrupted/forged localStorage value can never
 *  change document direction to something unsupported). Mounted once near
 *  the app root - every consumer just reads `useTranslation()`'s own
 *  `i18n.language` for the current value. */
export function useDocumentLocaleSync() {
  const { i18n } = useTranslation();

  useEffect(() => {
    const apply = (lng) => {
      const locale = isSupportedLocale(lng) ? lng : DEFAULT_LOCALE;
      document.documentElement.lang = locale;
      document.documentElement.dir = isRtlLocale(locale) ? 'rtl' : 'ltr';
    };
    apply(i18n.language);
    i18n.on('languageChanged', apply);
    return () => i18n.off('languageChanged', apply);
  }, [i18n]);
}

export function useLocale() {
  const { i18n } = useTranslation();

  const setLocale = useCallback((locale) => {
    if (!isSupportedLocale(locale)) return;
    i18n.changeLanguage(locale);
    if (typeof window !== 'undefined') {
      try {
        window.localStorage.setItem(LOCALE_STORAGE_KEY, locale);
      } catch {
        // Private browsing / storage disabled - the in-memory i18next
        // language change above still applies for this session.
      }
    }
  }, [i18n]);

  return { locale: i18n.language, setLocale, isRtl: isRtlLocale(i18n.language) };
}
