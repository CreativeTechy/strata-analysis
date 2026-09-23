import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import SourcesPage from './SourcesPage'
import { useAuth } from '../auth/useAuth.js'

vi.mock('../auth/useAuth.js', () => ({ useAuth: vi.fn() }))

const PROJECTS = [
  { id: 1, name: 'Project A' },
  { id: 2, name: 'Project B' },
]

function jsonResponse(body) {
  return { ok: true, json: async () => body }
}

function sourcesPayload(count, offset = 0) {
  return {
    sources: Array.from({ length: Math.max(0, Math.min(count, 20) - offset) }, (_, i) => ({
      key: `doc:${offset + i}`, type: 'document', label: `Source ${offset + i}`, url: null,
      article_count: 1, latest_published_at: null, articles: [],
      trust: { tier: 'unknown', reason: null, set_by: null, updated_at: null, is_default: true },
    })),
    total: count,
    total_articles: count,
  }
}

function renderPage() {
  return render(
    <MemoryRouter>
      <SourcesPage projectId={null} projects={PROJECTS} />
    </MemoryRouter>
  )
}

describe('SourcesPage', () => {
  let fetchMock
  let requestedOffsets

  beforeEach(() => {
    useAuth.mockReturnValue({ hasPermission: () => true })
    requestedOffsets = []
    fetchMock = vi.fn((url, options) => {
      const href = String(url)
      const match = href.match(/\/api\/projects\/(\d+)\/sources\?limit=(\d+)&offset=(\d+)/)
      if (match) {
        const [, projectId, , offset] = match
        requestedOffsets.push({ projectId: Number(projectId), offset: Number(offset) })
        // Project B only has 3 sources - a request at a stale offset > 3
        // would otherwise return an empty page indistinguishable from
        // "no sources".
        const count = Number(projectId) === 1 ? 25 : 3
        return Promise.resolve(jsonResponse(sourcesPayload(count, Number(offset))))
      }
      if (href.match(/\/api\/projects\/\d+\/sources\/trust$/) && options?.method === 'POST') {
        const body = JSON.parse(options.body)
        return Promise.resolve(jsonResponse({
          tier: body.tier, reason: body.reason, set_by: 'tester', updated_at: '2026-01-01T00:00:00Z', is_default: false,
        }))
      }
      return Promise.resolve(jsonResponse({}))
    })
    vi.stubGlobal('fetch', fetchMock)
  })

  it('never fetches with a stale offset when switching projects mid-pagination', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('Source 0')).toBeInTheDocument())

    // Move to page 2 of Project A (offset=20).
    fireEvent.click(screen.getByRole('button', { name: /next/i }))
    await waitFor(() => expect(requestedOffsets).toContainEqual({ projectId: 1, offset: 20 }))

    requestedOffsets.length = 0
    fireEvent.change(screen.getByLabelText('Project'), { target: { value: '2' } })

    await waitFor(() => expect(screen.getByText('Source 0')).toBeInTheDocument())

    // Exactly one request for Project B, and it must be at offset=0 - never
    // a request carrying the stale offset=20 left over from Project A.
    const projectBRequests = requestedOffsets.filter((r) => r.projectId === 2)
    expect(projectBRequests).toEqual([{ projectId: 2, offset: 0 }])
    expect(screen.queryByText('No sources yet')).not.toBeInTheDocument()
  })

  it('shows each source\'s trust tier and lets an operator set a new one', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('Source 0')).toBeInTheDocument())

    // Defaults to "not yet assessed" (unknown), not "untrusted" - the two
    // must never look the same.
    expect(screen.getAllByText('Not yet assessed').length).toBeGreaterThan(0)

    fireEvent.click(screen.getAllByRole('button', { name: 'Set trust' })[0])
    fireEvent.change(screen.getByLabelText('Trust tier'), { target: { value: 'trusted' } })
    fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'Verified the publisher directly.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save trust tier' }))

    await waitFor(() => expect(screen.getByText('Trusted')).toBeInTheDocument())

    const trustCall = fetchMock.mock.calls.find(([url]) => String(url).match(/\/sources\/trust$/))
    expect(trustCall).toBeTruthy()
    const [, options] = trustCall
    expect(JSON.parse(options.body)).toEqual({
      key: 'doc:0', type: 'document', tier: 'trusted', reason: 'Verified the publisher directly.',
    })
  })

  it('hides the trust editor for a user without projects.update', async () => {
    useAuth.mockReturnValue({ hasPermission: () => false })
    renderPage()
    await waitFor(() => expect(screen.getByText('Source 0')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Set trust' })).not.toBeInTheDocument()
  })
})
