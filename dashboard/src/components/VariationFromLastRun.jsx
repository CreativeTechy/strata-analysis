import { useEffect, useState } from 'react';
import { AlertCircle, RefreshCw } from 'lucide-react';
import { getReportVariation } from '../api/projectsApi.js';

function signed(value) {
  const number = Number(value || 0);
  return `${number > 0 ? '+' : ''}${number}`;
}

export default function VariationFromLastRun({ projectId, runId, number = '02' }) {
  const scopeKey = `${projectId ?? ''}:${runId ?? ''}`;
  const [result, setResult] = useState({ scopeKey: null, comparison: null, error: null });
  const [regenerating, setRegenerating] = useState(false);

  useEffect(() => {
    if (projectId == null || !runId) {
      return undefined;
    }

    const controller = new AbortController();
    getReportVariation(projectId, { run_id: runId }, controller.signal)
      .then((data) => setResult({ scopeKey, comparison: data, error: null }))
      .catch((err) => {
        if (err?.name !== 'AbortError') {
          setResult({ scopeKey, comparison: null, error: err?.message || 'Failed to load the run comparison.' });
        }
      });
    return () => controller.abort();
  }, [projectId, runId, scopeKey]);

  const scopeLoaded = result.scopeKey === scopeKey;
  const comparison = scopeLoaded ? result.comparison : null;
  const error = scopeLoaded ? result.error : null;
  const loading = Boolean(runId) && (!scopeLoaded || regenerating);

  const regenerate = async () => {
    if (projectId == null || !runId || loading) return;
    setRegenerating(true);
    try {
      const data = await getReportVariation(projectId, { run_id: runId, regenerate: 'true' });
      setResult({ scopeKey, comparison: data, error: null });
    } catch (err) {
      setResult((current) => ({
        scopeKey,
        comparison: current.scopeKey === scopeKey ? current.comparison : null,
        error: err?.message || 'Failed to regenerate the run comparison.',
      }));
    } finally {
      setRegenerating(false);
    }
  };

  const metrics = comparison?.metrics || {};
  const current = metrics.current;
  const previous = metrics.previous;
  const deltas = metrics.deltas;
  const coverage = metrics.coverage;

  return (
    <section className="report-brief-section report-variation-section">
      <header>
        <span>{number}</span>
        <h3>Variation from last run</h3>
        <span className="report-trend-actions">
          <button
            type="button"
            className="report-trend-refresh-btn"
            onClick={regenerate}
            disabled={loading || !runId}
            aria-busy={loading}
            aria-label="Regenerate variation from last run"
            title={runId ? 'Regenerate variation from last run' : 'Select an analysis run first'}
          >
            <RefreshCw size={13} className={loading ? 'spin' : ''} />
          </button>
        </span>
      </header>

      {!runId ? (
        <p className="report-brief-summary report-variation-empty">
          Select an analysis run to compare it with the immediately preceding run.
        </p>
      ) : loading && !comparison ? (
        <p className="report-trend-summary-status">Generating run comparison…</p>
      ) : error ? (
        <p className="report-trend-summary-status report-trend-summary-error" role="alert">
          <AlertCircle size={13} aria-hidden="true" /> {error}
        </p>
      ) : (
        <>
          {comparison?.previous_scope_label ? (
            <p className="report-variation-scope">
              {comparison.current_scope_label} compared with {comparison.previous_scope_label}
            </p>
          ) : null}

          {comparison?.narrative ? (
            <div className="report-brief-summary report-variation-narrative">{comparison.narrative}</div>
          ) : (
            <p className="report-brief-summary report-variation-empty">
              {comparison?.reason || 'No comparison is available for this run yet.'}
            </p>
          )}

          {current || previous ? (
            <div className="report-brief-metrics report-variation-metrics">
              <div><strong>{Number(current?.total || 0).toLocaleString()}</strong><span>Selected run articles</span></div>
              <div><strong>{Number(previous?.total || 0).toLocaleString()}</strong><span>Previous run articles</span></div>
              <div>
                <strong className={Number(deltas?.net_sentiment || 0) >= 0 ? 'positive-text' : 'negative-text'}>
                  {signed(deltas?.net_sentiment)}
                </strong>
                <span>Net sentiment change</span>
              </div>
            </div>
          ) : null}

          {coverage ? (
            <p className="report-trend-summary-status">
              {coverage.common} article(s) in both runs · {coverage.added} added · {coverage.removed} removed
            </p>
          ) : null}

          {loading ? <p className="report-trend-summary-status">Regenerating run comparison…</p> : null}
          {!loading && comparison?.status === 'llm_failed' ? (
            <p className="report-trend-summary-status report-trend-summary-error">
              {comparison.reason || 'The narrative could not be generated; verified metrics are still shown.'}
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}
