import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useLocation, useParams } from 'react-router-dom';
import { ArrowLeft, AlertTriangle, FileText, Loader2, Trash2 } from 'lucide-react';
import { getArticleAnalysis, reprocessArticle, removeArticleFromProject, restoreArticleToProject } from '../api/articlesApi.js';
import { categoryLabel, toneLabel, sentimentBadgeState, isLlmFallbackStatus } from '../lib/articleHelpers.jsx';
import { useDemographicLabels } from '../lib/demographicLabels.js';
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

// Tags a stage's value as coming from the structured-extraction LLM's own
// fallback answer (backend's 'ran_via_llm' outcome) rather than the
// dedicated HF/local classifier model, so it reads distinctly from a
// regular model-produced value.
function LlmFallbackTag({ t }) {
  return (
    <span className="badge neutral" style={{ marginLeft: 6, fontSize: '0.72rem' }} title={t('detail.llmFallbackHint')}>
      {t('detail.llmFallbackTag')}
    </span>
  );
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
  const location = useLocation();
  // Where "Back to Articles" should return to - the article list's own
  // path+query at the moment Details was clicked, so its filters/search/page
  // survive the round trip instead of resetting to the article library's
  // default view. Falls back to a bare /articles for any other way of
  // landing on this page (a direct link, a bookmark).
  const backTo = location.state?.from || '/articles';
  const { hasPermission } = useAuth();
  const canReprocess = hasPermission('pipeline.run');
  const canDelete = hasPermission('articles.delete');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [data, setData] = useState(null);
  const regionLabel = useDemographicLabels([data?.region]);
  const [reprocessing, setReprocessing] = useState(false);
  const [actionMessage, setActionMessage] = useState('');
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState('');
  // The project a removal would target. Auto-picked when the article is only
  // linked to one project; left for the user to choose from the modal's
  // dropdown when it's linked to several (the same article row can be shared
  // across projects, so "delete" has to say which link it means).
  const [selectedProjectId, setSelectedProjectId] = useState('');
  // Set right after a successful removal so the page can offer an inline
  // Undo instead of just navigating away - the article/project link still
  // exists in the trash table at this point, so restoring is instant.
  const [removedInfo, setRemovedInfo] = useState(null);
  const [restoring, setRestoring] = useState(false);
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
    setRemovedInfo(null);
    getArticleAnalysis(articleId, { locale }, controller.signal)
      .then((res) => setData(res?.analysis || null))
      .catch((err) => {
        if (err?.name !== 'AbortError') setError(err?.message || t('detail.loadFailed'));
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [articleId, locale, t]);

  const projects = data?.projects || [];
  // Derived at render time rather than mirrored into state via an effect:
  // whichever project selectedProjectId last pointed at, falling back to the
  // only (or first) project once the article data loads or a removal
  // changes the list.
  const effectiveProjectId = projects.some((p) => String(p.id) === String(selectedProjectId))
    ? selectedProjectId
    : String(projects[0]?.id || '');

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
    if (deleting || !effectiveProjectId) return;
    setDeleting(true);
    setDeleteError('');
    try {
      const target = projects.find((p) => String(p.id) === String(effectiveProjectId));
      await removeArticleFromProject(effectiveProjectId, articleId);
      // Stays on the page instead of navigating away - the article's row and
      // analysis are untouched, so there's something left to show, and an
      // inline Undo is only meaningful while the user is still looking at it.
      setShowDeleteModal(false);
      setRemovedInfo({ projectId: effectiveProjectId, projectName: target?.name || '' });
      setData((prev) => (prev ? { ...prev, projects: prev.projects.filter((p) => String(p.id) !== String(effectiveProjectId)) } : prev));
    } catch (err) {
      setDeleteError(err?.message || t('detail.deleteFailed'));
    } finally {
      setDeleting(false);
    }
  };

  const handleUndo = async () => {
    if (restoring || !removedInfo) return;
    setRestoring(true);
    setActionMessage('');
    try {
      await restoreArticleToProject(removedInfo.projectId, articleId);
      setActionMessage(t('detail.restoredBanner', { title: data?.title || t('common.untitledArticle'), project: removedInfo.projectName }));
      setData((prev) => (prev
        ? { ...prev, projects: [...prev.projects, { id: Number(removedInfo.projectId), name: removedInfo.projectName }] }
        : prev));
      setRemovedInfo(null);
    } catch (err) {
      setActionMessage(err?.message || t('detail.undoFailed'));
    } finally {
      setRestoring(false);
    }
  };

  return (
    <div className="admin-page-shell">
      <ConfirmModal
        open={showDeleteModal}
        title={t('detail.deleteModal.title')}
        message={
          projects.length > 1
            ? t('detail.deleteModal.messageMultiProject', { title: data?.title || t('common.untitledArticle') })
            : t('detail.deleteModal.messageSingleProject', {
                title: data?.title || t('common.untitledArticle'),
                project: (projects[0]?.display_name || projects[0]?.name) || '',
              })
        }
        confirmLabel={deleting ? t('detail.deleteModal.confirmLabelBusy') : t('detail.deleteModal.confirmLabel')}
        cancelLabel={t('detail.deleteModal.cancelLabel')}
        confirmDisabled={!effectiveProjectId}
        confirmButtonStyle={{
          background: 'linear-gradient(135deg, #ff4757, #e03131)',
          boxShadow: '0 4px 15px rgba(255, 71, 87, 0.28)',
        }}
        onClose={() => {
          if (!deleting) setShowDeleteModal(false);
        }}
        onConfirm={handleDelete}
      >
        {projects.length > 1 ? (
          <label style={{ display: 'block', fontSize: '0.85rem', margin: '8px 0' }}>
            {t('detail.deleteProjectLabel')}
            <select
              value={effectiveProjectId}
              onChange={(e) => setSelectedProjectId(e.target.value)}
              style={{ display: 'block', width: '100%', marginTop: 4 }}
            >
              {projects.map((p) => (
                <option key={p.id} value={p.id}>{p.display_name || p.name}</option>
              ))}
            </select>
          </label>
        ) : null}
        {deleteError ? <p style={{ color: '#b42318', fontSize: '0.85rem' }} dir="auto">{deleteError}</p> : null}
      </ConfirmModal>

      {removedInfo ? (
        <div className="glass-card" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, borderLeft: '4px solid #ff8787', marginBottom: 14 }}>
          <span dir="auto">{t('detail.removedBanner', { title: data?.title || t('common.untitledArticle'), project: removedInfo.projectName })}</span>
          <button type="button" className="btn-secondary" onClick={handleUndo} disabled={restoring}>
            {restoring ? t('detail.undoingButton') : t('detail.undoButton')}
          </button>
        </div>
      ) : null}

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
              // Also gated on having a project left to remove it from - once
              // the article has no project links, there's nothing left for
              // this project-scoped action to do.
              disabled={loading || !data || !projects.length}
              title={
                !loading && !data
                  ? t('detail.deleteDisabledTitle')
                  : !loading && data && !projects.length
                    ? t('detail.deleteDisabledNoProject')
                    : undefined
              }
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
            {isLlmFallbackStatus(data.sentiment_status) ? <LlmFallbackTag t={t} /> : null}
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
            {data.classification_status === 'ran' || data.classification_status === 'ran_via_llm'
              || !Object.prototype.hasOwnProperty.call(data, 'classification_status')
              ? categoryLabel(t, data.article_category)
              : t('sentiment.notAssessed')}
            {isLlmFallbackStatus(data.category_status) ? <LlmFallbackTag t={t} /> : null}
            {formatPercent(data.confidence?.category, locale) && (
              <span style={{ marginLeft: 6, color: 'var(--text-light)', fontSize: '0.85rem' }}>
                {t('detail.confidence', { pct: formatPercent(data.confidence.category, locale) })}
              </span>
            )}
          </div>
          <div>
            <strong>{t('detail.writerToneLabel')}</strong> {toneLabel(t, data.writer_tone)}
            {isLlmFallbackStatus(data.writer_tone_status) ? <LlmFallbackTag t={t} /> : null}
            {formatPercent(data.confidence?.writer_tone, locale) && (
              <span style={{ marginLeft: 6, color: 'var(--text-light)', fontSize: '0.85rem' }}>
                {t('detail.confidence', { pct: formatPercent(data.confidence.writer_tone, locale) })}
              </span>
            )}
          </div>
          <div>
            <strong>{t('detail.articleToneLabel')}</strong> {toneLabel(t, data.article_tone)}
            {isLlmFallbackStatus(data.article_tone_status) ? <LlmFallbackTag t={t} /> : null}
            {formatPercent(data.confidence?.article_tone, locale) && (
              <span style={{ marginLeft: 6, color: 'var(--text-light)', fontSize: '0.85rem' }}>
                {t('detail.confidence', { pct: formatPercent(data.confidence.article_tone, locale) })}
              </span>
            )}
          </div>
          <div>
            <strong>{t('detail.overallToneLabel')}</strong> {toneLabel(t, data.overall_tone)}
          </div>
          <div>
            <strong>{t('detail.regionLabel')}</strong> {regionLabel(data.region)}
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
