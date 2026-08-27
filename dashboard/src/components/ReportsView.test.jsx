import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import ReportsView from './ReportsView.jsx'

vi.mock('./StatsOverview', () => ({ default: () => <div data-testid="stats-overview" /> }))
vi.mock('./CompetitorPulseCard.jsx', () => ({ default: () => <div data-testid="competitor-pulse-card" /> }))

const PROJECT = { id: 1, name: 'Acme Study', status: 'active' }

function baseProps(overrides = {}) {
  return {
    projects: [PROJECT],
    isLoadingProjects: false,
    selectedProject: PROJECT,
    selectedProjectId: 1,
    onSelectedProjectIdChange: vi.fn(),
    intelligence: { total: 10, positive: 6, negative: 2, neutral: 2, mixed: 0 },
    isLoadingIntelligence: false,
    intelligenceError: null,
    lastIntelligenceSyncAt: null,
    reportPeriod: '30d',
    onReportPeriodChange: vi.fn(),
    reportRunId: null,
    onReportRunIdChange: vi.fn(),
    projectRuns: [],
    onRefresh: vi.fn(),
    ...overrides,
  }
}

describe('ReportsView', () => {
  it('shows the selected project name and article count', () => {
    render(<ReportsView {...baseProps()} />)
    expect(screen.getByRole('heading', { name: 'Acme Study' })).toBeInTheDocument()
    expect(screen.getByText('10')).toBeInTheDocument()
  })

  it('shows a sync-failed status when intelligenceError is set', () => {
    render(<ReportsView {...baseProps({ intelligenceError: 'network down' })} />)
    expect(screen.getByText('Sync failed')).toBeInTheDocument()
    expect(screen.getByText('network down')).toBeInTheDocument()
  })

  it('shows a syncing status while loading', () => {
    render(<ReportsView {...baseProps({ isLoadingIntelligence: true })} />)
    expect(screen.getByText('Syncing')).toBeInTheDocument()
  })

  it('calls onReportPeriodChange when a period tab is clicked', () => {
    const onReportPeriodChange = vi.fn()
    render(<ReportsView {...baseProps({ onReportPeriodChange })} />)
    fireEvent.click(screen.getByRole('tab', { name: 'Last 7 days' }))
    expect(onReportPeriodChange).toHaveBeenCalledWith('7d')
  })

  it('renders the competitor pulse card only for a competitor-mode project', () => {
    const { rerender } = render(<ReportsView {...baseProps()} />)
    expect(screen.queryByTestId('competitor-pulse-card')).not.toBeInTheDocument()

    rerender(<ReportsView {...baseProps({ selectedProject: { ...PROJECT, mode: 'competitor' } })} />)
    expect(screen.getByTestId('competitor-pulse-card')).toBeInTheDocument()
  })

  it('switches to the analysis-run tab strip when runs are available and selected', () => {
    const runs = [{ id: 'run-1', sequence_number: 1, finished_at: '2026-01-01T00:00:00Z' }]
    render(<ReportsView {...baseProps({ projectRuns: runs, reportRunId: 'run-1' })} />)
    expect(screen.getByRole('tab', { name: 'Analysis run' })).toBeInTheDocument()
    // Appears twice by design: the run tab strip and the "Range" summary chip.
    expect(screen.getAllByText(/Pipeline #1:/).length).toBeGreaterThan(0)
  })
})
