/**
 * Presentational pieces for the shared "run analysis" flow - the button,
 * its progress log, and its period/run-choice modal. State and the actual
 * queue/poll logic live in useRunAnalysis.js (kept separate so this file can
 * stay component-only for Fast Refresh).
 */

import { Sparkles, X } from 'lucide-react';
import { relativeTime } from '../competitorApi.js';
import { ANALYSIS_PERIODS, pipelineRunTitle } from '../useRunAnalysis.js';
import { DiscoveryLog } from './CompetitorOnboarding.jsx';

export function RunAnalysisButton({ run, label = 'Run analysis', primary = true, disabled }) {
  return (
    <button
      type="button"
      className={`cs-btn${primary ? ' cs-btn-primary' : ''}`}
      onClick={() => run.setShowRunChoice(true)}
      disabled={run.analyzing || disabled}
    >
      {run.analyzing ? <span className="cs-spinner" /> : <Sparkles size={15} />}
      {run.analyzing ? 'Analysing...' : label}
    </button>
  );
}

export function RunAnalysisLog({ run }) {
  if (!run.analyzing && !run.analysisLogs.length) return null;
  return <DiscoveryLog logs={run.analysisLogs} active={run.analyzing} />;
}

export function RunAnalysisChoiceModal({ run, lastRunAt }) {
  if (!run.showRunChoice) return null;
  return (
    <div className="confirm-modal-backdrop" role="presentation" onClick={() => run.setShowRunChoice(false)}>
      <div className="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="run-analysis-title"
        aria-describedby="run-analysis-message" onClick={(event) => event.stopPropagation()}>
        <div className="confirm-modal-header">
          <h2 id="run-analysis-title" className="confirm-modal-title">Run analysis</h2>
          <button type="button" className="confirm-modal-close" onClick={() => run.setShowRunChoice(false)} aria-label="Close dialog">
            <X size={18} />
          </button>
        </div>

        <p id="run-analysis-message" className="confirm-modal-message">
          Re-reads the evidence already on file and rewrites a card per tracked competitor.
          {' '}{lastRunAt ? `Last run ${relativeTime(lastRunAt)}.` : 'This study has never been analysed.'}
        </p>

        <div className="cs-run-period" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div className="filter-tabs-shell" style={{ margin: 0 }}>
            <div className="filter-tab-buttons filter-mode-toggle" role="tablist" aria-label="Evidence source">
              <button type="button" role="tab" aria-selected={!run.pipelineRunId}
                className={`source-type-tab ${!run.pipelineRunId ? 'active' : ''}`}
                onClick={() => run.setPipelineRunId(null)}>
                Date range
              </button>
              {run.pipelineRuns.length > 0 ? (
                <button type="button" role="tab" aria-selected={!!run.pipelineRunId}
                  className={`source-type-tab ${run.pipelineRunId ? 'active' : ''}`}
                  onClick={() => run.setPipelineRunId(run.pipelineRunId || run.pipelineRuns[0].id)}>
                  Analysis run
                </button>
              ) : null}
            </div>
          </div>

          {run.pipelineRunId ? (
            <select className="cs-select filter-run-select" value={run.pipelineRunId}
              onChange={(event) => run.setPipelineRunId(event.target.value)}
              aria-label="Analysis run to analyze">
              {run.pipelineRuns.map((pipelineRun, index) => (
                <option key={pipelineRun.id} value={pipelineRun.id}>{pipelineRunTitle(pipelineRun, index)}</option>
              ))}
            </select>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <label htmlFor="cs-analysis-period">Look back over</label>
              <select id="cs-analysis-period" className="cs-select" style={{ flex: 1 }} value={run.periodDays}
                onChange={(event) => run.setPeriodDays(Number(event.target.value))}>
                {ANALYSIS_PERIODS.map((option) => (
                  <option key={option.days} value={option.days}>{option.label}</option>
                ))}
              </select>
            </div>
          )}

          <small>
            {run.pipelineRunId
              ? 'Only the articles that analysis run covered are used as evidence.'
              : (<>
                  Evidence outside this window is ignored, and each report says which window it covers.
                  An article split out of an uploaded document is dated by when the document was added,
                  so a longer window mainly helps studies built up over time.
                </>)}
          </small>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, margin: '4px 0 6px' }}>
          <button type="button" onClick={run.runAnalysis}
            className="cs-btn cs-btn-primary"
            style={{ justifyContent: 'flex-start', width: '100%' }}>
            <Sparkles size={15} />
            <span style={{ textAlign: 'left', flex: 1 }}>
              {run.pipelineRunId ? 'Analyze this run' : 'Analyze this window'}
            </span>
          </button>
        </div>

        <div className="confirm-modal-actions">
          <button type="button" className="btn-secondary" onClick={() => run.setShowRunChoice(false)}>Cancel</button>
        </div>
      </div>
    </div>
  );
}
