import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import DashboardOverview from './DashboardOverview.jsx'

vi.mock('./CompetitorPulseCard.jsx', () => ({ default: () => <div data-testid="competitor-pulse-card" /> }))
vi.mock('../api/projectsApi.js', () => ({ getIdeaComparisons: vi.fn(async () => ({ ok: true, data: { comparisons: [] } })) }))

const PROJECT = { id: 1, name: 'Acme Study', status: 'active' }

const INTELLIGENCE = {
  total: 10,
  positive: 4,
  negative: 3,
  neutral: 3,
  mixed: 0,
  net_sentiment: 10,
  document_count: 2,
  sentiment_over_time: [{ date: '2026-09-01', total: 10, positive: 4, negative: 3, neutral: 3 }],
  insights: {
    frequent_ideas: [
      { idea: 'Great customer support', type: 'praise', frequency_estimate: 5 },
      { idea: 'Checkout keeps failing', type: 'complaint', frequency_estimate: 4 },
      { idea: 'Add a dark mode', type: 'suggestion', frequency_estimate: 3 },
      { idea: 'Prices went up', type: 'issue', frequency_estimate: 2 },
    ],
    language_breakdown: [{ language: 'en', count: 10 }],
    region_breakdown: [{ value: 'united_kingdom', total: 10, positive: 4, negative: 3, neutral: 3, mixed: 0 }],
  },
}

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
        pipelineHealth={null}
        runs={[]}
        selectedRunId={null}
        onRunChange={vi.fn()}
        {...overrides}
      />
    </MemoryRouter>,
  )
}

function ideasCard() {
  return screen.getByRole('tablist', { name: 'Show concerns or all ideas' }).closest('article')
}

describe('DashboardOverview', () => {
  beforeEach(() => {
    try {
      window.localStorage.clear()
    } catch {
      // storage unavailable in this environment - the component tolerates that too
    }
  })

  it('shows the sentiment trend and top concerns on the first screen', () => {
    renderDashboard()
    expect(screen.getByRole('heading', { name: 'Sentiment trend' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Top concerns' })).toBeInTheDocument()
  })

  it('lists only complaints and issues under Concerns, and every idea under All ideas', () => {
    renderDashboard()
    const card = ideasCard()
    expect(within(card).getByText('Checkout keeps failing')).toBeInTheDocument()
    expect(within(card).getByText('Prices went up')).toBeInTheDocument()
    expect(within(card).queryByText('Great customer support')).not.toBeInTheDocument()
    expect(within(card).queryByText('Add a dark mode')).not.toBeInTheDocument()

    fireEvent.click(within(card).getByRole('tab', { name: 'All ideas' }))
    expect(within(card).getByRole('heading', { name: 'Most talked-about ideas' })).toBeInTheDocument()
    expect(within(card).getByText('Great customer support')).toBeInTheDocument()
    expect(within(card).getByText('Add a dark mode')).toBeInTheDocument()
  })

  it('shows an empty state when there are ideas but none are concerns', () => {
    renderDashboard({
      intelligence: { ...INTELLIGENCE, insights: { ...INTELLIGENCE.insights, frequent_ideas: [{ idea: 'Love it', type: 'praise', frequency_estimate: 1 }] } },
    })
    expect(within(ideasCard()).getByText('No recurring concerns detected yet.')).toBeInTheDocument()
  })

  it('keeps the detailed breakdowns collapsed until expanded', () => {
    renderDashboard()
    const toggle = screen.getByRole('button', { name: /Detailed breakdowns/ })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('heading', { name: 'Language distribution' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Region distribution' })).not.toBeInTheDocument()

    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    for (const title of ['Language distribution', 'Region distribution', 'Gender distribution', 'Age range distribution', 'Segment distribution', 'Source trust']) {
      expect(screen.getByRole('heading', { name: title })).toBeInTheDocument()
    }

    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('heading', { name: 'Language distribution' })).not.toBeInTheDocument()
  })
})
