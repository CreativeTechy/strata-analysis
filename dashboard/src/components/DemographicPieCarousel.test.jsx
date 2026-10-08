import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import DemographicPieCarousel from './DemographicPieCarousel.jsx';
import i18n from '../i18n/index.js';
import { LabelProjectProvider } from '../i18n/LabelProjectContext.jsx';
import { resetTranslatedLabelsCache } from '../i18n/useTranslatedLabels.js';
import { translateLabels } from '../api/i18nApi.js';

vi.mock('./ResponsiveChartContainer.jsx', () => ({ default: () => null }));
vi.mock('../api/i18nApi.js', () => ({ translateLabels: vi.fn() }));

const bucket = (value, total) => ({ value, total, positive: total, negative: 0, neutral: 0, mixed: 0 });

function renderCarousel(data) {
  return render(
    <MemoryRouter>
      <LabelProjectProvider value={4}>
        <DemographicPieCarousel data={data} pathFor={(value) => `/articles?region=${encodeURIComponent(value)}`} />
      </LabelProjectProvider>
    </MemoryRouter>,
  );
}

describe('DemographicPieCarousel', () => {
  beforeEach(() => {
    resetTranslatedLabelsCache();
    translateLabels.mockReset();
  });

  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('labels each bucket it steps through in Arabic', async () => {
    await i18n.changeLanguage('ar');
    translateLabels.mockResolvedValue({ 'small business owner': 'صاحب عمل صغير' });
    renderCarousel([bucket('Israel\u200f', 4), bucket('small business owner', 2), bucket('female', 1)]);
    expect(screen.getByText('إسرائيل')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: i18n.t('dashboard:carousel.nextAria') }));
    expect(await screen.findByText('صاحب عمل صغير')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: i18n.t('dashboard:carousel.nextAria') }));
    expect(screen.getByText('أنثى')).toBeInTheDocument();
    expect(translateLabels).toHaveBeenCalledWith(4, 'ar', ['small business owner']);
  });

  it('labels the folded long tail as Other', async () => {
    await i18n.changeLanguage('ar');
    const many = Array.from({ length: 9 }, (_, index) => bucket(`Region ${index}`, 10 - index));
    renderCarousel(many);
    fireEvent.click(screen.getByRole('button', { name: i18n.t('dashboard:carousel.prevAria') }));
    expect(screen.getByText('أخرى')).toBeInTheDocument();
  });

  it('shows the empty label when nothing has a count', async () => {
    await i18n.changeLanguage('en');
    renderCarousel([bucket('Lebanon', 0)]);
    expect(screen.getByText(i18n.t('dashboard:carousel.emptyDefault'))).toBeInTheDocument();
  });
});
