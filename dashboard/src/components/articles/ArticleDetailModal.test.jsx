import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import ArticleDetailModal from './ArticleDetailModal.jsx'

function baseProps(overrides = {}) {
  return {
    open: true,
    canReprocess: false,
    loading: false,
    error: '',
    data: null,
    actionMessage: '',
    reprocessing: false,
    checkingCoverage: false,
    onClose: vi.fn(),
    onReprocess: vi.fn(),
    onCheckCoverage: vi.fn(),
    ...overrides,
  }
}

describe('ArticleDetailModal', () => {
  it('shows a loading message while fetching', () => {
    render(<ArticleDetailModal {...baseProps({ loading: true })} />)
    expect(screen.getByText('Loading analysis details...')).toBeInTheDocument()
  })

  it('shows the error message on failure', () => {
    render(<ArticleDetailModal {...baseProps({ error: 'network down' })} />)
    expect(screen.getByText('network down')).toBeInTheDocument()
  })

  it('renders the sentiment, category, and tone fields from the analysis data', () => {
    render(<ArticleDetailModal {...baseProps({
      data: {
        analysis_status: 'success', sentiment: 'positive', article_category: 'review',
        writer_tone: 'enthusiastic', article_tone: 'skeptical', overall_tone: 'mixed',
        confidence: { sentiment: 0.9 },
      },
    })} />)
    expect(screen.getByText('Success')).toBeInTheDocument()
    expect(screen.getByText('Review')).toBeInTheDocument()
    expect(screen.getByText('Enthusiastic')).toBeInTheDocument()
    expect(screen.getByText('Skeptical')).toBeInTheDocument()
    expect(screen.getByText('Mixed')).toBeInTheDocument()
    expect(screen.getByText(/confidence 90%/)).toBeInTheDocument()
  })

  it('renders the region with its confidence', () => {
    render(<ArticleDetailModal {...baseProps({
      data: {
        analysis_status: 'success', sentiment: 'positive', article_category: 'review',
        writer_tone: 'enthusiastic', article_tone: 'skeptical', overall_tone: 'mixed',
        region: 'United States',
        confidence: { region: 0.9 },
      },
    })} />)
    expect(screen.getByText('United States')).toBeInTheDocument()
    expect(screen.getByText(/confidence 90%/)).toBeInTheDocument()
  })

  it('shows the reprocess button only when canReprocess is true', () => {
    const { rerender } = render(<ArticleDetailModal {...baseProps({ canReprocess: false })} />)
    expect(screen.queryByRole('button', { name: 'Reprocess' })).not.toBeInTheDocument()

    rerender(<ArticleDetailModal {...baseProps({
      canReprocess: true,
      data: {
        analysis_status: 'success', sentiment: 'neutral', article_category: 'general_article',
        writer_tone: 'neutral', article_tone: 'neutral', overall_tone: 'neutral',
      },
    })} />)
    expect(screen.getByRole('button', { name: 'Reprocess' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Check cross-source coverage' })).toBeInTheDocument()
  })

  it('shows cross-source coverage with evidence and its limitation', () => {
    render(<ArticleDetailModal {...baseProps({
      data: {
        analysis_status: 'success', sentiment: 'neutral', article_category: 'general_article',
        writer_tone: 'neutral', article_tone: 'neutral', overall_tone: 'neutral',
        coverage_evidence: {
          status: 'some_coverage', reason: 'Closely matching coverage was found on 1 other domain.',
          caveat: 'Cross-source coverage is not proof that a claim is true.',
          matches: [{ domain: 'news.example', title: 'Matching report', url: 'https://news.example/report' }],
        },
      },
    })} />)
    expect(screen.getByText(/Some matching coverage/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /news\.example/ })).toHaveAttribute('href', 'https://news.example/report')
    expect(screen.getByText(/not proof/)).toBeInTheDocument()
  })
})
