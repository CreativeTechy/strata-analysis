import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import ArticleDetailPage from './ArticleDetailPage.jsx'
import { useAuth } from '../auth/useAuth.js'
import { getArticleAnalysis, removeArticleFromProject, restoreArticleToProject } from '../api/articlesApi.js'

vi.mock('../auth/useAuth.js', () => ({ useAuth: vi.fn() }))
vi.mock('../api/articlesApi.js', () => ({
  getArticleAnalysis: vi.fn(),
  reprocessArticle: vi.fn(),
  removeArticleFromProject: vi.fn(),
  restoreArticleToProject: vi.fn(),
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

  it('shows the remove-from-project button only when permitted', async () => {
    getArticleAnalysis.mockResolvedValue({
      analysis: { analysis_status: 'success', sentiment: 'positive', projects: [{ id: 7, name: 'Launch Watch' }] },
    })
    useAuth.mockReturnValue({ hasPermission: () => false })
    renderPage()
    await waitFor(() => expect(screen.getByText('Success')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /Remove from project/ })).not.toBeInTheDocument()
  })

  it('removes the article from its project and offers an undo, without navigating away', async () => {
    getArticleAnalysis.mockResolvedValue({
      analysis: {
        analysis_status: 'success', sentiment: 'positive', title: 'Battery fires spark recall',
        projects: [{ id: 7, name: 'Launch Watch' }],
      },
    })
    removeArticleFromProject.mockResolvedValue({ shared_with_other_projects: false })
    useAuth.mockReturnValue({ hasPermission: () => true })
    renderPage()
    await waitFor(() => expect(screen.getByText('Success')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: /Remove from project/ }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Remove from project' }))

    await waitFor(() => expect(removeArticleFromProject).toHaveBeenCalledWith('7', '1'))
    // Stays on the detail page - the article/analysis is untouched - and
    // offers an inline Undo instead of navigating back to the list.
    expect(screen.queryByText('Article library page')).not.toBeInTheDocument()
    expect(await screen.findByText(/Removed "Battery fires spark recall" from Launch Watch/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Undo' })).toBeInTheDocument()
  })

  it('restores the article to its project when Undo is clicked', async () => {
    getArticleAnalysis.mockResolvedValue({
      analysis: {
        analysis_status: 'success', sentiment: 'positive', title: 'Battery fires spark recall',
        projects: [{ id: 7, name: 'Launch Watch' }],
      },
    })
    removeArticleFromProject.mockResolvedValue({ shared_with_other_projects: false })
    restoreArticleToProject.mockResolvedValue({ ok: true })
    useAuth.mockReturnValue({ hasPermission: () => true })
    renderPage()
    await waitFor(() => expect(screen.getByText('Success')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: /Remove from project/ }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Remove from project' }))
    await screen.findByRole('button', { name: 'Undo' })

    fireEvent.click(screen.getByRole('button', { name: 'Undo' }))
    await waitFor(() => expect(restoreArticleToProject).toHaveBeenCalledWith('7', '1'))
    await waitFor(() => expect(screen.getByText(/Restored "Battery fires spark recall" to Launch Watch/)).toBeInTheDocument())
  })

  // Regression for F002: get_article_analysis returns null (and the route
  // 404s) for any backend failure, not just a genuinely missing article, so
  // this state is reachable for an article that still exists. Delete used to
  // stay clickable and confirm against a hardcoded "Untitled article".
  it('disables the remove-from-project button when the analysis failed to load', async () => {
    getArticleAnalysis.mockRejectedValue(new Error('network down'))
    useAuth.mockReturnValue({ hasPermission: () => true })
    renderPage()
    await waitFor(() => expect(screen.getByText('network down')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /Remove from project/ })).toBeDisabled()
  })

  it('disables the remove-from-project button when the article has no project links', async () => {
    getArticleAnalysis.mockResolvedValue({
      analysis: { analysis_status: 'success', sentiment: 'positive', projects: [] },
    })
    useAuth.mockReturnValue({ hasPermission: () => true })
    renderPage()
    await waitFor(() => expect(screen.getByText('Success')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /Remove from project/ })).toBeDisabled()
  })

  // Regression for F001/F003: the back link used to always go to a bare
  // /articles, discarding whatever search/filter state the operator had on
  // the list. It now returns to the location the list handed over via
  // router state.
  it('points the back link at the originating list location (not a bare /articles)', async () => {
    getArticleAnalysis.mockResolvedValue({
      analysis: { analysis_status: 'success', sentiment: 'positive', title: 'Battery fires spark recall' },
    })
    useAuth.mockReturnValue({ hasPermission: () => true })
    renderPage('1', { state: { from: '/articles?search=battery' } })
    await waitFor(() => expect(screen.getByText('Success')).toBeInTheDocument())

    expect(screen.getByRole('link', { name: /Back to Articles/ })).toHaveAttribute('href', '/articles?search=battery')
  })
})
