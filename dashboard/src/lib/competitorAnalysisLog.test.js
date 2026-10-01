import { afterEach, describe, expect, it } from 'vitest';
import i18n from '../i18n/index.js';
import { analysisLogText, rejectionReasonsList, skipReasonText } from './competitorAnalysisLog.js';

const tFor = (lang) => i18n.getFixedT(lang, ['competitors', 'errors']);

describe('analysisLogText', () => {
  afterEach(() => i18n.changeLanguage('en'));

  it('renders the English line from the code, matching the backend wording', () => {
    const t = tFor('en');
    expect(analysisLogText(t, { code: 'scope_documents', params: { count: 1 }, message: 'x' })).toBe('Scope: 1 document.');
    expect(analysisLogText(t, {
      code: 'checking_articles', params: { count: 20, window: 'documents', documents: 1 }, message: 'x',
    })).toBe('Checking 20 articles from the selected document against each competitor...');
    expect(analysisLogText(t, {
      code: 'filtered_out', params: { reasons: [{ reason: 'duplicate_story', count: 7 }] }, message: 'x',
    })).toBe('Filtered out: 7 duplicate stories.');
    expect(analysisLogText(t, { code: 'done', params: { generated: 2, skipped: 1 }, message: 'x' }))
      .toBe('Done. Generated 2 reports, skipped 1.');
  });

  it('renders the same lines in Arabic', () => {
    const t = tFor('ar');
    expect(analysisLogText(t, { code: 'scope_documents', params: { count: 1 }, message: 'Scope: 1 document.' }))
      .toBe('النطاق: مستند واحد.');
    expect(analysisLogText(t, { code: 'analyzing_competitors', params: { count: 2 }, message: 'x' }))
      .toBe('جارٍ تحليل منافسَين قيد المتابعة.');
    expect(analysisLogText(t, {
      code: 'writing_report', params: { name: 'Stories Coffee', count: 4 }, message: 'x',
    })).toBe('Stories Coffee: جارٍ كتابة تقرير من 4 قصص...');
    expect(analysisLogText(t, {
      code: 'finding_generated', params: { name: 'Costa', impact: 'high', headline: 'عنوان' }, message: 'x',
    })).toBe('Costa: تأثير مرتفع - عنوان');
  });

  it('resolves a failure through the errors namespace by its LLM error code', () => {
    const t = tFor('en');
    expect(analysisLogText(t, {
      code: 'competitor_failed', params: { name: 'Costa', error_code: 'llm_connection_error' }, message: 'x',
    })).toBe("Costa: failed - Couldn't reach the configured AI service. Please contact your administrator.");
  });

  it('falls back to the English message for entries without a known code', () => {
    const t = tFor('ar');
    expect(analysisLogText(t, { message: 'Scope: 3 documents.' })).toBe('Scope: 3 documents.');
    expect(analysisLogText(t, { code: 'some_future_code', params: {}, message: 'Something new.' })).toBe('Something new.');
  });
});

describe('workspace notice helpers', () => {
  it('translates rejection reasons and skip reasons', () => {
    const t = tFor('ar');
    expect(rejectionReasonsList(t, [{ reason: 'duplicate_story', count: 7 }, { reason: 'blocked_page', count: 1 }]))
      .toBe('7 قصص مكررة، صفحة محجوبة واحدة');
    expect(skipReasonText(t, { reason_code: 'no_evidence', reason: 'No validated evidence in this period.' }))
      .toBe('لا توجد أدلة موثَّقة في هذه الفترة.');
    // A skipped entry from before reason codes existed keeps its English reason.
    expect(skipReasonText(t, { reason: 'Old reason.' })).toBe('Old reason.');
  });
});
