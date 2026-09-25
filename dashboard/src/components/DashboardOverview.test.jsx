import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import DashboardOverview from './DashboardOverview.jsx';
import { getIdeaComparisons } from '../api/projectsApi.js';
import i18n from '../i18n/index.js';

vi.mock('../api/projectsApi.js', () => ({ getIdeaComparisons: vi.fn() }));
vi.mock('./CompetitorPulseCard.jsx', () => ({ default: () => null }));
// Charts need real layout to draw anything, so they're stubbed out - these
// tests are about the text around them.
vi.mock('./ResponsiveChartContainer.jsx', () => ({ default: () => null }));

const PROJECT = { id: 1, name: 'Acme Study', mode: 'opinion' };

const INTELLIGENCE = {
  total: 10, positive: 5, negative: 3, neutral: 2, mixed: 0, net_sentiment: 20, document_count: 2,
  source_trust: {
    total_articles: 10,
    tiers: {
      trusted: { articles: 6, sources: 2 },
      untrusted: { articles: 1, sources: 1 },
      unknown: { articles: 3, sources: 1 },
    },
  },
  insights: {
    region_breakdown: [{ value: 'other', total: 4, positive: 2, negative: 1, neutral: 1, mixed: 0 }],
    frequent_ideas: [{ idea: 'A very long topic name that should wrap onto a second line instead of being cut off', type: 'issue', frequency_estimate: 3 }],
  },
};

function renderDashboard(overrides = {}) {
  return render(
    <MemoryRouter>
      <DashboardOverview
        projects={[PROJECT]}
        selectedProjectId={1}
        onProjectChange={vi.fn()}
        period="30d"
        onPeriodChange={vi.fn()}
        intelligence={INTELLIGENCE}
        loading={false}
        error={null}
        pipelineHealth={{ lastRun: { status: 'success' }, lastFinished: null }}
        {...overrides}
      />
    </MemoryRouter>,
  );
}

describe('DashboardOverview', () => {
  beforeEach(() => {
    getIdeaComparisons.mockReset();
    getIdeaComparisons.mockResolvedValue({ ok: true, data: { comparisons: [] } });
  });

  it('labels the source trust card with the Sources tab tiers', async () => {
    renderDashboard();
    expect(screen.getByRole('heading', { name: 'Source trust' })).toBeInTheDocument();
    expect(screen.getByText('Trusted')).toBeInTheDocument();
    expect(screen.getByText('Untrusted')).toBeInTheDocument();
    expect(screen.getByText('Not yet assessed')).toBeInTheDocument();
    expect(screen.getByText('60%')).toBeInTheDocument();
    await screen.findByText(/No cross-source comparisons yet/);
  });

  it('shows the empty source trust state', async () => {
    renderDashboard({ intelligence: { ...INTELLIGENCE, source_trust: { total_articles: 0, tiers: {} } } });
    expect(screen.getByText('No sources assessed yet.')).toBeInTheDocument();
    await screen.findByText(/No cross-source comparisons yet/);
  });

  it('renders source trust, run status and the "other" bucket in Arabic', async () => {
    await i18n.changeLanguage('ar');
    renderDashboard();

    expect(screen.getByRole('heading', { name: 'موثوقية المصادر' })).toBeInTheDocument();
    expect(screen.getByText('موثوق')).toBeInTheDocument();
    expect(screen.getByText('غير موثوق')).toBeInTheDocument();
    expect(screen.getByText('لم يُقيَّم بعد')).toBeInTheDocument();
    // Analysis health shows the translated run status, not the raw enum.
    expect(screen.getByText('تم بنجاح')).toBeInTheDocument();
    expect(screen.getByText('أخرى')).toBeInTheDocument();
    expect(screen.queryByText(/Source trust|Trusted|Untrusted|^success$/)).not.toBeInTheDocument();
    await screen.findByText(/لا توجد مقارنات بين المصادر بعد/);
  });

  it('shows the Arabic empty source trust state', async () => {
    await i18n.changeLanguage('ar');
    renderDashboard({ intelligence: { ...INTELLIGENCE, source_trust: { total_articles: 0, tiers: {} } } });
    expect(screen.getByText('لم يتم تقييم أي مصادر بعد.')).toBeInTheDocument();
    await screen.findByText(/لا توجد مقارنات بين المصادر بعد/);
  });

  // SM-107: every metric and chart selection is an evidence link that keeps
  // the project and the dashboard's scope.
  describe('evidence links', () => {
    beforeEach(async () => { await i18n.changeLanguage('en'); });

    function linkParams(link) {
      return new URL(link.getAttribute('href'), 'http://x').searchParams;
    }

    it('opens a sentiment bucket in the same project and period', async () => {
      renderDashboard({ intelligence: { ...INTELLIGENCE, insights: { ...INTELLIGENCE.insights, region_breakdown: [{ value: 'Gulf', total: 4 }] } } });
      const params = linkParams(screen.getByTitle('Open the articles behind negative'));
      expect(Object.fromEntries(params)).toEqual({ project_id: '1', period: '30d', sentiment: 'negative' });
      expect(Object.fromEntries(linkParams(screen.getByTitle('Open the articles behind Gulf')))).toEqual({ project_id: '1', period: '30d', region: 'Gulf' });
      expect(Object.fromEntries(linkParams(screen.getByTitle('Open the articles behind Trusted')))).toEqual({ project_id: '1', period: '30d', trust: 'trusted' });
      await screen.findByText(/No cross-source comparisons yet/);
    });

    it('carries a selected run instead of the period', async () => {
      renderDashboard({ selectedRunId: 'run-9', runs: [{ id: 'run-9', sequence_number: 4, finished_at: '2026-09-01T10:00:00Z' }] });
      const params = linkParams(screen.getByTitle('Open the articles behind positive'));
      expect(Object.fromEntries(params)).toEqual({ project_id: '1', run_id: 'run-9', sentiment: 'positive' });
      await screen.findByText(/No cross-source comparisons yet/);
    });

    it('links the headline metrics and leaves empty or folded buckets unlinked', async () => {
      renderDashboard();
      const analyzed = screen.getByRole('link', { name: /Analyzed articles: 10/ });
      expect(Object.fromEntries(linkParams(analyzed))).toEqual({ project_id: '1', period: '30d' });
      // mixed has 0 articles; the region fixture is the folded "other" slice.
      expect(screen.queryByTitle('Open the articles behind mixed')).not.toBeInTheDocument();
      expect(screen.queryByTitle('Open the articles behind Other')).not.toBeInTheDocument();
      await screen.findByText(/No cross-source comparisons yet/);
    });
  });
});
