import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import ReportsView from './ReportsView.jsx'
import { exportReportSummaryPdf } from '../api/projectsApi.js'

vi.mock('./StatsOverview', () => ({ default: () => <div data-testid="stats-overview" /> }))
vi.mock('./CompetitorPulseCard.jsx', () => ({ default: () => <div data-testid="competitor-pulse-card" /> }))
vi.mock('../api/projectsApi.js', () => ({ exportReportSummaryPdf: vi.fn() }))

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

describe('ReportsView - Export Summary', () => {
  let createObjectURL
  let revokeObjectURL

  beforeEach(() => {
    exportReportSummaryPdf.mockReset()
    createObjectURL = vi.fn(() => 'blob:mock-url')
    revokeObjectURL = vi.fn()
    vi.stubGlobal('URL', { ...URL, createObjectURL, revokeObjectURL })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows a preparing state and downloads the PDF on success', async () => {
    let resolveExport
    exportReportSummaryPdf.mockReturnValue(new Promise((resolve) => { resolveExport = resolve }))
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    render(<ReportsView {...baseProps()} />)
    fireEvent.click(screen.getByRole('button', { name: /Export Summary/i }))

    expect(await screen.findByText('Preparing...')).toBeInTheDocument()
    expect(exportReportSummaryPdf).toHaveBeenCalledWith(1, { period: '30d', run_id: undefined })

    const fakeBlob = new Blob(['%PDF-1.7'], { type: 'application/pdf' })
    resolveExport(fakeBlob)

    await waitFor(() => expect(screen.getByRole('button', { name: /Export Summary/i })).not.toBeDisabled())
    expect(createObjectURL).toHaveBeenCalledWith(fakeBlob)
    expect(clickSpy).toHaveBeenCalled()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:mock-url')
    clickSpy.mockRestore()
  })

  it('passes the selected run id instead of the period when a run is selected', async () => {
    exportReportSummaryPdf.mockResolvedValue(new Blob(['%PDF-1.7']))
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    render(<ReportsView {...baseProps({ reportRunId: 'run-42' })} />)
    fireEvent.click(screen.getByRole('button', { name: /Export Summary/i }))

    await waitFor(() => expect(exportReportSummaryPdf).toHaveBeenCalledWith(1, { period: '30d', run_id: 'run-42' }))
  })

  it('shows an error message when the export fails, without crashing', async () => {
    exportReportSummaryPdf.mockRejectedValue(new Error('Report generation failed'))

    render(<ReportsView {...baseProps()} />)
    fireEvent.click(screen.getByRole('button', { name: /Export Summary/i }))

    expect(await screen.findByText('Report generation failed')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Export Summary/i })).not.toBeDisabled()
  })

  it('disables the export button when there are no analyzed articles in scope', () => {
    render(<ReportsView {...baseProps({ intelligence: { total: 0 } })} />)
    expect(screen.getByRole('button', { name: /Export Summary/i })).toBeDisabled()
  })

  it('prevents a duplicate request while one is already in flight', async () => {
    let resolveExport
    exportReportSummaryPdf.mockReturnValue(new Promise((resolve) => { resolveExport = resolve }))
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    render(<ReportsView {...baseProps()} />)
    const button = screen.getByRole('button', { name: /Export Summary/i })
    fireEvent.click(button)
    fireEvent.click(button)
    fireEvent.click(button)

    resolveExport(new Blob(['%PDF-1.7']))
    await waitFor(() => expect(button).not.toBeDisabled())
    expect(exportReportSummaryPdf).toHaveBeenCalledTimes(1)
  })
})
