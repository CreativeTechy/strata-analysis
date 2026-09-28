import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import IntelligenceEmptyState, { PendingAnalysisNotice } from './IntelligenceEmptyState.jsx'
import { resolveIntelligenceState } from '../lib/intelligenceState.js'
import { useAuth } from '../auth/useAuth.js'
import { startAnalysisRun } from '../api/pipelineRunsApi.js'

vi.mock('../auth/useAuth.js', () => ({ useAuth: vi.fn() }))
vi.mock('../api/pipelineRunsApi.js', () => ({ startAnalysisRun: vi.fn() }))

const PROJECT = { id: 7, name: 'Acme', mode: 'sentiment' }

function stateFor(coverage, extra = {}) {
  return resolveIntelligenceState({
    total: 0,
    ...extra,
    coverage: { documents: 0, documents_in_progress: 0, articles: 0, analyzed: 0, pending: 0, failed: 0, active_run: null, ...coverage },
  })
}

function renderState(props) {
  return render(<MemoryRouter><IntelligenceEmptyState project={PROJECT} {...props} /></MemoryRouter>)
}

function grant(...permissions) {
  useAuth.mockReturnValue({ hasPermission: (...required) => required.every((p) => permissions.includes(p)) })
}

describe('IntelligenceEmptyState', () => {
  beforeEach(() => {
    startAnalysisRun.mockReset()
    grant('projects.update', 'pipeline.run')
  })

  it('offers an upload link when the project has no documents', () => {
    renderState({ state: stateFor({}) })
    expect(screen.getByText('No documents uploaded yet')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Upload documents/ })).toHaveAttribute('href', '/projects/7/edit')
  })

  it('sends competitor studies to their own documents page', () => {
    grant('competitors.manage')
    renderState({ state: stateFor({}), project: { id: 9, mode: 'competitor' } })
    expect(screen.getByRole('link', { name: /Upload documents/ })).toHaveAttribute('href', '/competitors/9/documents')
  })

  it('explains who can upload when the viewer cannot', () => {
    grant()
    renderState({ state: stateFor({}) })
    expect(screen.queryByRole('link', { name: /Upload documents/ })).not.toBeInTheDocument()
    expect(screen.getByText(/Ask a project manager/)).toBeInTheDocument()
  })

  it('links to the active run while analysis is in progress', () => {
    renderState({ state: stateFor({ documents: 1, articles: 3, pending: 3, active_run: { id: 'run-5', status: 'running' } }, { total: 3 }) })
    expect(screen.getByText('Analysis in progress')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /View run progress/ })).toHaveAttribute('href', '/pipeline-runs/run-5')
  })

  it('starts a pending-scope analysis run and reports back', async () => {
    startAnalysisRun.mockResolvedValue({ run_id: 'run-6' })
    const onAnalysisStarted = vi.fn()
    renderState({ state: stateFor({ documents: 1, articles: 3, pending: 3 }, { total: 3 }), onAnalysisStarted })
    expect(screen.getByText('3 articles are waiting to be analyzed. Start an analysis run to populate this view.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Start analysis/ }))
    await waitFor(() => expect(onAnalysisStarted).toHaveBeenCalled())
    expect(startAnalysisRun).toHaveBeenCalledWith({ project_id: 7, scope: 'pending' })
  })

  it('shows the error when starting a run fails', async () => {
    startAnalysisRun.mockRejectedValue(new Error('Model host unreachable'))
    renderState({ state: stateFor({ documents: 1, articles: 3, failed: 3 }, { total: 3 }) })
    fireEvent.click(screen.getByRole('button', { name: /Retry analysis/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Model host unreachable')
  })

  it('offers to widen the range when the scope is empty but the project has results', () => {
    const onShowAllTime = vi.fn()
    renderState({ state: stateFor({ documents: 1, articles: 5, analyzed: 5 }), rangeLabel: 'Last 7 days', onShowAllTime })
    expect(screen.getByText('No results in this range')).toBeInTheDocument()
    expect(screen.getByText(/none fall within the selected range \(Last 7 days\)/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Show all time/ }))
    expect(onShowAllTime).toHaveBeenCalled()
  })
})

describe('PendingAnalysisNotice', () => {
  beforeEach(() => grant('pipeline.run'))

  it('renders nothing when nothing is pending', () => {
    const { container } = render(<MemoryRouter><PendingAnalysisNotice state={stateFor({ articles: 3, analyzed: 3 }, { total: 3 })} project={PROJECT} /></MemoryRouter>)
    expect(container).toBeEmptyDOMElement()
  })

  it('warns that figures will change while articles are still pending', () => {
    render(<MemoryRouter><PendingAnalysisNotice state={stateFor({ articles: 5, analyzed: 3, pending: 2, active_run: { id: 'run-1' } }, { total: 5 })} project={PROJECT} /></MemoryRouter>)
    expect(screen.getByRole('status')).toHaveTextContent('2 articles are still waiting for analysis')
    expect(screen.getByRole('link', { name: 'View progress' })).toHaveAttribute('href', '/pipeline-runs/run-1')
  })
})
