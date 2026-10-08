import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render as baseRender, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import DashboardOverview from './DashboardOverview.jsx';
import { getIdeaComparisons } from '../api/projectsApi.js';
import i18n from '../i18n/index.js';
import { useAuth } from '../auth/useAuth.js';
import { LabelProjectProvider } from '../i18n/LabelProjectContext.jsx';
import { resetTranslatedLabelsCache } from '../i18n/useTranslatedLabels.js';

vi.mock('../api/projectsApi.js', () => ({ getIdeaComparisons: vi.fn() }));
vi.mock('./CompetitorPulseCard.jsx', () => ({ default: () => null }));
// Charts need real layout to draw anything, so they're stubbed out - these
// tests are about the text around them.
vi.mock('./ResponsiveChartContainer.jsx', () => ({ default: () => null }));
vi.mock('../auth/useAuth.js', () => ({ useAuth: vi.fn() }));
vi.mock('../api/i18nApi.js', () => ({
  translateLabels: vi.fn(async (projectId, locale, values) => Object.fromEntries(values.map((value) => [value, `ع ${value}`]))),
}));

function LabelProject({ children }) {
  return <LabelProjectProvider value={1}>{children}</LabelProjectProvider>;
}
const render = (ui, options) => baseRender(ui, { wrapper: LabelProject, ...options });

const PROJECT = { id: 1, name: 'Acme Study', mode: 'opinion' };

const INTELLIGENCE = {
  project_id: 1,
  total: 10, positive: 5, negative: 3, neutral: 2, mixed: 0, net_sentiment: 20, document_count: 2,
  sentiment_over_time: [{ date: '2026-09-01', total: 10, positive: 5, negative: 3, neutral: 2 }],
  source_trust: {
    total_articles: 10,
    tiers: {
      trusted: { articles: 6, sources: 2 },
      untrusted: { articles: 1, sources: 1 },
      unknown: { articles: 3, sources: 1 },
    },
  },
  insights: {
    frequent_ideas: [
      { idea: 'Great customer support', type: 'praise', frequency_estimate: 5 },
      { idea: 'Checkout keeps failing', type: 'complaint', frequency_estimate: 4 },
      { idea: 'Add a dark mode', type: 'suggestion', frequency_estimate: 3 },
      { idea: 'Prices went up', type: 'issue', frequency_estimate: 2 },
    ],
    language_breakdown: [{ language: 'en', count: 10 }],
    region_breakdown: [{ value: 'other', total: 4, positive: 2, negative: 1, neutral: 1, mixed: 0 }],
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
        runs={[]}
        selectedRunId={null}
        onRunChange={vi.fn()}
        {...overrides}
      />
    </MemoryRouter>,
  );
}

function ideasCard() {
  return screen.getByRole('tablist', { name: 'Show concerns or all ideas' }).closest('article');
}

// The language/region/.../source trust cards live in the collapsed
// "Detailed breakdowns" area, so they only render once it's opened.
function openDetailedBreakdowns() {
  fireEvent.click(screen.getByRole('button', { name: /Detailed breakdowns|التوزيعات التفصيلية/ }));
}

