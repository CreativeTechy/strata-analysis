import { describe, expect, it } from 'vitest';

import { SUPPORTED_LOCALES } from './locales.js';

/**
 * Development/CI gate: every translation key that exists in one locale's
 * namespace file must exist in every other locale's same namespace file.
 * Runs as part of the ordinary `npm test` gate (CLAUDE.md: "Add a
 * development or CI check that detects missing English/Arabic translation
 * keys") rather than a separate script, so it can't silently stop being run.
 *
 * `import.meta.glob` (not a manually maintained file list) so a namespace
 * added later is picked up automatically instead of silently skipping it
 * here too.
 */
const localeModules = import.meta.glob('./locales/*/*.json', { eager: true });

// CLDR plural suffixes i18next resolves at runtime (Intl.PluralRules
// categories) - English only ever needs one/other, Arabic needs all six, so
// a key's *base* name (before the suffix) is what must exist in both
// locales, not the exact suffixed variant. A "_one"-only English key is
// legitimately absent as "_one" in Arabic if Arabic instead defines
// "_few"/"_many"/etc. for that same base key.
const PLURAL_SUFFIXES = ['zero', 'one', 'two', 'few', 'many', 'other'];

function stripPluralSuffix(key) {
  const parts = key.split('_');
  if (parts.length > 1 && PLURAL_SUFFIXES.includes(parts[parts.length - 1])) {
    return parts.slice(0, -1).join('_');
  }
  return key;
}

function flattenKeys(obj, prefix = '') {
  const keys = [];
  for (const [key, value] of Object.entries(obj)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      keys.push(...flattenKeys(value, path));
    } else {
      keys.push(stripPluralSuffix(path));
    }
  }
  return keys;
}

// { [namespace]: { [locale]: { default: <json> } } }
const catalogs = {};
for (const [path, mod] of Object.entries(localeModules)) {
  const match = path.match(/\.\/locales\/([a-z]+)\/([a-zA-Z0-9_-]+)\.json$/);
  if (!match) continue;
  const [, locale, namespace] = match;
  catalogs[namespace] ??= {};
  catalogs[namespace][locale] = mod.default;
}

describe('translation catalogs', () => {
  it('cover every configured supported locale', () => {
    expect(SUPPORTED_LOCALES.length).toBeGreaterThan(0);
  });

  const namespaces = Object.keys(catalogs).sort();

  it('discovered at least one namespace', () => {
    expect(namespaces.length).toBeGreaterThan(0);
  });

  for (const namespace of namespaces) {
    describe(`namespace: ${namespace}`, () => {
      for (const locale of SUPPORTED_LOCALES) {
        it(`has a ${locale} catalog file`, () => {
          expect(catalogs[namespace][locale], `locales/${locale}/${namespace}.json is missing`).toBeDefined();
        });
      }

      it('has the same keys (ignoring plural suffixes) in every supported locale', () => {
        const keysByLocale = Object.fromEntries(
          SUPPORTED_LOCALES.map((locale) => [locale, new Set(flattenKeys(catalogs[namespace][locale] || {}))]),
        );
        const allKeys = new Set(Object.values(keysByLocale).flatMap((set) => [...set]));

        const missing = {};
        for (const key of allKeys) {
          const missingIn = SUPPORTED_LOCALES.filter((locale) => !keysByLocale[locale].has(key));
          if (missingIn.length > 0) missing[key] = missingIn;
        }

        expect(missing, `Keys missing from one or more locales in "${namespace}": ${JSON.stringify(missing, null, 2)}`)
          .toEqual({});
      });
    });
  }
});
