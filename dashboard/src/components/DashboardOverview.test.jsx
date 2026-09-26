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
});
