import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import ImportProgressBanner from './ImportProgressBanner.jsx'

describe('ImportProgressBanner', () => {
  it('shows a determinate progress bar and counts while running', () => {
    render(<ImportProgressBanner run={{ status: 'running', total_lines: 100, processed: 40, saved: 38 }} onDismiss={vi.fn()} />)
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '40')
    expect(screen.getByText('38 saved')).toBeInTheDocument()
  })

  it('shows an indeterminate bar when there is no line count yet', () => {
    render(<ImportProgressBanner run={{ status: 'running', saved: 0 }} onDismiss={vi.fn()} />)
    expect(screen.getByRole('progressbar')).not.toHaveAttribute('aria-valuenow')
  })

  it('offers a dismiss button only once the run is done', () => {
    const { rerender } = render(<ImportProgressBanner run={{ status: 'running' }} onDismiss={vi.fn()} />)
    expect(screen.queryByLabelText('Dismiss import summary')).not.toBeInTheDocument()

    rerender(<ImportProgressBanner run={{ status: 'success' }} onDismiss={vi.fn()} />)
    expect(screen.getByLabelText('Dismiss import summary')).toBeInTheDocument()
  })

  it('calls onDismiss when the dismiss button is clicked', () => {
    const onDismiss = vi.fn()
    render(<ImportProgressBanner run={{ status: 'failed' }} onDismiss={onDismiss} />)
    fireEvent.click(screen.getByLabelText('Dismiss import summary'))
    expect(onDismiss).toHaveBeenCalled()
  })

  it('lists up to 5 errors and summarizes the rest', () => {
    const errors = Array.from({ length: 7 }, (_, i) => ({ line: i + 1, error: 'bad json' }))
    render(<ImportProgressBanner run={{ status: 'failed', errors }} onDismiss={vi.fn()} />)
    expect(screen.getAllByText(/bad json/).length).toBe(5)
    expect(screen.getByText('and 2 more...')).toBeInTheDocument()
  })
})
