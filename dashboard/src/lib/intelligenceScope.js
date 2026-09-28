export const INTELLIGENCE_PERIODS = new Set(['7d', '30d', 'all']);

export function readIntelligenceScope(search, defaultPeriod = '30d') {
  const params = new URLSearchParams(search);
  const runId = params.get('run_id') || null;
  const requestedPeriod = params.get('period');
  const period = INTELLIGENCE_PERIODS.has(requestedPeriod) ? requestedPeriod : defaultPeriod;

  return {
    period,
    runId,
    explicit: Boolean(runId || INTELLIGENCE_PERIODS.has(requestedPeriod)),
  };
}

export function writeIntelligenceScope(search, { period, runId }) {
  const params = new URLSearchParams(search);
  params.delete('period');
  params.delete('run_id');

  if (runId) {
    params.set('run_id', String(runId));
  } else {
    params.set('period', INTELLIGENCE_PERIODS.has(period) ? period : '30d');
  }

  const value = params.toString();
  return value ? `?${value}` : '';
}

export function clearIntelligenceScope(search) {
  const params = new URLSearchParams(search);
  params.delete('period');
  params.delete('run_id');
  const value = params.toString();
  return value ? `?${value}` : '';
}

export function transferableIntelligenceScope(search) {
  const params = new URLSearchParams(search);
  const runId = params.get('run_id');
  if (runId) return `?${new URLSearchParams({ run_id: runId }).toString()}`;

  const period = params.get('period');
  if (INTELLIGENCE_PERIODS.has(period)) {
    return `?${new URLSearchParams({ period }).toString()}`;
  }
  return '';
}
