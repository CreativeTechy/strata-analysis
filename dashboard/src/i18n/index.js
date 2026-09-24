/**
 * i18next setup for the dashboard.
 *
 * Every translation catalog below is a static import, not a runtime fetch -
 * i18next-http-backend (or any backend that loads JSON over the network) is
 * deliberately not used here. This app has to stay offline-first (see
 * CLAUDE.md: "nothing fetches from the network except the configured LLM"),
 * so every locale's every namespace is bundled into the JS build exactly
 * like any other imported module, resolved once at build time.
 *
 * Namespaces are organized by feature area rather than one large file, so a
 * page only needs to reason about its own catalog (see useTranslation('ns')
 * call sites) while still sharing `common` for cross-cutting strings
 * (buttons, statuses, empty states, dialogs, a11y labels).
 */
import i18n from 'i18next';
import LanguageDetector from 'i18next-browser-languagedetector';
import { initReactI18next } from 'react-i18next';

import { DEFAULT_LOCALE, SUPPORTED_LOCALES } from './locales.js';

import enCommon from './locales/en/common.json';
import enAuth from './locales/en/auth.json';
import enNav from './locales/en/nav.json';
import enDashboard from './locales/en/dashboard.json';
import enProjects from './locales/en/projects.json';
import enDocuments from './locales/en/documents.json';
import enArticles from './locales/en/articles.json';
import enAnalysis from './locales/en/analysis.json';
import enReports from './locales/en/reports.json';
import enSources from './locales/en/sources.json';
import enCompetitors from './locales/en/competitors.json';
import enCopilot from './locales/en/copilot.json';
import enAdmin from './locales/en/admin.json';
import enErrors from './locales/en/errors.json';

import arCommon from './locales/ar/common.json';
import arAuth from './locales/ar/auth.json';
import arNav from './locales/ar/nav.json';
import arDashboard from './locales/ar/dashboard.json';
import arProjects from './locales/ar/projects.json';
import arDocuments from './locales/ar/documents.json';
import arArticles from './locales/ar/articles.json';
import arAnalysis from './locales/ar/analysis.json';
import arReports from './locales/ar/reports.json';
import arSources from './locales/ar/sources.json';
import arCompetitors from './locales/ar/competitors.json';
import arCopilot from './locales/ar/copilot.json';
import arAdmin from './locales/ar/admin.json';
import arErrors from './locales/ar/errors.json';

export const LOCALE_STORAGE_KEY = 'strata.locale';

export const NAMESPACES = [
  'common', 'auth', 'nav', 'dashboard', 'projects', 'documents', 'articles',
  'analysis', 'reports', 'sources', 'competitors', 'copilot', 'admin', 'errors',
];

const resources = {
  en: {
    common: enCommon, auth: enAuth, nav: enNav, dashboard: enDashboard, projects: enProjects,
    documents: enDocuments, articles: enArticles, analysis: enAnalysis, reports: enReports,
    sources: enSources, competitors: enCompetitors, copilot: enCopilot, admin: enAdmin, errors: enErrors,
  },
  ar: {
    common: arCommon, auth: arAuth, nav: arNav, dashboard: arDashboard, projects: arProjects,
    documents: arDocuments, articles: arArticles, analysis: arAnalysis, reports: arReports,
    sources: arSources, competitors: arCompetitors, copilot: arCopilot, admin: arAdmin, errors: arErrors,
  },
};

function readStoredLocale() {
  if (typeof window === 'undefined') return null;
  try {
    const stored = window.localStorage.getItem(LOCALE_STORAGE_KEY);
    return SUPPORTED_LOCALES.includes(stored) ? stored : null;
  } catch {
    return null;
  }
}

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources,
    ns: NAMESPACES,
    defaultNS: 'common',
    fallbackLng: DEFAULT_LOCALE,
    supportedLngs: SUPPORTED_LOCALES,
    nonExplicitSupportedLngs: true,
    lng: readStoredLocale() || undefined,
    detection: {
      // localStorage first (an explicit prior choice always wins), then the
      // browser's own language - never a network geo-IP lookup or similar,
      // consistent with this app staying offline-first end to end.
      order: ['localStorage', 'navigator'],
      lookupLocalStorage: LOCALE_STORAGE_KEY,
      caches: ['localStorage'],
    },
    interpolation: {
      // React already escapes interpolated values when rendering JSX text,
      // so i18next's own HTML-escaping would double-escape entities (turning
      // "&" into "&amp;amp;" wherever a translation interpolates one).
      escapeValue: false,
    },
    returnEmptyString: false,
  });

export default i18n;
