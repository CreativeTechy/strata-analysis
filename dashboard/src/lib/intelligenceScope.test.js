import { describe, expect, it } from 'vitest';
import {
  clearIntelligenceScope,
  readIntelligenceScope,
  transferableIntelligenceScope,
  writeIntelligenceScope,
} from './intelligenceScope.js';

describe('intelligence scope URL helpers', () => {
  it('reads a bookmarked period and reports it as explicit', () => {
    expect(readIntelligenceScope('?period=7d', '30d')).toEqual({
      period: '7d',
      runId: null,
      explicit: true,
    });
  });

  it('reads a bookmarked run in preference to the page default', () => {
    expect(readIntelligenceScope('?run_id=run-42', 'all')).toEqual({
      period: 'all',
      runId: 'run-42',
      explicit: true,
    });
  });

  it('uses the page default for missing or invalid periods', () => {
    expect(readIntelligenceScope('', '30d')).toEqual({ period: '30d', runId: null, explicit: false });
    expect(readIntelligenceScope('?period=year', 'all')).toEqual({ period: 'all', runId: null, explicit: false });
  });

  it('writes exactly one scope while retaining unrelated parameters', () => {
    expect(writeIntelligenceScope('?view=compact&period=7d', { period: 'all', runId: 'run 2' }))
      .toBe('?view=compact&run_id=run+2');
    expect(writeIntelligenceScope('?run_id=run-2', { period: '30d', runId: null }))
      .toBe('?period=30d');
  });

  it('transfers only valid scope parameters between dashboard and reports', () => {
    expect(transferableIntelligenceScope('?period=7d&view=compact')).toBe('?period=7d');
    expect(transferableIntelligenceScope('?period=7d&run_id=run-2')).toBe('?run_id=run-2');
    expect(transferableIntelligenceScope('?period=year')).toBe('');
  });

  it('can clear project-specific scope without removing unrelated parameters', () => {
    expect(clearIntelligenceScope('?period=7d&view=compact')).toBe('?view=compact');
  });
});
