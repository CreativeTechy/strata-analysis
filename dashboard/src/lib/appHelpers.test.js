import { describe, it, expect } from 'vitest'
import {
  dominantSentimentFromStats,
  timeAgo,
  formatRunLabel,
  pipelineRunNumber,
  pipelineRunTitle,
} from './appHelpers.js'

describe('dominantSentimentFromStats', () => {
  it('reports no data when total is zero', () => {
    expect(dominantSentimentFromStats({ total: 0 })).toEqual({ label: 'No data yet', color: 'var(--text-light)', pct: 0 })
  })

  it('picks the sentiment with the most articles', () => {
    const result = dominantSentimentFromStats({ total: 10, positive: 7, negative: 2, neutral: 1, mixed: 0 })
    expect(result.label).toBe('Positive - 70%')
    expect(result.color).toBe('#16a34a')
  })

  it('breaks a tie by taking the first sorted entry', () => {
    const result = dominantSentimentFromStats({ total: 4, positive: 2, negative: 2, neutral: 0, mixed: 0 })
    expect(result.label).toBe('Positive - 50%')
  })
})

describe('timeAgo', () => {
  it('returns null for a missing date', () => {
    expect(timeAgo(null)).toBeNull()
    expect(timeAgo(undefined)).toBeNull()
  })

  it('returns null for an unparsable date', () => {
    expect(timeAgo('not a date')).toBeNull()
  })

  it('reports "just now" for very recent timestamps', () => {
    expect(timeAgo(new Date().toISOString())).toBe('just now')
  })

  it('reports minutes ago for timestamps under an hour old', () => {
    const fiveMinutesAgo = new Date(Date.now() - 5 * 60000).toISOString()
    expect(timeAgo(fiveMinutesAgo)).toBe('5m ago')
  })

  it('reports days ago for timestamps over a day old', () => {
    const threeDaysAgo = new Date(Date.now() - 3 * 24 * 60 * 60000).toISOString()
    expect(timeAgo(threeDaysAgo)).toBe('3d ago')
  })
})

describe('formatRunLabel', () => {
  it('returns "Run" when there is no usable date', () => {
    expect(formatRunLabel({})).toBe('Run')
    expect(formatRunLabel({ finished_at: 'garbage' })).toBe('Run')
  })

  it('prefers finished_at over created_at', () => {
    const label = formatRunLabel({ finished_at: '2026-01-15T10:00:00Z', created_at: '2020-01-01T00:00:00Z' })
    expect(label).toContain('Jan')
    expect(label).toContain('15')
  })
})

describe('pipelineRunNumber', () => {
  it('prefers the server-computed sequence number', () => {
    expect(pipelineRunNumber({ sequence_number: 7 }, 0)).toBe(7)
  })

  it('falls back to a 1-based index when there is no sequence number', () => {
    expect(pipelineRunNumber({}, 2)).toBe(3)
  })
})

describe('pipelineRunTitle', () => {
  it('combines the run number and formatted date', () => {
    const title = pipelineRunTitle({ sequence_number: 2, finished_at: '2026-01-15T10:00:00Z' }, 0)
    expect(title).toMatch(/^Pipeline #2: /)
  })
})
