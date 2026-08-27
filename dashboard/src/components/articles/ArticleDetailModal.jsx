import ConfirmModal from '../ConfirmModal';
import { prettyLabel, confidencePct } from '../../lib/articleHelpers.jsx';

// The "Analysis details" popover opened from an article card/row - extracted
// out of ArticlesPage.jsx as its own component since it's a fully
// self-contained read (plus optional reprocess action) of one article's
// stored analysis.
export default function ArticleDetailModal({
  open,
  canReprocess,
  loading,
  error,
  data,
  actionMessage,
  reprocessing,
  onClose,
  onReprocess,
}) {
  return (
    <ConfirmModal
      open={open}
      title="Analysis details"
      hideCancel={!canReprocess}
      cancelLabel="Close"
      confirmLabel={canReprocess ? (reprocessing ? 'Reprocessing...' : 'Reprocess') : 'Close'}
      onClose={onClose}
      onConfirm={canReprocess ? onReprocess : onClose}
    >
      {loading ? (
        <p className="subtitle">Loading analysis details...</p>
      ) : error ? (
        <p style={{ color: '#b42318' }}>{error}</p>
      ) : data ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <span
              className={`badge ${
                data.analysis_status === 'failed' ? 'negative' : data.analysis_status === 'success' ? 'positive' : 'neutral'
              }`}
            >
              {prettyLabel(data.analysis_status || 'unknown')}
            </span>
            {data.analysis_error ? <span className="badge negative">{data.analysis_error}</span> : null}
          </div>

          <div>
            <strong>Sentiment:</strong> {prettyLabel(data.sentiment)}
            {confidencePct(data.confidence?.sentiment) && (
              <span style={{ marginLeft: 6, color: 'var(--text-light)', fontSize: '0.85rem' }}>
                (confidence {confidencePct(data.confidence.sentiment)}
                {data.confidence?.sentiment_low_confidence ? ', low confidence' : ''})
              </span>
            )}
          </div>
          <div>
            <strong>Category:</strong> {prettyLabel(data.article_category)}
            {confidencePct(data.confidence?.category) && (
              <span style={{ marginLeft: 6, color: 'var(--text-light)', fontSize: '0.85rem' }}>
                (confidence {confidencePct(data.confidence.category)})
              </span>
            )}
          </div>
          <div>
            <strong>Writer tone:</strong> {prettyLabel(data.writer_tone)}
            {confidencePct(data.confidence?.writer_tone) && (
              <span style={{ marginLeft: 6, color: 'var(--text-light)', fontSize: '0.85rem' }}>
                (confidence {confidencePct(data.confidence.writer_tone)})
              </span>
            )}
          </div>
          <div>
            <strong>Article tone:</strong> {prettyLabel(data.article_tone)}
            {confidencePct(data.confidence?.article_tone) && (
              <span style={{ marginLeft: 6, color: 'var(--text-light)', fontSize: '0.85rem' }}>
                (confidence {confidencePct(data.confidence.article_tone)})
              </span>
            )}
          </div>
          <div>
            <strong>Overall tone:</strong> {prettyLabel(data.overall_tone)}
          </div>
          {data.source_language ? (
            <div>
              <strong>Source language:</strong> {data.source_language.toUpperCase()}
              {confidencePct(data.source_language_confidence) && (
                <span style={{ marginLeft: 6, color: 'var(--text-light)', fontSize: '0.85rem' }}>
                  (confidence {confidencePct(data.source_language_confidence)})
                </span>
              )}
            </div>
          ) : null}
          <div style={{ fontSize: '0.82rem', color: 'var(--text-light)', borderTop: '1px solid rgba(0,0,0,0.08)', paddingTop: 10 }}>
            <div>
              Models - sentiment: {data.models?.sentiment || 'n/a'}, classification: {data.models?.classification || 'n/a'}, extraction:{' '}
              {data.models?.extraction || 'n/a'}
            </div>
            <div style={{ marginTop: 4 }}>
              Attempts: {data.processing?.attempt_count ?? 0} - Last run:{' '}
              {data.processing?.finished_at ? new Date(data.processing.finished_at).toLocaleString() : 'Not yet'}
            </div>
          </div>
        </div>
      ) : (
        <p className="subtitle">No analysis data available for this article.</p>
      )}
      {actionMessage ? <p style={{ marginTop: 10, fontSize: '0.85rem', color: 'var(--text-light)' }}>{actionMessage}</p> : null}
    </ConfirmModal>
  );
}
