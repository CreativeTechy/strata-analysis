import { describe, it, expect, vi, beforeEach } from 'vitest'
import { StrictMode } from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'
import ArticlesPage from './ArticlesPage'
import { useAuth } from '../auth/useAuth.js'
import {
  uploadDocuments,
  pollDocumentExtraction,
  pollArticleCandidates,
  listDocumentArticles,
  approveDocumentArticlesForDocuments,
} from '../api/projectDocumentsApi.js'

// Stands in for ArticleDetailPage: surfaces what onShowDetails actually
// navigated with (the destination's own search, plus the router `state.from`
// it carried) so a test can assert on it without rendering the real page.
function DetailPlaceholder() {
  const location = useLocation()
  return (
    <div>
      Article detail page
      <div data-testid="detail-search">{location.search}</div>
      <div data-testid="detail-from-state">{location.state?.from || ''}</div>
    </div>
  )
}

vi.mock('../auth/useAuth.js', () => ({ useAuth: vi.fn() }))
vi.mock('../api/projectDocumentsApi.js', () => ({
  uploadDocuments: vi.fn(),
  pollDocumentExtraction: vi.fn(() => Promise.resolve()),
  pollArticleCandidates: vi.fn(() => Promise.resolve([])),
  listDocumentArticles: vi.fn(() => Promise.resolve({ articles: [] })),
  approveDocumentArticlesForDocuments: vi.fn(() => Promise.resolve({ articles: [], run_id: null })),
  listDocuments: vi.fn(() => Promise.resolve({ documents: [] })),
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

// Surfaces the list route's own current location.search - the URL->router
// round trip that mirrors filters into the address bar (see ArticlesPage's
// URL-sync effect) lands one render after the filter state itself updates,
// so a test that wants to click Details right as a filter "lands" needs to
// wait on this rather than on the filtered result appearing.
function ListLocationWatcher() {
  const location = useLocation()
  return <div data-testid="list-search">{location.search}</div>
}

function renderPage(props = {}) {
  return render(
    <MemoryRouter initialEntries={['/articles']}>
      <ListLocationWatcher />
      <Routes>
        <Route
          path="/articles"
          element={<ArticlesPage project={null} projectId={null} projects={[{ id: 5, name: 'Riverside', status: 'active' }]} {...props} />}
        />
        <Route path="/articles/:articleId" element={<DetailPlaceholder />} />
      </Routes>
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

  it('navigates to the article detail page for an article', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('Battery fires spark recall')).toBeInTheDocument())
    fireEvent.click(screen.getAllByTitle('View analysis details')[0])
    await waitFor(() => expect(screen.getByText('Article detail page')).toBeInTheDocument())
  })

  // Regression for F001: the list used to unmount on the way to the detail
  // page with no memory of its own filters/search, so "Back to Articles"
  // landed on an unfiltered page 1. It now mirrors its live filters into the
  // URL and hands that URL to the detail page as router state.
  it('carries the current search/filter state to the article detail page for the back link to use', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('Battery fires spark recall')).toBeInTheDocument())

    fetch.mockImplementation((url) => {
      const href = String(url)
      if (href.startsWith('/api/articles?')) {
        if (href.includes('search=battery')) return Promise.resolve(jsonResponse({ articles: [ARTICLES[0]], total: 1 }))
        return Promise.resolve(jsonResponse({ articles: ARTICLES, total: ARTICLES.length }))
      }
      return Promise.resolve(jsonResponse({}))
    })
    fireEvent.change(screen.getByPlaceholderText('Search title, summary, source...'), { target: { value: 'battery' } })
    // Wait for the debounced search to actually land (not just any refetch -
    // only the mock's search=battery branch returns a single result)...
    await waitFor(() => expect(screen.getByText(/1 articles total/)).toBeInTheDocument(), { timeout: 2000 })
    // ...and then for the URL-sync effect's own render (one tick behind the
    // filtered result, since it round-trips through the router) to catch up,
    // so the click below is guaranteed to happen after it.
    await waitFor(() => expect(screen.getByTestId('list-search').textContent).toContain('search=battery'))

    fireEvent.click(screen.getAllByTitle('View analysis details')[0])
    await waitFor(() => expect(screen.getByText('Article detail page')).toBeInTheDocument())
    expect(screen.getByTestId('detail-from-state').textContent).toContain('search=battery')
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

  // Regression for F001/F002 in the SM-87 import rework: a truncated
  // .jsonl/.ndjson import (more records than the per-file cap) must not read
  // as a plain, unqualified success, and approving what was just uploaded
  // must be one batched call scoped to the uploaded documents - not one
  // request per candidate.
  it('surfaces a truncated import as a warning and approves the batch in one scoped call', async () => {
    render(
      <MemoryRouter initialEntries={['/articles?project_id=5']}>
        <Routes>
          <Route
            path="/articles"
            element={<ArticlesPage project={null} projectId={null} projects={[{ id: 5, name: 'Riverside', status: 'active' }]} />}
          />
        </Routes>
      </MemoryRouter>
    )
    await waitFor(() => expect(screen.getByText('Battery fires spark recall')).toBeInTheDocument())

    uploadDocuments.mockResolvedValue({ documents: [{ id: 101, original_filename: 'export.jsonl' }] })
    pollDocumentExtraction.mockResolvedValue([{ id: 101, status: 'processed' }])
    pollArticleCandidates.mockResolvedValue([{
      id: 101,
      original_filename: 'export.jsonl',
      status: 'processed',
      articles_status: 'ready',
      articles_error: 'Imported the first 5,000 of 20,000 records in this file. Split the file to import the rest.',
    }])
    listDocumentArticles.mockResolvedValue({
      articles: [
        { id: 1, document_id: 101, status: 'approved' },
        { id: 2, document_id: 101, status: 'approved' },
      ],
    })
    approveDocumentArticlesForDocuments.mockResolvedValue({ articles: [{ article_id: 1 }, { article_id: 2 }], run_id: 'run-1' })

    const file = new File(['{"title":"A","text":"one"}'], 'export.jsonl', { type: 'application/x-ndjson' })
    const [fileInput] = document.querySelectorAll('input[type="file"]')
    fireEvent.change(fileInput, { target: { files: [file] } })

    await waitFor(() =>
      expect(screen.getByText(/Added 2 articles from 1 file\./)).toBeInTheDocument()
    )
    // The truncation note travels with the success message rather than being
    // dropped just because the document itself didn't fail outright.
    expect(screen.getByText(/Imported the first 5,000 of 20,000 records/)).toBeInTheDocument()

    // One call for the whole batch, scoped to just the uploaded document -
    // not one setDocumentArticleStatus call per candidate.
    expect(approveDocumentArticlesForDocuments).toHaveBeenCalledTimes(1)
    expect(approveDocumentArticlesForDocuments).toHaveBeenCalledWith('5', [101])
  })

  // Regression for F004: React StrictMode (which main.jsx wraps the whole
  // app in) double-invokes a fresh mount's effects with identical deps, to
  // surface exactly this kind of bug. An earlier version of the offset-reset
  // guard used an invocation-count ref ("have I run once?"), which treated
  // that harmless second invocation as a real subsequent change and zeroed
  // an offset just restored from the URL right back out - on every single
  // mount in dev, including the remount that happens when returning from the
  // article detail page. It's plain `render()`, not wrapped in StrictMode,
  // everywhere else in this file specifically because that's what let this
  // regression slip through once already.
  it('does not reset an offset restored from the URL under React StrictMode', async () => {
    fetch.mockImplementation((url) => {
      const href = String(url)
      if (href.startsWith('/api/articles?')) return Promise.resolve(jsonResponse({ articles: ARTICLES, total: 50 }))
      return Promise.resolve(jsonResponse({}))
    })
    render(
      <StrictMode>
        <MemoryRouter initialEntries={['/articles?offset=48']}>
          <Routes>
            <Route
              path="/articles"
              element={<ArticlesPage project={null} projectId={null} projects={[{ id: 5, name: 'Riverside', status: 'active' }]} />}
            />
          </Routes>
        </MemoryRouter>
      </StrictMode>
    )
    await waitFor(() => expect(screen.getByText('Battery fires spark recall')).toBeInTheDocument())
    // Give any spurious extra effect invocation a chance to fire its own
    // fetch before asserting none of them ever asked for offset=0.
    await new Promise((resolve) => setTimeout(resolve, 100))
    const offsetsRequested = fetch.mock.calls
      .map(([url]) => String(url))
      .filter((href) => href.startsWith('/api/articles?'))
      .map((href) => new URL(href, 'http://localhost').searchParams.get('offset'))
    expect(offsetsRequested.every((offset) => offset === '48')).toBe(true)
  })
})
