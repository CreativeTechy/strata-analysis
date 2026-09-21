import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, AlertTriangle, FileText, Loader2, Trash2 } from 'lucide-react';
import { getArticleAnalysis, reprocessArticle, deleteArticle } from '../api/articlesApi.js';
import { prettyLabel, confidencePct, articleDate } from '../lib/articleHelpers.jsx';
import { useAuth } from '../auth/useAuth.js';
import ConfirmModal from './ConfirmModal';

// Full-page version of what used to be the "Analysis details" modal opened
// from an article card/row - a self-contained read (plus optional reprocess
// and delete actions) of one article's stored analysis and full text, now at
// its own /articles/:id URL instead of a popover so it can be linked to
// directly. Delete used to live on the card/row - it's here instead so it
// isn't one accidental click away from the list.
export default function ArticleDetailPage() {
  const { articleId } = useParams();
  const navigate = useNavigate();
  const { hasPermission } = useAuth();
  const canReprocess = hasPermission('pipeline.run');
  const canDelete = hasPermission('articles.delete');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [data, setData] = useState(null);
  const [reprocessing, setReprocessing] = useState(false);
  const [actionMessage, setActionMessage] = useState('');
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState('');

  useEffect(() => {
    if (!articleId) return undefined;
    const controller = new AbortController();
    setLoading(true);
    setError('');
    setActionMessage('');
    getArticleAnalysis(articleId, controller.signal)
      .then((res) => setData(res?.analysis || null))
      .catch((err) => {
        if (err?.name !== 'AbortError') setError(err?.message || 'Failed to load analysis details.');
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [articleId]);

  const handleReprocess = async () => {
    if (reprocessing) return;
    setReprocessing(true);
    setActionMessage('');
    try {
      await reprocessArticle(articleId);
      setActionMessage('Reprocessing started - refresh this page in a moment to see the updated result.');
    } catch (err) {
      setActionMessage(err?.message || 'Failed to reprocess article.');
    } finally {
      setReprocessing(false);
    }
  };

  const handleDelete = async () => {
    if (deleting) return;
    setDeleting(true);
    setDeleteError('');
    try {
      await deleteArticle(articleId);
      navigate('/articles');
    } catch (err) {
      setDeleteError(err?.message || 'Failed to delete article.');
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="admin-page-shell">
      <ConfirmModal
        open={showDeleteModal}
        title="Delete this article?"
        message={`"${data?.title || 'Untitled article'}" will be permanently removed and cannot be undone.`}
        confirmLabel={deleting ? 'Deleting...' : 'Delete article'}
        cancelLabel="Keep article"
        confirmButtonStyle={{
          background: 'linear-gradient(135deg, #ff4757, #e03131)',
          boxShadow: '0 4px 15px rgba(255, 71, 87, 0.28)',
        }}
        onClose={() => {
          if (!deleting) setShowDeleteModal(false);
        }}
        onConfirm={handleDelete}
      >
        {deleteError ? <p style={{ color: '#b42318', fontSize: '0.85rem' }}>{deleteError}</p> : null}
      </ConfirmModal>

      <div className="admin-page-header">
        <div>
          <div className="admin-page-kicker">
            <FileText size={14} /> Article Library
          </div>
          <h1 className="admin-page-title">{data?.title || 'Article details'}</h1>
          {data?.source || data?.author || data?.published ? (
            <p className="admin-page-subtitle">
              {[data?.source, data?.author ? `By ${data.author}` : null, data?.published ? articleDate(data.published) : null]
                .filter(Boolean)
                .join(' · ')}
            </p>
          ) : null}
        </div>
        <div className="admin-page-toolbar">
          <Link to="/articles" className="btn-secondary" style={{ textDecoration: 'none' }}>
            <ArrowLeft size={16} /> Back to Articles
          </Link>
          {canReprocess ? (
            <button type="button" className="btn-secondary" onClick={handleReprocess} disabled={reprocessing || loading}>
              {reprocessing ? 'Reprocessing...' : 'Reprocess'}
            </button>
          ) : null}
          {canDelete ? (
            <button
              type="button"
              className="btn-secondary"
              style={{ color: '#b42318', borderColor: 'rgba(180,35,24,0.18)' }}
              onClick={() => setShowDeleteModal(true)}
              disabled={loading}
            >
              <Trash2 size={16} /> Delete
            </button>
          ) : null}
        </div>
      </div>

      {loading ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-light)', padding: '24px 0' }}>
          <Loader2 size={18} className="spin" /> Loading analysis details...
        </div>
      ) : error ? (
        <div className="glass-card" style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#b42318', borderLeft: '4px solid #ff4757' }}>
          <AlertTriangle size={18} /> {error}
        </div>
      ) : !data ? (
        <div className="glass-card">
          <p className="subtitle">No analysis data available for this article.</p>
        </div>
      ) : (
        <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
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

          {data.summary ? <p className="article-summary">{data.summary}</p> : null}

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
          <div>
            <strong>Region:</strong> {prettyLabel(data.region)}
            {confidencePct(data.confidence?.region) && (
              <span style={{ marginLeft: 6, color: 'var(--text-light)', fontSize: '0.85rem' }}>
                (confidence {confidencePct(data.confidence.region)})
              </span>
            )}
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

          {actionMessage ? <p style={{ fontSize: '0.85rem', color: 'var(--text-light)' }}>{actionMessage}</p> : null}
        </div>
      )}

      {!loading && !error && data?.text ? (
        <div className="glass-card" style={{ marginTop: 18 }}>
          <h3 className="run-detail-section-title">Full article</h3>
          <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.6, fontSize: '0.95rem' }}>{data.text}</div>
        </div>
      ) : null}
    </div>
  );
}
