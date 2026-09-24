/**
 * Presentational pieces for the shared "run analysis" flow - the button,
 * its progress log, and its scope-choice dialog. State and the actual
 * queue/poll logic live in useRunAnalysis.js (kept separate so this file can
 * stay component-only for Fast Refresh).
 */

import { useTranslation } from 'react-i18next';
import { Sparkles, X } from 'lucide-react';
import { formatRelativeTime } from '../lib/i18nFormat.js';
import { DiscoveryLog } from './CompetitorOnboarding.jsx';

export function RunAnalysisButton({ run, label, primary = true, disabled }) {
  const { t } = useTranslation('competitors');
  const resolvedLabel = label ?? t('runAnalysis.runAnalysisLabel');
  return (
    <button
      type="button"
      className={`cs-btn${primary ? ' cs-btn-primary' : ''}`}
      onClick={() => run.setShowRunChoice(true)}
      disabled={run.analyzing || disabled}
    >
      {run.analyzing ? <span className="cs-spinner" /> : <Sparkles size={15} />}
      {run.analyzing ? t('runAnalysis.analysingEllipsis') : resolvedLabel}
    </button>
  );
}

export function RunAnalysisLog({ run }) {
  if (!run.analyzing && !run.analysisLogs.length) return null;
  return <DiscoveryLog logs={run.analysisLogs} active={run.analyzing} />;
}

const SCOPES = ['pending', 'all', 'selected'];

export function RunAnalysisChoiceModal({ run, lastRunAt }) {
  const { t, i18n } = useTranslation('competitors');
  const locale = i18n.language;
  if (!run.showRunChoice) return null;

  const SCOPE_LABELS = {
    pending: t('runAnalysis.scopeLabels.pending'),
    all: t('runAnalysis.scopeLabels.all'),
    selected: t('runAnalysis.scopeLabels.selected'),
  };

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
          <h2 id="run-analysis-title" className="confirm-modal-title">{t('runAnalysis.runAnalysisLabel')}</h2>
          <button type="button" className="confirm-modal-close" onClick={() => run.setShowRunChoice(false)} aria-label={t('common:a11y.closeDialog')}>
            <X size={18} />
          </button>
        </div>

        <p id="run-analysis-message" className="confirm-modal-message">
          {t('runAnalysis.description')}
          {' '}{lastRunAt ? t('runAnalysis.lastRun', { time: formatRelativeTime(lastRunAt, locale) }) : t('runAnalysis.neverAnalysed')}
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
                    ? t('runAnalysis.chosenBelow', { count: run.selectedDocumentIds.length })
                    : t('runAnalysis.documentCount', { count: scopeCount(scope) })}
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
                  <div className="cs-row-name" dir="auto">{document.original_filename}</div>
                  <div className="cs-row-desc">
                    {t('runAnalysis.approvedArticleCount', { count: document.approved_article_count })}
                    {document.analyzed ? ` · ${t('runAnalysis.previouslyAnalyzed')}` : ''}
                  </div>
                </div>
              </label>
            )) : (
              <div className="cs-row-desc" style={{ padding: '8px 0' }}>{t('runAnalysis.noEligibleDocuments')}</div>
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
              {t('runAnalysis.analyzeDocuments', { count })}
            </span>
          </button>
        </div>

        <div className="confirm-modal-actions">
          <button type="button" className="btn-secondary" onClick={() => run.setShowRunChoice(false)}>{t('common:actions.cancel')}</button>
        </div>
      </div>
    </div>
  );
}
