import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, AlertTriangle, FileText, Loader2, Trash2 } from 'lucide-react';
import { getArticleAnalysis, reprocessArticle, deleteArticle } from '../api/articlesApi.js';
import { prettyLabel, sentimentBadgeState } from '../lib/articleHelpers.jsx';
import { formatDate, formatDateTime, formatPercent, formatLanguageName } from '../lib/i18nFormat.js';
import { useAuth } from '../auth/useAuth.js';
import ConfirmModal from './ConfirmModal';

// Bounded enum (pending/success/failed) - reuses the shared common:status.*
// labels rather than duplicating them, keeping data.analysis_status itself
// untouched (it still drives the badge's negative/positive/neutral className).
const STATUS_LABEL_KEYS = {
  pending: 'common:status.pending',
  success: 'common:status.success',
  failed: 'common:status.failed',
};

const SENTIMENT_STATE_LABEL_KEYS = {
  pending: 'sentiment.pending',
  failed: 'sentiment.failed',
  not_assessed: 'sentiment.notAssessed',
  positive: 'sentiment.positive',
  negative: 'sentiment.negative',
  neutral: 'sentiment.neutral',
  mixed: 'sentiment.mixed',
};

// articleHelpers.jsx's articleDate() is an ad hoc, locale-unaware
// toLocaleDateString() wrapper - this uses the shared, locale-explicit
// formatDate() instead (see lib/i18nFormat.js), keeping the same fallback.
function displayDate(value, locale) {
  if (!value) return null;
  return formatDate(value, locale) || value;
}

