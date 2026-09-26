// Why a Dashboard/Reports scope has nothing to show, read off the intelligence
// response's project-wide `coverage` block (services/intelligence/
// intelligence.py's _fetch_coverage). `total` alone can't tell "nothing
// uploaded" from "analysis hasn't finished" from "nothing in this range" - and
// it also counts articles still carrying neutral placeholders because no
// analysis has succeeded for them yet, so "nothing analyzed" has to be checked
// before `total` is trusted at all.
//
// kind:    'ready' | 'no_documents' | 'analysis_pending' | 'no_results'
// variant: narrows the message/action within a kind (see IntelligenceEmptyState.jsx).
function count(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : 0;
}

// App holds one `intelligence` for both Dashboard and Reports, so right after
// a project switch (or before the first fetch lands) it can still describe
// another project - callers must treat that as loading, not as an empty
// result. Single owner for that check so Dashboard/Reports/Stats can't drift
// on the rule (e.g. if it later also needs to compare run_id).
export function isIntelligenceStale(intelligence, selectedProjectId) {
  return !intelligence || Number(intelligence.project_id) !== Number(selectedProjectId);
}

export function resolveIntelligenceState(intelligence) {
  const data = intelligence || {};
  const total = count(data.total);
  const coverage = data.coverage;

  // An older backend without `coverage` - fall back to the one distinction
  // `total` can still make.
  if (!coverage) {
    return total ? { kind: 'ready', coverage: null } : { kind: 'no_results', variant: 'unknown', coverage: null };
  }

  const summary = {
    documents: count(coverage.documents),
    documentsInProgress: count(coverage.documents_in_progress),
    articles: count(coverage.articles),
    analyzed: count(coverage.analyzed),
    pending: count(coverage.pending),
    failed: count(coverage.failed),
    activeRun: coverage.active_run || null,
  };

  if (summary.articles === 0) {
    if (summary.documentsInProgress > 0) return { kind: 'analysis_pending', variant: 'extracting', coverage: summary };
    return { kind: 'no_documents', variant: summary.documents > 0 ? 'no_articles' : 'none', coverage: summary };
  }
  if (summary.analyzed === 0) {
    if (summary.activeRun) return { kind: 'analysis_pending', variant: 'running', coverage: summary };
    if (summary.pending > 0) return { kind: 'analysis_pending', variant: 'queued', coverage: summary };
    return { kind: 'analysis_pending', variant: 'failed', coverage: summary };
  }
  if (total === 0) return { kind: 'no_results', variant: data.run_id ? 'run' : 'period', coverage: summary };
  return { kind: 'ready', coverage: summary };
}
