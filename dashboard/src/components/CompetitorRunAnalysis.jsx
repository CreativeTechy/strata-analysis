/**
 * Presentational pieces for the shared "run analysis" flow - the button,
 * its progress log, and its scope-choice dialog. State and the actual
 * queue/poll logic live in useRunAnalysis.js (kept separate so this file can
 * stay component-only for Fast Refresh).
 */

import { Sparkles, X } from 'lucide-react';
import { relativeTime } from '../competitorApi.js';
import { SCOPE_LABELS } from '../useRunAnalysis.js';
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

const SCOPES = ['pending', 'all', 'selected'];

export function RunAnalysisChoiceModal({ run, lastRunAt }) {
  if (!run.showRunChoice) return null;

  const scopeCount = (scope) => {
    if (scope === 'pending') return run.pendingDocuments.length;
    if (scope === 'all') return run.eligibleDocuments.length;
    return run.selectedDocumentIds.length;
  };

  const toggleSelected = (documentId) => {
    run.setSelectedDocumentIds((current) => (
      current.includes(documentId)
        ? current.filter((id) => id !== documentId)
        : [...current, documentId]
    ));
  };

  const count = scopeCount(run.scope);

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
          Reads the chosen documents' evidence and rewrites a card per tracked competitor.
          {' '}{lastRunAt ? `Last run ${relativeTime(lastRunAt)}.` : 'This study has never been analysed.'}
        </p>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, margin: '4px 0 12px' }}>
          {SCOPES.map((scope) => (
            <label key={scope} className="cs-row" style={{ cursor: 'pointer', alignItems: 'flex-start' }}>
              <input
                type="radio"
                name="cs-run-scope"
                checked={run.scope === scope}
                onChange={() => run.setScope(scope)}
                style={{ marginTop: 3 }}
              />
              <div className="cs-row-main">
                <div className="cs-row-name">{SCOPE_LABELS[scope]}</div>
                <div className="cs-row-desc">
                  {scope === 'selected'
                    ? `${run.selectedDocumentIds.length} chosen below`
                    : `${scopeCount(scope)} document${scopeCount(scope) === 1 ? '' : 's'}`}
                </div>
              </div>
            </label>
          ))}
        </div>

        {run.scope === 'selected' ? (
          <div className="cs-rows" style={{ maxHeight: 220, overflowY: 'auto', marginBottom: 12 }}>
            {run.eligibleDocuments.length ? run.eligibleDocuments.map((document) => (
              <label key={document.id} className="cs-row" style={{ cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={run.selectedDocumentIds.includes(document.id)}
                  onChange={() => toggleSelected(document.id)}
                />
                <div className="cs-row-main">
                  <div className="cs-row-name">{document.original_filename}</div>
                  <div className="cs-row-desc">
                    {document.approved_article_count} approved article{document.approved_article_count === 1 ? '' : 's'}
                    {document.analyzed ? ' · previously analyzed' : ''}
                  </div>
                </div>
              </label>
            )) : (
              <div className="cs-row-desc" style={{ padding: '8px 0' }}>No documents with approved articles yet.</div>
            )}
          </div>
        ) : null}

        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, margin: '4px 0 6px' }}>
          <button type="button" onClick={run.runAnalysis}
            className="cs-btn cs-btn-primary"
            disabled={count === 0}
            style={{ justifyContent: 'flex-start', width: '100%' }}>
            <Sparkles size={15} />
            <span style={{ textAlign: 'left', flex: 1 }}>
              Analyze {count} document{count === 1 ? '' : 's'}
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