// Full-page version of what used to be the "Analysis details" modal opened
// from an article card/row - a self-contained read (plus optional reprocess
// and delete actions) of one article's stored analysis and full text, now at
// its own /articles/:id URL instead of a popover so it can be linked to
// directly. Delete used to live on the card/row - it's here instead so it
// isn't one accidental click away from the list.
export default function ArticleDetailPage() {
  const { t, i18n } = useTranslation(['articles', 'common']);
  const locale = i18n.language;
  const { articleId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  // Where "Back to Articles" (and a successful delete) should return to -
  // the article list's own path+query at the moment Details was clicked, so
  // its filters/search/page survive the round trip instead of resetting to
  // the article library's default view. Falls back to a bare /articles for
  // any other way of landing on this page (a direct link, a bookmark).
  const backTo = location.state?.from || '/articles';
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
  const activeArticle = useRef(articleId);

  useEffect(() => {
    activeArticle.current = articleId;
    return () => { activeArticle.current = null; };
  }, [articleId]);

  useEffect(() => {
    if (!articleId) return undefined;
    const controller = new AbortController();
    setLoading(true);
    setError('');
    setActionMessage('');
    getArticleAnalysis(articleId, { locale }, controller.signal)
      .then((res) => setData(res?.analysis || null))
      .catch((err) => {
        if (err?.name !== 'AbortError') setError(err?.message || t('detail.loadFailed'));
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [articleId, locale, t]);

  const handleReprocess = async () => {
    if (reprocessing) return;
    setReprocessing(true);
    setActionMessage('');
    try {
      await reprocessArticle(articleId);
      setActionMessage(t('detail.reprocessSuccess'));
    } catch (err) {
      setActionMessage(err?.message || t('detail.reprocessFailed'));
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
      // Replace, not push: the deleted article's own /articles/:id stays
      // out of the back-button history, so Back from the list can't return
      // to a 404 for a row that's already gone.
      navigate(backTo, { replace: true });
    } catch (err) {
      setDeleteError(err?.message || t('detail.deleteFailed'));
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="admin-page-shell">
      <ConfirmModal
        open={showDeleteModal}
        title={t('detail.deleteModal.title')}
        message={t('detail.deleteModal.message', { title: data?.title || t('common.untitledArticle') })}
        confirmLabel={deleting ? t('detail.deleteModal.confirmLabelBusy') : t('detail.deleteModal.confirmLabel')}
        cancelLabel={t('detail.deleteModal.cancelLabel')}
        confirmButtonStyle={{
          background: 'linear-gradient(135deg, #ff4757, #e03131)',
          boxShadow: '0 4px 15px rgba(255, 71, 87, 0.28)',
        }}
        onClose={() => {
          if (!deleting) setShowDeleteModal(false);
        }}
        onConfirm={handleDelete}
      >
        {deleteError ? <p style={{ color: '#b42318', fontSize: '0.85rem' }} dir="auto">{deleteError}</p> : null}
      </ConfirmModal>

      <div className="admin-page-header">
        <div>
          <div className="admin-page-kicker">
            <FileText size={14} /> {t('detail.kicker')}
          </div>
          <h1 className="admin-page-title" dir="auto">{data?.title || t('detail.titleFallback')}</h1>
          {data?.source || data?.author || data?.published ? (
            <p className="admin-page-subtitle" dir="auto">
              {[data?.source, data?.author ? t('common.byAuthor', { author: data.author }) : null, data?.published ? displayDate(data.published, locale) : null]
                .filter(Boolean)
                .join(' · ')}
            </p>
          ) : null}
        </div>
        <div className="admin-page-toolbar">
          <Link to={backTo} className="btn-secondary" style={{ textDecoration: 'none' }}>
            <ArrowLeft size={16} className="rtl-mirror" /> {t('detail.backToArticles')}
          </Link>
          {canReprocess ? (
            <button type="button" className="btn-secondary" onClick={handleReprocess} disabled={reprocessing || loading}>
              {reprocessing ? t('detail.reprocessingButton') : t('detail.reprocessButton')}
            </button>
          ) : null}
          {canDelete ? (
            <button
              type="button"
              className="btn-secondary"
              style={{ color: '#b42318', borderColor: 'rgba(180,35,24,0.18)' }}
              onClick={() => setShowDeleteModal(true)}
              // Gated on `data`, not just `loading`: a failed/404 load
              // leaves `data` null with `loading` already false, and
              // confirming a delete with no article to name and no
              // confirmed title is worse than just disabling the button.
              disabled={loading || !data}
              title={!loading && !data ? t('detail.deleteDisabledTitle') : undefined}
            >
              <Trash2 size={16} /> {t('detail.deleteButton')}
            </button>
          ) : null}
        </div>
      </div>

      {loading ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-light)', padding: '24px 0' }}>
          <Loader2 size={18} className="spin" /> {t('detail.loading')}
        </div>
      ) : error ? (
        <div className="glass-card" style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#b42318', borderLeft: '4px solid #ff4757' }}>
          <AlertTriangle size={18} /> <span dir="auto">{error}</span>
        </div>
      ) : !data ? (
        <div className="glass-card">
          <p className="subtitle">{t('detail.noData')}</p>
        </div>
      ) : (
        <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <span
              className={`badge ${
                data.analysis_status === 'failed' ? 'negative' : data.analysis_status === 'success' ? 'positive' : 'neutral'
              }`}
            >
              {t(STATUS_LABEL_KEYS[data.analysis_status] || 'common:status.unknown')}
            </span>
            {data.analysis_error ? <span className="badge negative" dir="auto">{data.analysis_error}</span> : null}
          </div>

          {data.summary ? <p className="article-summary" dir="auto">{data.summary}</p> : null}

          <div>
            <strong>{t('detail.sentimentLabel')}</strong>{' '}
            <span className={`badge ${sentimentBadgeState(data)}`}>
              {t(SENTIMENT_STATE_LABEL_KEYS[sentimentBadgeState(data)] || 'sentiment.notAssessed')}
            </span>
            {formatPercent(data.confidence?.sentiment, locale) && (
              <span style={{ marginLeft: 6, color: 'var(--text-light)', fontSize: '0.85rem' }}>
                {data.confidence?.sentiment_low_confidence
                  ? t('detail.confidenceLowConfidence', { pct: formatPercent(data.confidence.sentiment, locale) })
                  : t('detail.confidence', { pct: formatPercent(data.confidence.sentiment, locale) })}
              </span>
            )}
          </div>
          <div>
            <strong>{t('detail.categoryLabel')}</strong>{' '}
            {data.classification_status === 'ran' || !Object.prototype.hasOwnProperty.call(data, 'classification_status')
              ? prettyLabel(data.article_category)
              : t('sentiment.notAssessed')}
            {formatPercent(data.confidence?.category, locale) && (
              <span style={{ marginLeft: 6, color: 'var(--text-light)', fontSize: '0.85rem' }}>
                {t('detail.confidence', { pct: formatPercent(data.confidence.category, locale) })}
              </span>
            )}
          </div>
          <div>
            <strong>{t('detail.writerToneLabel')}</strong> {prettyLabel(data.writer_tone)}
            {formatPercent(data.confidence?.writer_tone, locale) && (
              <span style={{ marginLeft: 6, color: 'var(--text-light)', fontSize: '0.85rem' }}>
                {t('detail.confidence', { pct: formatPercent(data.confidence.writer_tone, locale) })}
              </span>
            )}
          </div>
          <div>
            <strong>{t('detail.articleToneLabel')}</strong> {prettyLabel(data.article_tone)}
            {formatPercent(data.confidence?.article_tone, locale) && (
              <span style={{ marginLeft: 6, color: 'var(--text-light)', fontSize: '0.85rem' }}>
                {t('detail.confidence', { pct: formatPercent(data.confidence.article_tone, locale) })}
              </span>
            )}
          </div>
          <div>
            <strong>{t('detail.overallToneLabel')}</strong> {prettyLabel(data.overall_tone)}
          </div>
          <div>
            <strong>{t('detail.regionLabel')}</strong> {prettyLabel(data.region)}
            {formatPercent(data.confidence?.region, locale) && (
              <span style={{ marginLeft: 6, color: 'var(--text-light)', fontSize: '0.85rem' }}>
                {t('detail.confidence', { pct: formatPercent(data.confidence.region, locale) })}
              </span>
            )}
          </div>
          {data.source_language ? (
            <div>
              <strong>{t('detail.sourceLanguageLabel')}</strong> {formatLanguageName(data.source_language, locale)}
              {formatPercent(data.source_language_confidence, locale) && (
                <span style={{ marginLeft: 6, color: 'var(--text-light)', fontSize: '0.85rem' }}>
                  {t('detail.confidence', { pct: formatPercent(data.source_language_confidence, locale) })}
                </span>
              )}
            </div>
          ) : null}

          <div style={{ fontSize: '0.82rem', color: 'var(--text-light)', borderTop: '1px solid rgba(0,0,0,0.08)', paddingTop: 10 }}>
            <div>
              {t('detail.modelsLine', {
                sentiment: data.models?.sentiment || t('detail.notApplicable'),
                classification: data.models?.classification || t('detail.notApplicable'),
                extraction: data.models?.extraction || t('detail.notApplicable'),
              })}
            </div>
            <div style={{ marginTop: 4 }}>
              {t('detail.attemptsLine', {
                count: data.processing?.attempt_count ?? 0,
                lastRun: data.processing?.finished_at ? formatDateTime(data.processing.finished_at, locale) : t('detail.notYet'),
              })}
            </div>
          </div>

          {actionMessage ? <p style={{ fontSize: '0.85rem', color: 'var(--text-light)' }} dir="auto">{actionMessage}</p> : null}
        </div>
      )}

      {!loading && !error && data?.text ? (
        <div className="glass-card" style={{ marginTop: 18 }}>
          <h3 className="run-detail-section-title">{t('detail.fullArticleHeading')}</h3>
          <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.6, fontSize: '0.95rem' }} dir="auto">{data.text}</div>
        </div>
      ) : null}
    </div>
  );
}
