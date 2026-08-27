import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import {
  prettyLabel,
  articleDate,
  addedAtLabel,
  formatMatchScore,
  confidencePct,
  highlightMatches,
  getPageNumbers,
} from './articleHelpers.jsx'

describe('prettyLabel', () => {
  it('replaces underscores with spaces and title-cases each word', () => {
    expect(prettyLabel('general_article')).toBe('General Article')
  })

  it('handles a missing value', () => {
    expect(prettyLabel(null)).toBe('')
  })
})

describe('articleDate', () => {
  it('returns "Unknown date" for a missing value', () => {
    expect(articleDate(null)).toBe('Unknown date')
  })

  it('falls back to the raw value when unparsable', () => {
    expect(articleDate('garbage')).toBe('garbage')
  })

  it('formats a valid date', () => {
    expect(articleDate('2026-01-15T00:00:00Z')).toEqual(expect.any(String))
  })
})

describe('addedAtLabel', () => {
  it('returns "Unknown" for a missing value', () => {
    expect(addedAtLabel(null)).toBe('Unknown')
  })
})

describe('formatMatchScore', () => {
  it('formats a numeric score to two decimals', () => {
    expect(formatMatchScore(0.8234)).toBe('0.82')
  })

  it('returns an empty string for a non-numeric value', () => {
    expect(formatMatchScore(undefined)).toBe('')
    expect(formatMatchScore('n/a')).toBe('')
  })
})

describe('confidencePct', () => {
  it('formats a fraction as a rounded percentage', () => {
    expect(confidencePct(0.876)).toBe('88%')
  })

  it('returns null for a non-numeric value', () => {
    expect(confidencePct(undefined)).toBeNull()
    expect(confidencePct('n/a')).toBeNull()
  })
})

describe('highlightMatches', () => {
  it('returns the plain text unchanged when there is no search term', () => {
    expect(highlightMatches('Stellantis battery recall', '')).toBe('Stellantis battery recall')
  })

  it('wraps every token of a multi-word search separately', () => {
    const { container } = render(<div>{highlightMatches('Stellantis battery recall', 'battery recall')}</div>)
    const marks = container.querySelectorAll('mark.article-search-highlight')
    expect(Array.from(marks).map((m) => m.textContent)).toEqual(['battery', 'recall'])
  })

  it('is case-insensitive', () => {
    const { container } = render(<div>{highlightMatches('BATTERY issue', 'battery')}</div>)
    expect(container.querySelector('mark')?.textContent).toBe('BATTERY')
  })
})

describe('getPageNumbers', () => {
  it('returns every page when there are 7 or fewer', () => {
    expect(getPageNumbers(1, 5)).toEqual([1, 2, 3, 4, 5])
  })

  it('collapses the middle into ellipses for many pages', () => {
    expect(getPageNumbers(10, 20)).toEqual([1, '...', 9, 10, 11, '...', 20])
  })

  it('has no leading ellipsis near the start', () => {
    expect(getPageNumbers(1, 20)).toEqual([1, 2, '...', 20])
  })
})
