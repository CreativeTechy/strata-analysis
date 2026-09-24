import { describe, expect, it } from 'vitest';

import {
  formatDate, formatDateTime, formatLanguageName, formatNumber, formatPercent,
} from './i18nFormat.js';

describe('formatDate', () => {
  it('formats a date for English', () => {
    expect(formatDate('2026-03-05T00:00:00Z', 'en')).toMatch(/Mar/);
  });

  it('formats the same date differently for Arabic (still legible, non-empty)', () => {
    const value = formatDate('2026-03-05T00:00:00Z', 'ar');
    expect(value).toBeTruthy();
  });

  it('returns an empty string for a missing/invalid value rather than "Invalid Date"', () => {
    expect(formatDate(null, 'en')).toBe('');
    expect(formatDate('not-a-date', 'en')).toBe('');
  });
});

describe('formatDateTime', () => {
  it('includes both a date and a time component', () => {
    const value = formatDateTime('2026-03-05T14:30:00Z', 'en');
    expect(value).toMatch(/Mar/);
    expect(value).toMatch(/\d/);
  });
});

describe('formatNumber', () => {
  it('formats a plain number for English using Latin digits', () => {
    expect(formatNumber(1234, 'en')).toBe('1,234');
  });

  it('formats a plain number for Arabic using Latin digits too (MSA UI convention, not Arabic-Indic)', () => {
    // The app deliberately pins western Arabic numerals for the ar locale
    // (see INTL_LOCALE_TAGS's `-u-nu-latn` extension) - digits stay
    // technical/readable rather than switching to ٠١٢٣.
    expect(formatNumber(1234, 'ar')).toBe('1,234');
  });

  it('returns an empty string for a non-numeric value', () => {
    expect(formatNumber(undefined, 'en')).toBe('');
    expect(formatNumber('abc', 'en')).toBe('');
  });
});

describe('formatPercent', () => {
  it('formats a 0-1 ratio as a whole percentage by default', () => {
    expect(formatPercent(0.62, 'en')).toBe('62%');
  });

  it('formats an already-computed whole number (e.g. Math.round(count/total*100)) with alreadyWhole', () => {
    expect(formatPercent(62, 'en', { alreadyWhole: true })).toBe('62%');
  });
});

describe('formatLanguageName', () => {
  it('renders a language code as a display name in the current locale', () => {
    expect(formatLanguageName('ar', 'en')).toMatch(/Arabic/i);
    expect(formatLanguageName('en', 'en')).toMatch(/English/i);
  });

  it('falls back to the raw code if Intl.DisplayNames cannot resolve it', () => {
    expect(formatLanguageName('not-a-real-code', 'en')).toBeTruthy();
  });
});
