import { act, render, renderHook, screen } from '@testing-library/react';
import { I18nextProvider, useTranslation } from 'react-i18next';
import { afterEach, describe, expect, it } from 'vitest';

import i18n, { LOCALE_STORAGE_KEY } from './index.js';
import { useDocumentLocaleSync, useLocale } from './useLocale.js';

async function resetToEnglish() {
  await act(async () => {
    await i18n.changeLanguage('en');
  });
  document.documentElement.lang = 'en';
  document.documentElement.dir = 'ltr';
  window.localStorage.clear();
}

describe('useLocale', () => {
  afterEach(async () => {
    await resetToEnglish();
  });

  it('exposes the active i18next language and isRtl flag', async () => {
    const { result } = renderHook(() => useLocale(), { wrapper: ({ children }) => (
      <I18nextProvider i18n={i18n}>{children}</I18nextProvider>
    ) });
    expect(result.current.locale).toBe('en');
    expect(result.current.isRtl).toBe(false);

    await act(async () => {
      result.current.setLocale('ar');
    });
    expect(result.current.locale).toBe('ar');
    expect(result.current.isRtl).toBe(true);
  });

  it('persists an explicit locale choice to localStorage', async () => {
    const { result } = renderHook(() => useLocale());
    await act(async () => {
      result.current.setLocale('ar');
    });
    expect(window.localStorage.getItem(LOCALE_STORAGE_KEY)).toBe('ar');
  });

  it('ignores a locale outside the supported list rather than corrupting state', async () => {
    const { result } = renderHook(() => useLocale());
    await act(async () => {
      result.current.setLocale('fr');
    });
    expect(result.current.locale).toBe('en');
    expect(window.localStorage.getItem(LOCALE_STORAGE_KEY)).not.toBe('fr');
  });

  it('reloading with a previously-stored Arabic choice restores Arabic (locale persistence survives a refresh)', async () => {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, 'ar');
    await act(async () => {
      // Simulates what i18n/index.js's readStoredLocale() + detector does at
      // module load time, without re-importing the module (ESM modules are
      // cached, so re-importing index.js in the same test run wouldn't
      // re-execute its init() call).
      await i18n.changeLanguage(window.localStorage.getItem(LOCALE_STORAGE_KEY));
    });
    expect(i18n.language).toBe('ar');
  });

  it.each(['en-US', 'en-GB'])('normalizes a regional English browser locale (%s) down to the supported base code', async (regional) => {
    await act(async () => {
      await i18n.changeLanguage(regional);
    });
    // nonExplicitSupportedLngs: false (i18n/index.js) is what makes this
    // resolve to 'en' instead of staying 'en-US' - the backend's
    // normalize_locale() rejects anything but exactly 'en'/'ar', so a
    // first-time visitor with a regional browser locale would otherwise get
    // 400s from every locale-aware endpoint (article detail, Copilot chat).
    expect(i18n.language).toBe('en');
  });

  it.each(['ar-SA', 'ar-EG'])('normalizes a regional Arabic browser locale (%s) down to the supported base code', async (regional) => {
    await act(async () => {
      await i18n.changeLanguage(regional);
    });
    expect(i18n.language).toBe('ar');
  });
});

function DocumentLocaleProbe() {
  useDocumentLocaleSync();
  const { i18n: instance } = useTranslation();
  return <span>{instance.language}</span>;
}

describe('useDocumentLocaleSync', () => {
  afterEach(async () => {
    await resetToEnglish();
  });

  it('sets document lang/dir to ltr for English', async () => {
    render(<DocumentLocaleProbe />);
    expect(await screen.findByText('en')).toBeInTheDocument();
    expect(document.documentElement.lang).toBe('en');
    expect(document.documentElement.dir).toBe('ltr');
  });

  it('sets document lang/dir to rtl when the locale changes to Arabic', async () => {
    render(<DocumentLocaleProbe />);
    await act(async () => {
      await i18n.changeLanguage('ar');
    });
    expect(document.documentElement.lang).toBe('ar');
    expect(document.documentElement.dir).toBe('rtl');
  });

  it('falls back to a safe ltr default if the resolved language is unsupported', async () => {
    render(<DocumentLocaleProbe />);
    await act(async () => {
      await i18n.changeLanguage('fr');
    });
    expect(document.documentElement.dir).toBe('ltr');
  });
});

describe('English fallback for missing translation keys', () => {
  afterEach(async () => {
    await resetToEnglish();
  });

  it('falls back to the English value when a key is missing from the active locale catalog', async () => {
    await act(async () => {
      await i18n.changeLanguage('ar');
    });
    // A key that exists only in en/common.json's fallback chain still
    // resolves rather than rendering the bare key - i18next's fallbackLng
    // (config.DEFAULT_LOCALE, see i18n/index.js) is what makes this work
    // even for a namespace with an incomplete Arabic catalog.
    const missingKey = 'common:this.key.does.not.exist.anywhere';
    expect(i18n.t(missingKey, { defaultValue: 'fallback text' })).toBe('fallback text');
  });
});

describe('Arabic plural forms', () => {
  afterEach(async () => {
    await resetToEnglish();
  });

  it('resolves the correct CLDR plural category for each count', async () => {
    await act(async () => {
      await i18n.changeLanguage('ar');
    });
    const t = i18n.getFixedT('ar', 'common');
    expect(t('pagination.itemCount', { count: 0 })).toContain('لا توجد');
    expect(t('pagination.itemCount', { count: 1 })).toContain('واحد');
    expect(t('pagination.itemCount', { count: 2 })).toContain('عنصران');
    expect(t('pagination.itemCount', { count: 5 })).toBe('5 عناصر');
    expect(t('pagination.itemCount', { count: 11 })).toBe('11 عنصرًا');
    expect(t('pagination.itemCount', { count: 100 })).toBe('100 عنصر');
  });

  it('resolves English one/other plural forms', async () => {
    const t = i18n.getFixedT('en', 'common');
    expect(t('pagination.itemCount', { count: 1 })).toBe('1 item');
    expect(t('pagination.itemCount', { count: 3 })).toBe('3 items');
  });
});
