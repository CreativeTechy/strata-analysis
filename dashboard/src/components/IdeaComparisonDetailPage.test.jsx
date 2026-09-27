import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import IdeaComparisonDetailPage from './IdeaComparisonDetailPage.jsx'
import { useAuth } from '../auth/useAuth.js'
import { getIdeaComparison } from '../api/projectsApi.js'

vi.mock('../auth/useAuth.js', () => ({ useAuth: vi.fn() }))
vi.mock('../api/projectsApi.js', () => ({
  getIdeaComparison: vi.fn(),
  createIdeaComparisonFact: vi.fn(),
  deleteIdeaComparisonFact: vi.fn(),
  regenerateIdeaComparison: vi.fn(),
  updateIdeaComparisonFact: vi.fn(),
}))

const source = (index) => ({
  source_label: `Outlet ${index}`, title: `Source title ${index}`, value: `${index}%`,
  article_id: index, url: '', excerpt: '',
})
const fact = (id) => ({ id, fact_text: `Fact number ${id}`, observations: [] })
const group = (index, observations = [{
  id: `obs-${index}`, evidence_id: 'document-evidence-0', source_label: 'Outlet 0',
  display_value: '1', numeric_value: 1, origin: 'document',
}]) => ({
  id: `group-${index}`, metric: `Metric ${index}`, unit: '%', display_type: 'single',
  observations, minimum: 1, maximum: 1, spread: 0,
})

function comparison({ sources = 3, facts = 0, groups = [] } = {}) {
  return {
    idea: 'Oil output', diverges: true, summary: 'Summary', summary_stale: false,
    sources: Array.from({ length: sources }, (_, i) => source(i)),
    facts: Array.from({ length: facts }, (_, i) => fact(i + 1)),
    numeric_evidence: { groups },
  }
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/projects/1/idea-comparisons/9']}>
      <Routes>
        <Route path="/projects/:projectId/idea-comparisons/:clusterId" element={<IdeaComparisonDetailPage />} />
      </Routes>
    </MemoryRouter>
  )
}

const evidenceCard = () => screen.getByText('Document evidence').closest('article')
const factsCard = () => screen.getByText('User-provided facts').closest('article')

beforeEach(() => {
  useAuth.mockReturnValue({ hasPermission: () => false })
  Element.prototype.scrollIntoView = vi.fn()
})

describe('IdeaComparisonDetailPage pagination', () => {
  it('shows no pagination when every list fits on one page', async () => {
    getIdeaComparison.mockResolvedValue({ comparison: comparison({ sources: 3, facts: 2 }) })
    renderPage()
    await screen.findByText('Source title 2')
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument()
  })

  it('starts paging document evidence once there are more than 3 sources', async () => {
    getIdeaComparison.mockResolvedValue({ comparison: comparison({ sources: 4 }) })
    renderPage()
    await screen.findByText('Source title 0')
    const card = evidenceCard()
    expect(within(card).queryByText('Source title 3')).not.toBeInTheDocument()
    expect(within(card).getByText('Showing 1–3 of 4')).toBeInTheDocument()
    fireEvent.click(within(card).getByRole('button', { name: 'Next document evidence page' }))
    expect(within(card).getByText('Source title 3')).toBeInTheDocument()
    expect(within(card).getByText('Showing 4–4 of 4')).toBeInTheDocument()
  })

  it('pages document evidence and keeps the global numbering', async () => {
    getIdeaComparison.mockResolvedValue({ comparison: comparison({ sources: 8 }) })
    renderPage()
    await screen.findByText('Source title 0')
    const card = evidenceCard()
    expect(within(card).getByText('Source title 2')).toBeInTheDocument()
    expect(within(card).queryByText('Source title 3')).not.toBeInTheDocument()
    expect(within(card).getByText('Showing 1–3 of 8')).toBeInTheDocument()
    expect(within(card).getByRole('button', { name: 'Previous document evidence page' })).toBeDisabled()

    fireEvent.click(within(card).getByRole('button', { name: 'Next document evidence page' }))
    expect(within(card).getByText('Source title 3')).toBeInTheDocument()
    expect(within(card).queryByText('Source title 2')).not.toBeInTheDocument()
    expect(within(card).getByText('4')).toBeInTheDocument()
    expect(document.getElementById('document-evidence-3')).not.toBeNull()

    fireEvent.click(within(card).getByRole('button', { name: 'Next document evidence page' }))
    expect(within(card).getByText('Showing 7–8 of 8')).toBeInTheDocument()
    expect(within(card).getByText('Page 3 of 3')).toBeInTheDocument()
    expect(within(card).getByRole('button', { name: 'Next document evidence page' })).toBeDisabled()
  })

  it('pages user-provided facts once there are more than 3, independently of document evidence', async () => {
    getIdeaComparison.mockResolvedValue({ comparison: comparison({ sources: 8, facts: 4 }) })
    renderPage()
    await screen.findByText('Fact number 1')
    const card = factsCard()
    expect(within(card).getByText('Fact number 3')).toBeInTheDocument()
    expect(within(card).queryByText('Fact number 4')).not.toBeInTheDocument()
    expect(within(card).getByText('Showing 1–3 of 4')).toBeInTheDocument()
    fireEvent.click(within(card).getByRole('button', { name: 'Next user-provided facts page' }))
    expect(within(card).getByText('Fact number 4')).toBeInTheDocument()
    expect(within(card).queryByText('Fact number 1')).not.toBeInTheDocument()
    expect(within(evidenceCard()).getByText('Page 1 of 3')).toBeInTheDocument()
  })

  it('does not page the numbers section', async () => {
    getIdeaComparison.mockResolvedValue({ comparison: comparison({ groups: [0, 1, 2, 3].map((i) => group(i)) }) })
    renderPage()
    await screen.findByText('Metric 0')
    expect(screen.getByText('Metric 3')).toBeInTheDocument()
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument()
  })

  it('jumps to the page holding a user fact linked from the numbers section', async () => {
    const observations = [{
      id: 'obs-fact', evidence_id: 'user-fact-5', source_label: 'Team',
      display_value: '5%', numeric_value: 5, origin: 'user',
    }]
    getIdeaComparison.mockResolvedValue({ comparison: comparison({ facts: 5, groups: [group(0, observations)] }) })
    renderPage()
    await screen.findByText('Fact number 1')
    expect(document.getElementById('user-fact-5')).toBeNull()

    fireEvent.click(screen.getByText('5%').closest('a'))
    const row = document.getElementById('user-fact-5')
    expect(row).not.toBeNull()
    expect(row).toHaveClass('is-targeted')
    expect(within(factsCard()).getByText('Page 2 of 2')).toBeInTheDocument()
  })

  it('jumps to the page holding an evidence row linked from the numbers section', async () => {
    const observations = [{
      id: 'obs-late', evidence_id: 'document-evidence-8', source_label: 'Outlet 8',
      display_value: '8%', numeric_value: 8, origin: 'document',
    }]
    getIdeaComparison.mockResolvedValue({ comparison: comparison({ sources: 12, groups: [group(0, observations)] }) })
    renderPage()
    await screen.findByText('Source title 0')
    expect(document.getElementById('document-evidence-8')).toBeNull()

    fireEvent.click(screen.getByText('8%').closest('a'))
    const row = document.getElementById('document-evidence-8')
    expect(row).not.toBeNull()
    expect(row).toHaveClass('is-targeted')
    expect(within(evidenceCard()).getByText('Page 3 of 4')).toBeInTheDocument()
    expect(row.scrollIntoView).toHaveBeenCalled()
    expect(window.location.hash).toBe('#document-evidence-8')
  })
})
