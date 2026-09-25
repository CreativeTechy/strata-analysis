import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import StatsOverview from './StatsOverview.jsx';
import { getTrendSummary } from '../api/projectsApi.js';
import { listDocuments } from '../api/projectDocumentsApi.js';

vi.mock('../api/projectsApi.js', () => ({
  getKeywordExistence: vi.fn(),
  getReportVariation: vi.fn(),
  getTrendSummary: vi.fn(),
}));
vi.mock('../api/projectDocumentsApi.js', () => ({ listDocuments: vi.fn() }));

const INTELLIGENCE = {
  total: 10,
  positive: 6,
  negative: 2,
  neutral: 2,
  mixed: 0,
  net_sentiment: 40,
};

describe('StatsOverview sentiment score', () => {
  beforeEach(() => {
    getTrendSummary.mockResolvedValue({ ok: true, data: {} });
    listDocuments.mockResolvedValue({ documents: [] });
  });

  it('shows the net sentiment score in the Sentiment analysis section', () => {
    render(
      <MemoryRouter>
        <StatsOverview intelligence={INTELLIGENCE} project={{ id: 1, name: 'Acme', keywords: [] }} />
      </MemoryRouter>,
    );

    const section = screen.getByRole('heading', { name: 'Sentiment analysis' }).closest('section');
    expect(section).toHaveTextContent('+40');
    expect(section).toHaveTextContent('net sentiment');
    expect(screen.getByLabelText('Net sentiment score: +40 out of 100')).toBeInTheDocument();
  });

  it('renders a negative score with the negative tone', () => {
    render(
      <MemoryRouter>
        <StatsOverview
          intelligence={{ ...INTELLIGENCE, positive: 1, negative: 6, neutral: 3, net_sentiment: -50 }}
          project={{ id: 1, name: 'Acme', keywords: [] }}
        />
      </MemoryRouter>,
    );

    expect(screen.getByLabelText('Net sentiment score: -50 out of 100')).toHaveClass('negative');
  });
});
