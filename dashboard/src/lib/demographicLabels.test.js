import { describe, expect, it } from 'vitest';

import i18n from '../i18n/index.js';
import { demographicLabel } from './demographicLabels.js';

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
});