describe('DashboardOverview', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('en');
    try {
      window.localStorage.clear();
    } catch {
      // storage unavailable in this environment - the component tolerates that too
    }
    getIdeaComparisons.mockReset();
    getIdeaComparisons.mockResolvedValue({ ok: true, data: { comparisons: [] } });
    useAuth.mockReturnValue({ hasPermission: () => true });
  });

  it('shows the sentiment trend and top concerns on the first screen', async () => {
    renderDashboard();
    expect(screen.getByRole('heading', { name: 'Sentiment trend' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Top concerns' })).toBeInTheDocument();
    await screen.findByText(/No cross-source comparisons yet/);
  });

  it('lists only complaints and issues under Concerns, and every idea under All ideas', async () => {
    renderDashboard();
    const card = ideasCard();
    expect(within(card).getByText('Checkout keeps failing')).toBeInTheDocument();
    expect(within(card).getByText('Prices went up')).toBeInTheDocument();
    expect(within(card).queryByText('Great customer support')).not.toBeInTheDocument();
    expect(within(card).queryByText('Add a dark mode')).not.toBeInTheDocument();

    fireEvent.click(within(card).getByRole('tab', { name: 'All ideas' }));
    expect(within(card).getByRole('heading', { name: 'Most talked-about ideas' })).toBeInTheDocument();
    expect(within(card).getByText('Great customer support')).toBeInTheDocument();
    expect(within(card).getByText('Add a dark mode')).toBeInTheDocument();
    await screen.findByText(/No cross-source comparisons yet/);
  });

  it('paginates ideas 3 at a time and resets to page 1 when the filter changes', async () => {
    renderDashboard();
    const card = ideasCard();

    fireEvent.click(within(card).getByRole('tab', { name: 'All ideas' }));
    expect(within(card).getByText('Great customer support')).toBeInTheDocument();
    expect(within(card).getByText('Checkout keeps failing')).toBeInTheDocument();
    expect(within(card).getByText('Add a dark mode')).toBeInTheDocument();
    expect(within(card).queryByText('Prices went up')).not.toBeInTheDocument();
    expect(within(card).getByText('Page 1 of 2')).toBeInTheDocument();

    fireEvent.click(within(card).getByRole('button', { name: 'Next' }));
    expect(within(card).getByText('Prices went up')).toBeInTheDocument();
    expect(within(card).queryByText('Great customer support')).not.toBeInTheDocument();
    expect(within(card).getByText('Page 2 of 2')).toBeInTheDocument();
    expect(within(card).getByRole('button', { name: 'Next' })).toBeDisabled();

    fireEvent.click(within(card).getByRole('tab', { name: 'Concerns' }));
    expect(within(card).getByText('Checkout keeps failing')).toBeInTheDocument();
    expect(within(card).getByText('Prices went up')).toBeInTheDocument();
    expect(within(card).queryByText(/^Page \d+ of \d+$/)).not.toBeInTheDocument();
    await screen.findByText(/No cross-source comparisons yet/);
  });

  it('shows an empty state when there are ideas but none are concerns', async () => {
    renderDashboard({
      intelligence: { ...INTELLIGENCE, insights: { ...INTELLIGENCE.insights, frequent_ideas: [{ idea: 'Love it', type: 'praise', frequency_estimate: 1 }] } },
    });
    expect(within(ideasCard()).getByText('No recurring concerns detected yet.')).toBeInTheDocument();
    await screen.findByText(/No cross-source comparisons yet/);
  });

  it('keeps the detailed breakdowns collapsed until expanded', async () => {
    renderDashboard();
    const toggle = screen.getByRole('button', { name: /Detailed breakdowns/ });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('heading', { name: 'Language distribution' })).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Source trust' })).not.toBeInTheDocument();

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    for (const title of ['Language distribution', 'Region distribution', 'Gender distribution', 'Age range distribution', 'Segment distribution', 'Source trust']) {
      expect(screen.getByRole('heading', { name: title })).toBeInTheDocument();
    }

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('heading', { name: 'Language distribution' })).not.toBeInTheDocument();
    await screen.findByText(/No cross-source comparisons yet/);
  });

  it('remembers whether the detailed breakdowns were left open', async () => {
    const { unmount } = renderDashboard();
    fireEvent.click(screen.getByRole('button', { name: /Detailed breakdowns/ }));
    expect(window.localStorage.getItem('dashboard-detailed-breakdowns-open')).toBe('open');
    await screen.findByText(/No cross-source comparisons yet/);
    unmount();

    renderDashboard();
    expect(screen.getByRole('button', { name: /Detailed breakdowns/ })).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('heading', { name: 'Language distribution' })).toBeInTheDocument();
    await screen.findByText(/No cross-source comparisons yet/);
  });

  it('points the breakdowns toggle at a panel that exists even while collapsed', async () => {
    const { container } = renderDashboard();
    const toggle = screen.getByRole('button', { name: /Detailed breakdowns/ });
    const panel = container.querySelector(`#${toggle.getAttribute('aria-controls')}`);
    expect(panel).not.toBeNull();
    expect(panel).toHaveAttribute('hidden');
    await screen.findByText(/No cross-source comparisons yet/);
  });

  it('prefers the backend concern ranking over filtering the top-12 idea slice', async () => {
    renderDashboard({
      intelligence: {
        ...INTELLIGENCE,
        insights: {
          ...INTELLIGENCE.insights,
          frequent_ideas: [{ idea: 'Great customer support', type: 'praise', frequency_estimate: 5 }],
          frequent_concerns: [{ idea: 'Refunds take weeks', type: 'complaint', frequency_estimate: 2 }],
        },
      },
    });
    expect(within(ideasCard()).getByText('Refunds take weeks')).toBeInTheDocument();
    await screen.findByText(/No cross-source comparisons yet/);
  });

  it('starts the next project on page 1 of Top concerns', async () => {
    const concerns = ['A', 'B', 'C', 'D', 'E'].map((letter, index) => ({ idea: `Concern ${letter}`, type: 'complaint', frequency_estimate: 10 - index }));
    const withConcerns = (projectId) => ({ ...INTELLIGENCE, project_id: projectId, insights: { ...INTELLIGENCE.insights, frequent_ideas: concerns, frequent_concerns: concerns } });
    const props = {
      projects: [PROJECT, { id: 2, name: 'Beta', mode: 'opinion' }],
      onProjectChange: vi.fn(), period: '30d', onPeriodChange: vi.fn(), loading: false, error: null,
      pipelineHealth: { lastRun: { status: 'success' }, lastFinished: null }, runs: [], selectedRunId: null, onRunChange: vi.fn(),
    };
    const { rerender } = render(<MemoryRouter><DashboardOverview {...props} selectedProjectId={1} intelligence={withConcerns(1)} /></MemoryRouter>);
    fireEvent.click(within(ideasCard()).getByRole('button', { name: /Next/ }));
    expect(within(ideasCard()).getByText('Concern D')).toBeInTheDocument();

    rerender(<MemoryRouter><DashboardOverview {...props} selectedProjectId={2} intelligence={withConcerns(2)} /></MemoryRouter>);
    expect(within(ideasCard()).getByText('Concern A')).toBeInTheDocument();
    expect(within(ideasCard()).queryByText('Concern D')).not.toBeInTheDocument();
    await screen.findByText(/No cross-source comparisons yet/);
  });

  it('returns to Top concerns when the project changes', async () => {
    const { rerender } = renderDashboard({ projects: [PROJECT, { id: 2, name: 'Beta', mode: 'opinion' }] });
    fireEvent.click(within(ideasCard()).getByRole('tab', { name: 'All ideas' }));
    expect(within(ideasCard()).getByRole('heading', { name: 'Most talked-about ideas' })).toBeInTheDocument();

    rerender(
      <MemoryRouter>
        <DashboardOverview
          projects={[PROJECT, { id: 2, name: 'Beta', mode: 'opinion' }]}
          selectedProjectId={2}
          onProjectChange={vi.fn()}
          period="30d"
          onPeriodChange={vi.fn()}
          intelligence={{ ...INTELLIGENCE, project_id: 2 }}
          loading={false}
          error={null}
          pipelineHealth={{ lastRun: { status: 'success' }, lastFinished: null }}
          runs={[]}
          selectedRunId={null}
          onRunChange={vi.fn()}
        />
      </MemoryRouter>,
    );
    expect(within(ideasCard()).getByRole('heading', { name: 'Top concerns' })).toBeInTheDocument();
    await screen.findByText(/No cross-source comparisons yet/);
  });

  it('labels the source trust card with the Sources tab tiers', async () => {
    renderDashboard();
    openDetailedBreakdowns();
    expect(screen.getByRole('heading', { name: 'Source trust' })).toBeInTheDocument();
    expect(screen.getByText('Trusted')).toBeInTheDocument();
    expect(screen.getByText('Untrusted')).toBeInTheDocument();
    expect(screen.getByText('Not yet assessed')).toBeInTheDocument();
    expect(screen.getByText('60%')).toBeInTheDocument();
    await screen.findByText(/No cross-source comparisons yet/);
  });

  it('shows the empty source trust state', async () => {
    renderDashboard({ intelligence: { ...INTELLIGENCE, source_trust: { total_articles: 0, tiers: {} } } });
    openDetailedBreakdowns();
    expect(screen.getByText('No sources assessed yet.')).toBeInTheDocument();
    await screen.findByText(/No cross-source comparisons yet/);
  });

  it('renders source trust, run status and the "other" bucket in Arabic', async () => {
    await i18n.changeLanguage('ar');
    renderDashboard();
    openDetailedBreakdowns();

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

  // SM-141 follow-up: the Region distribution kept "Lebanon"/"Israel" in
  // English in the Arabic UI when the values weren't spelled exactly like
  // the canonical country name (an invisible direction mark, an Arabic name).
  it('names country regions in Arabic however they were stored', async () => {
    resetTranslatedLabelsCache();
    await i18n.changeLanguage('ar');
    renderDashboard({
      intelligence: {
        ...INTELLIGENCE,
        insights: {
          ...INTELLIGENCE.insights,
          region_breakdown: [{ value: 'Lebanon\u200f', total: 7 }, { value: '\u200fIsrael', total: 5 }],
          gender_breakdown: [{ value: 'unknown', total: 13 }],
          age_range_breakdown: [{ value: 'unknown', total: 13 }],
        },
      },
    });
    openDetailedBreakdowns();
    expect(screen.getAllByText('لبنان').length).toBeGreaterThan(0);
    expect(screen.getByText('إسرائيل')).toBeInTheDocument();
    expect(screen.queryByText(/Lebanon|Israel/)).not.toBeInTheDocument();
    await screen.findByText(/لا توجد مقارنات بين المصادر بعد/);
  });

  it('translates every demographic bucket and platform in Arabic', async () => {
    resetTranslatedLabelsCache();
    await i18n.changeLanguage('ar');
    renderDashboard({
      intelligence: {
        ...INTELLIGENCE,
        platforms: [{ platform: 'Documents', total: 4, positive: 2, negative: 1, neutral: 1, mixed: 0 }, { platform: 'Reddit', total: 1, positive: 1, negative: 0, neutral: 0, mixed: 0 }],
        insights: {
          ...INTELLIGENCE.insights,
          region_breakdown: [{ value: 'Jordan', total: 4 }, { value: 'Middle East', total: 2 }],
          segment_breakdown: [{ value: 'small_business_owner', total: 2 }],
          gender_breakdown: [{ value: 'female', total: 3 }, { value: 'male', total: 2 }],
          age_range_breakdown: [{ value: '65_plus', total: 2 }],
        },
      },
    });
    openDetailedBreakdowns();
    expect(screen.getByText('الأردن')).toBeInTheDocument();
    expect(screen.getByText('أنثى')).toBeInTheDocument();
    expect(screen.getByText('ذكر')).toBeInTheDocument();
    expect(screen.getByText('65 فأكثر')).toBeInTheDocument();
    // Free-text buckets come back from the label translation endpoint.
    expect(await screen.findByText('ع Middle East')).toBeInTheDocument();
    expect(screen.getByText('ع small_business_owner')).toBeInTheDocument();
    // Generic platform buckets translate; brand names stay as written.
    expect(screen.getAllByText('المستندات').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Reddit').length).toBeGreaterThan(0);
    expect(screen.queryByText('Documents')).not.toBeInTheDocument();
    expect(screen.queryByText(/^(Jordan|Female|Male|65 Plus|Middle East|Small Business Owner)$/)).not.toBeInTheDocument();
    await screen.findByText(/لا توجد مقارنات بين المصادر بعد/);
  });

  it('shows the Arabic empty source trust state', async () => {
    await i18n.changeLanguage('ar');
    renderDashboard({ intelligence: { ...INTELLIGENCE, source_trust: { total_articles: 0, tiers: {} } } });
    openDetailedBreakdowns();
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
      // The distribution cards live in the collapsed "Detailed breakdowns".
      openDetailedBreakdowns();
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
      openDetailedBreakdowns();
      expect(screen.getByText('Other')).toBeInTheDocument();
      expect(screen.queryByTitle('Open the articles behind mixed')).not.toBeInTheDocument();
      expect(screen.queryByTitle('Open the articles behind Other')).not.toBeInTheDocument();
      await screen.findByText(/No cross-source comparisons yet/);
    });
  });
});
