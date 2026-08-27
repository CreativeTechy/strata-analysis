import { describe, it, expect } from 'vitest'
import {
  formatDateTime,
  toDateInput,
  sanitizeTermArray,
  normalizeTermListForCompare,
  normalizeDraftForCompare,
} from './projectHelpers.js'

describe('formatDateTime', () => {
  it('returns null for a missing or unparsable value', () => {
    expect(formatDateTime(null)).toBeNull()
    expect(formatDateTime('garbage')).toBeNull()
  })

  it('formats a valid date', () => {
    expect(formatDateTime('2026-01-15T10:00:00Z')).toEqual(expect.any(String))
  })
})

describe('toDateInput', () => {
  it('returns an empty string for a missing or unparsable value', () => {
    expect(toDateInput(null)).toBe('')
    expect(toDateInput('garbage')).toBe('')
  })

  it('formats a valid date as YYYY-MM-DD', () => {
    expect(toDateInput('2026-01-15T10:00:00Z')).toBe('2026-01-15')
  })
})

describe('sanitizeTermArray', () => {
  it('trims, dedupes, and drops blanks', () => {
    expect(sanitizeTermArray([' ev ', 'ev', '', null, 'charging'])).toEqual(['ev', 'charging'])
  })

  it('returns an empty array for non-array input', () => {
    expect(sanitizeTermArray(null)).toEqual([])
    expect(sanitizeTermArray('not an array')).toEqual([])
  })
})

describe('normalizeTermListForCompare', () => {
  it('sorts the sanitized terms', () => {
    expect(normalizeTermListForCompare(['zebra', 'apple'])).toEqual(['apple', 'zebra'])
  })
})

describe('normalizeDraftForCompare', () => {
  it('produces equal output for two differently-ordered but equivalent drafts', () => {
    const a = normalizeDraftForCompare({ name: ' A ', keywords: ['b', 'a'], user_ids: [2, 1] })
    const b = normalizeDraftForCompare({ name: 'A', keywords: ['a', 'b'], user_ids: [1, 2] })
    expect(a).toEqual(b)
  })

  it('lowercases status and location_type for comparison', () => {
    const result = normalizeDraftForCompare({ status: 'ACTIVE', location_type: 'REMOTE' })
    expect(result.status).toBe('active')
    expect(result.location_type).toBe('remote')
  })

  it('defaults status to draft when missing', () => {
    expect(normalizeDraftForCompare({}).status).toBe('draft')
  })
})
