import { useTranslation } from 'react-i18next';
import { Languages } from 'lucide-react';

import { useLocale } from '../i18n/useLocale.js';
import { SUPPORTED_LOCALES, LOCALE_NATIVE_NAMES, isRtlLocale } from '../i18n/locales.js';

/** English/Arabic switch, shown on the login page and in the authenticated
 *  shell (CLAUDE.md: "Add a clear English/العربية switch on login and in the
 *  authenticated shell"). A pill-shaped button group rather than a <select> -
 *  both options are always visible so the active language is obvious at a
 *  glance without opening a dropdown first. */
export default function LanguageSwitcher({ className = '' }) {
  const { t } = useTranslation('auth');
  const { locale, setLocale } = useLocale();

  return (
    <div className={`language-switcher ${className}`.trim()} role="group" aria-label={t('languageSwitcher.label')}>
      <Languages size={14} aria-hidden="true" className="language-switcher-icon" />
      {SUPPORTED_LOCALES.map((code) => (
        <button
          key={code}
          type="button"
          lang={code}
          dir={isRtlLocale(code) ? 'rtl' : 'ltr'}
          className={`language-switcher-option${code === locale ? ' is-active' : ''}`}
          aria-pressed={code === locale}
          onClick={() => setLocale(code)}
        >
          {LOCALE_NATIVE_NAMES[code]}
        </button>
      ))}
    </div>
  );
}
