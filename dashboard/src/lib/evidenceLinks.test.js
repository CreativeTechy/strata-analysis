import { describe, expect, it } from 'vitest';
import { articlesEvidencePath, isLinkableBucket, readEvidenceParams } from './evidenceLinks.js';

describe('articlesEvidencePath', () => {
  it('carries project, period and the selected bucket', () => {
    expect(articlesEvidencePath({ projectId: 3, period: '7d', filters: { sentiment: 'negative' } }))
      .toBe('/articles?project_id=3&period=7d&sentiment=negative');
  });

  it('prefers a run over the period, as the dashboard does', () => {
    expect(articlesEvidencePath({ projectId: 3, period: '7d', runId: 'r1', filters: { platform: 'X' } }))
      .toBe('/articles?project_id=3&run_id=r1&platform=X');
  });

  it('drops blank filters and encodes values', () => {
    expect(articlesEvidencePath({ projectId: 3, period: 'all', filters: { region: 'Gulf & Levant', gender: '', age_range: null } }))
      .toBe('/articles?project_id=3&period=all&region=Gulf+%26+Levant');
  });
});

describe('readEvidenceParams', () => {
  it('reads scope and dimensions, ignoring unrelated params', () => {
    const params = new URLSearchParams('project_id=3&period=30d&platform=X&search=ev&date=2026-09-01');
    expect(readEvidenceParams(params)).toEqual({ period: '30d', platform: 'X', date: '2026-09-01' });
  });

  it('drops an unknown period and lets a run replace the period', () => {
    expect(readEvidenceParams(new URLSearchParams('period=90d'))).toEqual({});
    expect(readEvidenceParams(new URLSearchParams('period=7d&run_id=r1'))).toEqual({ run_id: 'r1' });
  });
});

describe('isLinkableBucket', () => {
  it('refuses the folded "other" slice and blanks', () => {
    expect(isLinkableBucket('other')).toBe(false);
    expect(isLinkableBucket('')).toBe(false);
    expect(isLinkableBucket('unknown')).toBe(true);
  });
});
