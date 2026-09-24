import { useTranslation } from 'react-i18next';
import { Languages } from 'lucide-react';

import { useLocale } from '../i18n/useLocale.js';
import { SUPPORTED_LOCALES, LOCALE_NATIVE_NAMES } from '../i18n/locales.js';

/** English/Arabic switch, shown on the login page and in the authenticated
 *  shell (CLAUDE.md: "Add a clear English/العربية switch on login and in the
 *  authenticated shell"). A plain <select> rather than a custom listbox -
 *  it's two options, and a native control gets keyboard/screen-reader
 *  support and RTL mirroring for free. */
export default function LanguageSwitcher({ className = '' }) {
  const { t } = useTranslation('auth');
  const { locale, setLocale } = useLocale();

  return (
    <label className={`language-switcher ${className}`.trim()}>
      <Languages size={16} aria-hidden="true" />
      <span className="sr-only">{t('languageSwitcher.label')}</span>
      <select
        className="language-switcher-select"
        value={locale}
        onChange={(e) => setLocale(e.target.value)}
        aria-label={t('languageSwitcher.label')}
      >
        {SUPPORTED_LOCALES.map((code) => (
          <option key={code} value={code} lang={code}>
            {LOCALE_NATIVE_NAMES[code]}
          </option>
        ))}
      </select>
    </label>
  );
}
