import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

import i18n from './index.js';
import { resetTranslatedLabelsCache, useTranslatedLabels } from './useTranslatedLabels.js';
import { translateLabels } from '../api/i18nApi.js';

vi.mock('../api/i18nApi.js', () => ({ translateLabels: vi.fn() }));

function Label({ value }) {
  const translatedFor = useTranslatedLabels([value]);
  return <span>{translatedFor(value) || value}</span>;
}

describe('useTranslatedLabels', () => {
  beforeEach(() => {
    resetTranslatedLabelsCache();
    translateLabels.mockReset();
  });

  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('never asks for the default locale', async () => {
    await i18n.changeLanguage('en');
    render(<Label value="Middle East" />);
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(translateLabels).not.toHaveBeenCalled();
    expect(screen.getByText('Middle East')).toBeInTheDocument();
  });

  it('batches every component on the page into one request and renders the result', async () => {
    await i18n.changeLanguage('ar');
    translateLabels.mockResolvedValue({ 'Middle East': 'الشرق الأوسط', Retired: 'متقاعد' });
    render(<><Label value="Middle East" /><Label value="Retired" /><Label value="Retired" /></>);
    expect(await screen.findByText('الشرق الأوسط')).toBeInTheDocument();
    expect(screen.getAllByText('متقاعد')).toHaveLength(2);
    expect(translateLabels).toHaveBeenCalledTimes(1);
    expect(translateLabels.mock.calls[0][0]).toBe('ar');
    expect([...translateLabels.mock.calls[0][1]].sort()).toEqual(['Middle East', 'Retired']);
  });

  it('keeps the original text when translation fails, and asks again on a later mount', async () => {
    await i18n.changeLanguage('ar');
    translateLabels.mockRejectedValueOnce(new Error('down'));
    const { unmount } = render(<Label value="Gulf" />);
    await waitFor(() => expect(translateLabels).toHaveBeenCalledTimes(1));
    expect(screen.getByText('Gulf')).toBeInTheDocument();
    unmount();

    translateLabels.mockResolvedValueOnce({ Gulf: 'الخليج' });
    render(<Label value="Gulf" />);
    expect(await screen.findByText('الخليج')).toBeInTheDocument();
    expect(translateLabels).toHaveBeenCalledTimes(2);
  });
});
