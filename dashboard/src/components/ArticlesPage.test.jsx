import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import ArticlesPage from './ArticlesPage'
import { useAuth } from '../auth/useAuth.js'

vi.mock('../auth/useAuth.js', () => ({ useAuth: vi.fn() }))
vi.mock('../api/projectDocumentsApi.js', () => ({
  uploadDocuments: vi.fn(),
  pollDocumentExtraction: vi.fn(() => Promise.resolve()),
  pollArticleCandidates: vi.fn(() => Promise.resolve([])),
  listDocumentArticles: vi.fn(() => Promise.resolve({ articles: [] })),
  setDocumentArticleStatus: vi.fn(),
}))

const ARTICLES = [
  {
    id: 1, url: 'https://example.com/a', title: 'Battery fires spark recall', source: 'Example News',
    sentiment: 'negative', published: '2026-01-10T00:00:00Z', fetched_at: '2026-01-11T00:00:00Z',
    summary: 'A recall over battery fires.', article_category: 'safety',
  },
  {
    id: 2, url: 'https://example.com/b', title: 'New charging network opens', source: 'Example Wire',
    sentiment: 'positive', published: '2026-01-09T00:00:00Z', fetched_at: '2026-01-10T00:00:00Z',
    summary: 'A new charging network.', article_category: 'infrastructure',
  },
]

function jsonResponse(body) {
  return { ok: true, json: async () => body }
}

function renderPage(props = {}) {
  return render(
    <MemoryRouter>
      <ArticlesPage project={null} projectId={null} projects={[{ id: 5, name: 'Riverside', status: 'active' }]} {...props} />
    </MemoryRouter>
  )
}

beforeEach(() => {
  useAuth.mockReturnValue({ hasPermission: () => true })
  vi.stubGlobal('fetch', vi.fn((url) => {
    const href = String(url)
    if (href.startsWith('/api/articles?')) {
      return Promise.resolve(jsonResponse({ articles: ARTICLES, total: ARTICLES.length }))
    }
    if (href.includes('/documents')) {
      return Promise.resolve(jsonResponse({ documents: [] }))
    }
    if (href.includes('/analysis')) {
      return Promise.resolve(jsonResponse({ analysis: { sentiment: 'negative', analysis_status: 'success' } }))
    }
    return Promise.resolve(jsonResponse({}))
  }))
})

describe('ArticlesPage', () => {
  it('lists the loaded articles', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('Battery fires spark recall')).toBeInTheDocument())
    expect(screen.getByText('New charging network opens')).toBeInTheDocument()
  })

  it('shows the total count once loaded', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText(/2 articles total/)).toBeInTheDocument())
  })

  it('filters by typing in the search box (debounced)', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('Battery fires spark recall')).toBeInTheDocument())

    fetch.mockImplementation((url) => {
      const href = String(url)
      if (href.startsWith('/api/articles?')) {
        expect(href).toContain('search=battery')
        return Promise.resolve(jsonResponse({ articles: [ARTICLES[0]], total: 1 }))
      }
      return Promise.resolve(jsonResponse({}))
    })
    fireEvent.change(screen.getByPlaceholderText('Search title, summary, source...'), { target: { value: 'battery' } })
    await waitFor(() => expect(screen.getByText(/1 articles total/)).toBeInTheDocument(), { timeout: 2000 })
  })

  it('opens the analysis detail modal for an article', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('Battery fires spark recall')).toBeInTheDocument())
    fireEvent.click(screen.getAllByTitle('View analysis details')[0])
    const dialog = await screen.findByRole('dialog')
    await waitFor(() => expect(within(dialog).getByText('Negative')).toBeInTheDocument())
  })

  it('does not attach a delayed coverage response to another article', async () => {
    const originalFetch = fetch.getMockImplementation()
    let finishCoverage
    fetch.mockImplementation((url, ...args) => String(url).endsWith('/coverage')
      ? new Promise((resolve) => { finishCoverage = resolve })
      : originalFetch(url, ...args))
    renderPage()
    await screen.findByText('Battery fires spark recall')
    fireEvent.click(screen.getAllByTitle('View analysis details')[0])
    fireEvent.click(await screen.findByRole('button', { name: 'Check source reliability signals' }))
    fireEvent.click(screen.getByRole('button', { name: 'Close dialog' }))
    fireEvent.click(screen.getAllByTitle('View analysis details')[1])
    await screen.findByText('Not assessed', { selector: 'div' })
    await act(async () => {
      finishCoverage(jsonResponse({ article_id: 1, coverage: { status: 'some_coverage', reason: 'Result for first article' } }))
    })
    expect(screen.queryByText('Result for first article')).not.toBeInTheDocument()
    expect(screen.getByText('Not assessed', { selector: 'div' })).toBeInTheDocument()
  })

  it('shows an empty state when there are no articles', async () => {
    fetch.mockImplementation((url) => {
      const href = String(url)
      if (href.startsWith('/api/articles?')) return Promise.resolve(jsonResponse({ articles: [], total: 0 }))
      return Promise.resolve(jsonResponse({}))
    })
    renderPage()
    await waitFor(() => expect(screen.getByText('No articles found')).toBeInTheDocument())
  })

  it('switches between card and list view', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('Battery fires spark recall')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('tab', { name: /List/ }))
    expect(screen.getByRole('tab', { name: /List/ })).toHaveAttribute('aria-selected', 'true')
  })
})
