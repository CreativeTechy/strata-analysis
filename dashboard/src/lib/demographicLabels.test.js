import { describe, expect, it } from 'vitest';

import i18n from '../i18n/index.js';
import { countryCodeFor, demographicLabel, isFreeTextValue } from './demographicLabels.js';

const tFor = (locale) => i18n.getFixedT(locale);

describe('demographicLabel', () => {
  it('translates the closed gender and age-range vocabularies', () => {
    expect(demographicLabel(tFor('en'), 'en', 'female')).toBe('Female');
    expect(demographicLabel(tFor('ar'), 'ar', 'female')).toBe('أنثى');
    expect(demographicLabel(tFor('en'), 'en', '65_plus')).toBe('65+');
    expect(demographicLabel(tFor('ar'), 'ar', 'under_18')).toBe('أقل من 18');
  });

  it('translates the app-generated other/unknown buckets', () => {
    expect(demographicLabel(tFor('ar'), 'ar', 'unknown')).toBe('غير معروف');
    expect(demographicLabel(tFor('ar'), 'ar', null)).toBe('غير معروف');
    expect(demographicLabel(tFor('en'), 'en', 'other')).toBe('Other');
  });

  it('names a canonical country region in the active locale, keeping the stored English name', () => {
    expect(demographicLabel(tFor('ar'), 'ar', 'Jordan')).toBe('الأردن');
    expect(demographicLabel(tFor('en'), 'en', 'Congo (DRC)')).toBe('Congo (DRC)');
  });

  it('leaves free-text regions and segments as a capitalize transform', () => {
    expect(demographicLabel(tFor('ar'), 'ar', 'middle_east')).toBe('Middle East');
    expect(demographicLabel(tFor('ar'), 'ar', 'small business owner')).toBe('Small Business Owner');
  });

  // SM-141 follow-up: region values that name a country but aren't spelled
  // exactly like the canonical English name still translate.
  it('names a country even with invisible direction marks or spacing around it', () => {
    for (const value of ['Lebanon\u200f', '\u200fLebanon', '\u202bIsrael\u202c', ' Lebanon\u00a0', 'lebanon', 'Lebanon.']) {
      expect(demographicLabel(tFor('ar'), 'ar', value)).toMatch(/^(لبنان|إسرائيل)$/);
    }
    expect(demographicLabel(tFor('ar'), 'ar', 'Lebanon\u200f')).toBe('لبنان');
    expect(demographicLabel(tFor('ar'), 'ar', 'Israel')).toBe('إسرائيل');
  });

  it('names a country given its ISO code or its Arabic name, in either UI language', () => {
    expect(demographicLabel(tFor('ar'), 'ar', 'LB')).toBe('لبنان');
    expect(demographicLabel(tFor('en'), 'en', 'لبنان')).toBe('Lebanon');
    expect(demographicLabel(tFor('en'), 'en', 'اسرائيل')).toBe('Israel');
    expect(demographicLabel(tFor('en'), 'en', 'الاردن')).toBe('Jordan');
    expect(demographicLabel(tFor('ar'), 'ar', 'إسرائيل')).toBe('إسرائيل');
  });

  it('uses the server translation for free text and only sends free text for it', () => {
    expect(demographicLabel(tFor('ar'), 'ar', 'Middle East', 'الشرق الأوسط')).toBe('الشرق الأوسط');
    expect(isFreeTextValue('Middle East')).toBe(true);
    expect(isFreeTextValue('Lebanon\u200f')).toBe(false);
    expect(isFreeTextValue('لبنان')).toBe(false);
    expect(isFreeTextValue('female')).toBe(false);
    expect(isFreeTextValue('unknown')).toBe(false);
    expect(isFreeTextValue('')).toBe(false);
  });

  it('resolves country codes', () => {
    expect(countryCodeFor('Lebanon')).toBe('LB');
    expect(countryCodeFor('Congo (DRC)')).toBe('CD');
    expect(countryCodeFor('North Sea')).toBeNull();
    expect(countryCodeFor('XX')).toBeNull();
  });
});
