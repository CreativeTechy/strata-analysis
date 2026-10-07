import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

import i18n from './index.js';
import { resetTranslatedLabelsCache, useTranslatedLabels } from './useTranslatedLabels.js';
import { LabelProjectProvider } from './LabelProjectContext.jsx';
import { translateLabels } from '../api/i18nApi.js';

vi.mock('../api/i18nApi.js', () => ({ translateLabels: vi.fn() }));

function renderWithProject(ui, projectId = 5) {
  return render(<LabelProjectProvider value={projectId}>{ui}</LabelProjectProvider>);
}

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
    renderWithProject(<Label value="Middle East" />);
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(translateLabels).not.toHaveBeenCalled();
    expect(screen.getByText('Middle East')).toBeInTheDocument();
  });

  it('batches every component on the page into one request and renders the result', async () => {
    await i18n.changeLanguage('ar');
    translateLabels.mockResolvedValue({ 'Middle East': 'الشرق الأوسط', Retired: 'متقاعد' });
    renderWithProject(<><Label value="Middle East" /><Label value="Retired" /><Label value="Retired" /></>);
    expect(await screen.findByText('الشرق الأوسط')).toBeInTheDocument();
    expect(screen.getAllByText('متقاعد')).toHaveLength(2);
    expect(translateLabels).toHaveBeenCalledTimes(1);
    expect(translateLabels.mock.calls[0][0]).toBe(5);
    expect(translateLabels.mock.calls[0][1]).toBe('ar');
    expect([...translateLabels.mock.calls[0][2]].sort()).toEqual(['Middle East', 'Retired']);
  });

  it('keeps the original text when translation fails, and asks again on a later mount', async () => {
    await i18n.changeLanguage('ar');
    translateLabels.mockRejectedValueOnce(new Error('down'));
    const { unmount } = renderWithProject(<Label value="Gulf" />);
    await waitFor(() => expect(translateLabels).toHaveBeenCalledTimes(1));
    expect(screen.getByText('Gulf')).toBeInTheDocument();
    unmount();

    translateLabels.mockResolvedValueOnce({ Gulf: 'الخليج' });
    renderWithProject(<Label value="Gulf" />);
    expect(await screen.findByText('الخليج')).toBeInTheDocument();
    expect(translateLabels).toHaveBeenCalledTimes(2);
  });

  it('asks on behalf of the project in scope and keeps projects apart', async () => {
    await i18n.changeLanguage('ar');
    translateLabels.mockImplementation(async (projectId, locale, values) => Object.fromEntries(values.map((v) => [v, `${projectId}:${v}`])));
    const first = renderWithProject(<Label value="Gulf" />, 5);
    expect(await screen.findByText('5:Gulf')).toBeInTheDocument();
    first.unmount();
    renderWithProject(<Label value="Gulf" />, 6);
    expect(await screen.findByText('6:Gulf')).toBeInTheDocument();
    expect(translateLabels.mock.calls.map((call) => call[0])).toEqual([5, 6]);
  });

  it('makes no request when no project is in scope', async () => {
    await i18n.changeLanguage('ar');
    render(<Label value="Gulf" />);
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(translateLabels).not.toHaveBeenCalled();
    expect(screen.getByText('Gulf')).toBeInTheDocument();
  });
});
