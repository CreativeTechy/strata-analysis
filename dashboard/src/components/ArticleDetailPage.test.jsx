import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import ArticleDetailPage from './ArticleDetailPage.jsx'
import { useAuth } from '../auth/useAuth.js'
import { getArticleAnalysis, deleteArticle } from '../api/articlesApi.js'

vi.mock('../auth/useAuth.js', () => ({ useAuth: vi.fn() }))
vi.mock('../api/articlesApi.js', () => ({
  getArticleAnalysis: vi.fn(),
  reprocessArticle: vi.fn(),
  deleteArticle: vi.fn(),
}))

function renderPage(articleId = '1', { state } = {}) {
  return render(
    <MemoryRouter initialEntries={[{ pathname: `/articles/${articleId}`, state }]}>
      <Routes>
        <Route path="/articles/:articleId" element={<ArticleDetailPage />} />
        <Route path="/articles" element={<div>Article library page</div>} />
      </Routes>
    </MemoryRouter>
  )
}

beforeEach(() => {
  useAuth.mockReturnValue({ hasPermission: () => false })
})

describe('ArticleDetailPage', () => {
  it('shows a loading message while fetching', async () => {
    getArticleAnalysis.mockReturnValue(new Promise(() => {}))
    renderPage()
    expect(screen.getByText('Loading analysis details...')).toBeInTheDocument()
  })

  it('shows the error message on failure', async () => {
    getArticleAnalysis.mockRejectedValue(new Error('network down'))
    renderPage()
    await waitFor(() => expect(screen.getByText('network down')).toBeInTheDocument())
  })

  it('renders the sentiment, category, and tone fields from the analysis data', async () => {
    getArticleAnalysis.mockResolvedValue({
      analysis: {
        analysis_status: 'success', sentiment: 'positive', article_category: 'review',
        writer_tone: 'enthusiastic', article_tone: 'skeptical', overall_tone: 'mixed',
        confidence: { sentiment: 0.9 },
      },
    })
    renderPage()
    await waitFor(() => expect(screen.getByText('Success')).toBeInTheDocument())
    expect(screen.getByText('Review')).toBeInTheDocument()
    expect(screen.getByText('Enthusiastic')).toBeInTheDocument()
    expect(screen.getByText('Skeptical')).toBeInTheDocument()
    expect(screen.getByText('Mixed')).toBeInTheDocument()
    expect(screen.getByText(/confidence 90%/)).toBeInTheDocument()
  })

  it('renders the region with its confidence', async () => {
    getArticleAnalysis.mockResolvedValue({
      analysis: {
        analysis_status: 'success', sentiment: 'positive', article_category: 'review',
        writer_tone: 'enthusiastic', article_tone: 'skeptical', overall_tone: 'mixed',
        region: 'United States',
        confidence: { region: 0.9 },
      },
    })
    renderPage()
    await waitFor(() => expect(screen.getByText('United States')).toBeInTheDocument())
    expect(screen.getByText(/confidence 90%/)).toBeInTheDocument()
  })

  it('shows the reprocess button only when permitted', async () => {
    getArticleAnalysis.mockResolvedValue({ analysis: { analysis_status: 'success', sentiment: 'positive' } })
    useAuth.mockReturnValue({ hasPermission: () => false })
    const { rerender } = renderPage()
    await waitFor(() => expect(screen.getByText('Success')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Reprocess' })).not.toBeInTheDocument()

    useAuth.mockReturnValue({ hasPermission: () => true })
    rerender(
      <MemoryRouter initialEntries={['/articles/1']}>
        <Routes>
          <Route path="/articles/:articleId" element={<ArticleDetailPage />} />
        </Routes>
      </MemoryRouter>
    )
    await waitFor(() => expect(screen.getByRole('button', { name: 'Reprocess' })).toBeInTheDocument())
  })

  it('renders the full article text for reading', async () => {
    getArticleAnalysis.mockResolvedValue({
      analysis: { analysis_status: 'success', sentiment: 'positive', text: 'The full body of the article goes here.' },
    })
    renderPage()
    await waitFor(() => expect(screen.getByText('Full article')).toBeInTheDocument())
    expect(screen.getByText('The full body of the article goes here.')).toBeInTheDocument()
  })

  it('shows the delete button only when permitted', async () => {
    getArticleAnalysis.mockResolvedValue({ analysis: { analysis_status: 'success', sentiment: 'positive' } })
    useAuth.mockReturnValue({ hasPermission: () => false })
    renderPage()
    await waitFor(() => expect(screen.getByText('Success')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /Delete/ })).not.toBeInTheDocument()
  })

  it('deletes the article and returns to the article library', async () => {
    getArticleAnalysis.mockResolvedValue({ analysis: { analysis_status: 'success', sentiment: 'positive', title: 'Battery fires spark recall' } })
    deleteArticle.mockResolvedValue({})
    useAuth.mockReturnValue({ hasPermission: () => true })
    renderPage()
    await waitFor(() => expect(screen.getByText('Success')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: /Delete/ }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete article' }))

    await waitFor(() => expect(deleteArticle).toHaveBeenCalledWith('1'))
    await waitFor(() => expect(screen.getByText('Article library page')).toBeInTheDocument())
  })

  // Regression for F002: get_article_analysis returns null (and the route
  // 404s) for any backend failure, not just a genuinely missing article, so
  // this state is reachable for an article that still exists. Delete used to
  // stay clickable and confirm against a hardcoded "Untitled article".
  it('disables the delete button when the analysis failed to load', async () => {
    getArticleAnalysis.mockRejectedValue(new Error('network down'))
    useAuth.mockReturnValue({ hasPermission: () => true })
    renderPage()
    await waitFor(() => expect(screen.getByText('network down')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /Delete/ })).toBeDisabled()
  })

  // Regression for F001/F003: the back link and the post-delete redirect
  // used to always go to a bare /articles, discarding whatever search/filter
  // state the operator had on the list. They now return to the location the
  // list handed over via router state, and do so with history replacement so
  // Back from the list can't land on the just-deleted article's dead page.
  it('returns to the originating list location (not a bare /articles) after deleting', async () => {
    getArticleAnalysis.mockResolvedValue({ analysis: { analysis_status: 'success', sentiment: 'positive', title: 'Battery fires spark recall' } })
    deleteArticle.mockResolvedValue({})
    useAuth.mockReturnValue({ hasPermission: () => true })
    renderPage('1', { state: { from: '/articles?search=battery' } })
    await waitFor(() => expect(screen.getByText('Success')).toBeInTheDocument())

    expect(screen.getByRole('link', { name: /Back to Articles/ })).toHaveAttribute('href', '/articles?search=battery')

    fireEvent.click(screen.getByRole('button', { name: /Delete/ }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete article' }))

    await waitFor(() => expect(deleteArticle).toHaveBeenCalledWith('1'))
    await waitFor(() => expect(screen.getByText('Article library page')).toBeInTheDocument())
  })
})
