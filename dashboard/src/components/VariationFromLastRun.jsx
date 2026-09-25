import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertCircle, RefreshCw } from 'lucide-react';
import { getReportVariation } from '../api/projectsApi.js';
import { formatDate, formatNumber } from '../lib/i18nFormat.js';

// current_date/previous_date are plain calendar dates (already resolved in the
// report timezone server-side), so they're formatted in UTC - a local-time
// parse would shift them a day back anywhere west of UTC.
const SCOPE_DATE_OPTIONS = { year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC' };

// Builds "Analysis #N - <date>" in the interface language from the response's
// raw sequence number and date, falling back to the backend's own English
// *_scope_label only when there's no date to format.
function scopeLabel(t, locale, sequence, isoDate, fallback) {
  const date = isoDate ? formatDate(isoDate, locale, SCOPE_DATE_OPTIONS) : '';
  if (!date) return fallback || '';
  return sequence
    ? t('reports:variation.scopeLabel', { number: sequence, date })
    : t('reports:variation.scopeLabelNoNumber', { date });
}

export default function VariationFromLastRun({ projectId, runId, number = '02' }) {
  const { t, i18n } = useTranslation('reports');
  const locale = i18n.language;
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
          console.error('Failed to load the run comparison', err);
          setResult({ scopeKey, comparison: null, error: { key: 'loadError', detail: err?.message || null } });
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
      console.error('Failed to regenerate the run comparison', err);
      setResult((current) => ({
        scopeKey,
        comparison: current.scopeKey === scopeKey ? current.comparison : null,
        error: { key: 'regenerateError', detail: err?.message || null },
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
  const llmFailed = comparison?.status === 'llm_failed';
  // `reason` is English prose (it also goes into the PDF); `reason_code` is
  // what picks the translated message here.
  const unavailableReason = comparison?.reason_code
    ? t(`reports:variation.reasons.${comparison.reason_code}`, { defaultValue: t('reports:variation.reasons.fallback') })
    : t('reports:variation.reasons.fallback');

  return (
    <section className="report-brief-section report-variation-section">
      <header>
        <span>{number}</span>
        <h3>{t('reports:variation.title')}</h3>
        <span className="report-trend-actions">
          <button
            type="button"
            className="report-trend-refresh-btn"
            onClick={regenerate}
            disabled={loading || !runId}
            aria-busy={loading}
            aria-label={t('reports:variation.regenerateAria')}
            title={runId ? t('reports:variation.regenerateAria') : t('reports:variation.selectRunFirst')}
          >
            <RefreshCw size={13} className={loading ? 'spin' : ''} />
          </button>
        </span>
      </header>

      {!runId ? (
        <p className="report-brief-summary report-variation-empty">
          {t('reports:variation.selectRunPrompt')}
        </p>
      ) : loading && !comparison ? (
        <p className="report-trend-summary-status">{t('reports:variation.generating')}</p>
      ) : error ? (
        <p className="report-trend-summary-status report-trend-summary-error" role="alert">
          <AlertCircle size={13} aria-hidden="true" /> {t(`reports:variation.${error.key}`)}
          {error.detail ? <span dir="auto"> {error.detail}</span> : null}
        </p>
      ) : (
        <>
          {comparison?.previous_scope_label ? (
            <p className="report-variation-scope">
              {t('reports:variation.comparedWith', {
                current: scopeLabel(t, locale, comparison.current_sequence_number, comparison.current_date, comparison.current_scope_label),
                previous: scopeLabel(t, locale, comparison.previous_sequence_number, comparison.previous_date, comparison.previous_scope_label),
              })}
            </p>
          ) : null}

          {comparison?.narrative ? (
            <div className="report-brief-summary report-variation-narrative" dir="auto">{comparison.narrative}</div>
          ) : !llmFailed ? (
            <p className="report-brief-summary report-variation-empty">{unavailableReason}</p>
          ) : null}

          {current || previous ? (
            <div className="report-brief-metrics report-variation-metrics">
              <div><strong>{formatNumber(current?.total || 0, locale)}</strong><span>{t('reports:variation.selectedRunArticles')}</span></div>
              <div><strong>{formatNumber(previous?.total || 0, locale)}</strong><span>{t('reports:variation.previousRunArticles')}</span></div>
              <div>
                <strong className={Number(deltas?.net_sentiment || 0) >= 0 ? 'positive-text' : 'negative-text'}>
                  {formatNumber(deltas?.net_sentiment || 0, locale, { signDisplay: 'exceptZero', maximumFractionDigits: 0 })}
                </strong>
                <span>{t('reports:variation.netSentimentChange')}</span>
              </div>
            </div>
          ) : null}

          {coverage ? (
            <p className="report-trend-summary-status">
              {t('reports:variation.coverage', {
                common: t('reports:variation.coverageCommon', { count: Number(coverage.common || 0) }),
                added: t('reports:variation.coverageAdded', { count: formatNumber(coverage.added || 0, locale) }),
                removed: t('reports:variation.coverageRemoved', { count: formatNumber(coverage.removed || 0, locale) }),
              })}
            </p>
          ) : null}

          {loading ? <p className="report-trend-summary-status">{t('reports:variation.regenerating')}</p> : null}
          {!loading && llmFailed ? (
            <p className="report-trend-summary-status report-trend-summary-error" title={comparison.reason || undefined}>
              {t('reports:variation.llmFailed')}
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}
