import { describe, expect, it } from 'vitest'
import { resolveIntelligenceState } from './intelligenceState.js'

function withCoverage(coverage, extra = {}) {
  return {
    total: 0,
    run_id: null,
    ...extra,
    coverage: {
      documents: 0, documents_in_progress: 0, articles: 0, analyzed: 0, pending: 0, failed: 0, active_run: null,
      ...coverage,
    },
  }
}

describe('resolveIntelligenceState', () => {
  it('falls back to total alone when the backend sends no coverage', () => {
    expect(resolveIntelligenceState({ total: 3 }).kind).toBe('ready')
    expect(resolveIntelligenceState({ total: 0 })).toMatchObject({ kind: 'no_results', variant: 'unknown' })
    expect(resolveIntelligenceState(null)).toMatchObject({ kind: 'no_results', variant: 'unknown' })
  })

  it('reports no documents when nothing has been uploaded', () => {
    expect(resolveIntelligenceState(withCoverage({}))).toMatchObject({ kind: 'no_documents', variant: 'none' })
  })

  it('separates "uploaded but nothing extracted" from "nothing uploaded"', () => {
    expect(resolveIntelligenceState(withCoverage({ documents: 2 }))).toMatchObject({ kind: 'no_documents', variant: 'no_articles' })
  })

  it('treats documents still being split as analysis pending', () => {
    expect(resolveIntelligenceState(withCoverage({ documents: 2, documents_in_progress: 1 })))
      .toMatchObject({ kind: 'analysis_pending', variant: 'extracting' })
  })

  it('is analysis pending while nothing is analyzed, even though placeholder articles inflate total', () => {
    const run = { id: 'run-1', status: 'running' }
    expect(resolveIntelligenceState(withCoverage({ documents: 1, articles: 5, pending: 5, active_run: run }, { total: 5 })))
      .toMatchObject({ kind: 'analysis_pending', variant: 'running' })
    expect(resolveIntelligenceState(withCoverage({ documents: 1, articles: 5, pending: 5 }, { total: 5 })))
      .toMatchObject({ kind: 'analysis_pending', variant: 'queued' })
    expect(resolveIntelligenceState(withCoverage({ documents: 1, articles: 5, failed: 5 }, { total: 5 })))
      .toMatchObject({ kind: 'analysis_pending', variant: 'failed' })
  })

  it('reports no results in range when the project has analysis but the scope is empty', () => {
    const coverage = { documents: 1, articles: 5, analyzed: 5 }
    expect(resolveIntelligenceState(withCoverage(coverage))).toMatchObject({ kind: 'no_results', variant: 'period' })
    expect(resolveIntelligenceState(withCoverage(coverage, { run_id: 'run-1' }))).toMatchObject({ kind: 'no_results', variant: 'run' })
  })

  it('is ready once the scope has analyzed results', () => {
    const state = resolveIntelligenceState(withCoverage({ documents: 1, articles: 5, analyzed: 3, pending: 2 }, { total: 5 }))
    expect(state.kind).toBe('ready')
    expect(state.coverage.pending).toBe(2)
  })
})
