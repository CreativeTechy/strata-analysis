import { afterEach, describe, expect, it, vi } from 'vitest';

import { translateLabels } from './i18nApi.js';

describe('translateLabels', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('posts the project, locale and values and returns the label map', async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ locale: 'ar', labels: { Gulf: 'الخليج' } }) }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(translateLabels(3, 'ar', ['Gulf'])).resolves.toEqual({ Gulf: 'الخليج' });
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/i18n/labels');
    expect(options.method).toBe('POST');
    expect(JSON.parse(options.body)).toEqual({ project_id: 3, locale: 'ar', values: ['Gulf'] });
  });

  it('throws on an error response so the caller keeps its fallback', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 403, json: async () => ({}) })));
    await expect(translateLabels(3, 'ar', ['Gulf'])).rejects.toThrow('403');
  });

  it('treats a response without labels as no translations', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ locale: 'ar' }) })));
    await expect(translateLabels(3, 'ar', ['Gulf'])).resolves.toEqual({});
  });
});
