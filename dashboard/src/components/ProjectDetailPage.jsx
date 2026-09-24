import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { motion } from 'framer-motion';
import { useTranslation } from 'react-i18next';
import ConfirmModal from './ConfirmModal';
import DemographicSentimentChart from './DemographicSentimentChart';
import SurveyObservationsChart from './SurveyObservationsChart';
import { useAuth } from '../auth/useAuth.js';
import { translateApiError } from '../lib/apiError.js';
import { formatDate as formatDateIntl, formatDateTime as formatDateTimeIntl, formatNumber } from '../lib/i18nFormat.js';
import {
  ArrowLeft,
  BarChart3,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  FileText,
  ShieldCheck,
  Lightbulb,
  Link2,
  Loader2,
  MapPin,
  Play,
  Tag,
  Pencil,
  RefreshCw,
  Trash2,
} from 'lucide-react';
import { startAnalysisRun } from '../api/pipelineRunsApi.js';
import { listIdeaClusters, listIdeaClusterArticles } from '../api/projectsApi.js';
import { listDocuments } from '../api/projectDocumentsApi.js';
import { getArticleStats } from '../api/articlesApi.js';
import '../styles/ProjectDetail.css';

const DOCUMENTS_PAGE_SIZE = 5;

function documentStatusTone(status) {
  if (status === 'processed') return 'success';
  if (status === 'failed') return 'danger';
  return 'muted';
}

function formatBytes(value, locale) {
  const bytes = Number(value || 0);
  if (!bytes) return '';
  if (bytes < 1024) return `${formatNumber(bytes, locale)} B`;
  if (bytes < 1024 * 1024) return `${formatNumber(Math.round(bytes / 1024), locale)} KB`;
  return `${formatNumber(bytes / (1024 * 1024), locale, { maximumFractionDigits: 1, minimumFractionDigits: 1 })} MB`;
}

function normalizeList(value) {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item || '').trim()).filter(Boolean);
}

function prettyLabel(value) {
  return String(value || '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

export default function ProjectDetailPage({
  projects = [],
  users = [],
  onDeleteProject,
}) {
  const navigate = useNavigate();
  const params = useParams();
  const { t, i18n } = useTranslation('projects');
  const { t: tErrors } = useTranslation('errors');
  const locale = i18n.language;
  const formatDate = (value) => formatDateIntl(value, locale) || t('detail.overview.notSet');
  const formatDateTime = (value) => formatDateTimeIntl(value, locale) || t('detail.analysis.notYet');
  const locationTypeLabels = {
    on_site: t('shared.locationTypeLabels.on_site'),
    remote: t('shared.locationTypeLabels.remote'),
    hybrid: t('shared.locationTypeLabels.hybrid'),
  };
  const documentStatusLabels = {
    uploaded: t('documents:detail.documents.statusLabels.uploaded'),
    processing: t('documents:detail.documents.statusLabels.processing'),
    processed: t('documents:detail.documents.statusLabels.processed'),
    failed: t('documents:detail.documents.statusLabels.failed'),
  };
  const articlesStatusLabels = {
    pending: t('documents:detail.documents.articlesStatusLabels.pending'),
    generating: t('documents:detail.documents.articlesStatusLabels.generating'),
    ready: t('documents:detail.documents.articlesStatusLabels.ready'),
    failed: t('documents:detail.documents.articlesStatusLabels.failed'),
    skipped: t('documents:detail.documents.articlesStatusLabels.skipped'),
  };
  const lastRunStatusLabels = {
    success: t('detail.analysis.statusLabels.success'),
    failed: t('detail.analysis.statusLabels.failed'),
    cancelled: t('detail.analysis.statusLabels.cancelled'),
  };
  const { hasPermission } = useAuth();
  const canEdit = hasPermission('projects.update') || hasPermission('projects.delete');
  const canLinkUsers = hasPermission('projects.link_users');
  const canRunAnalysis = hasPermission('pipeline.run');
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [documents, setDocuments] = useState([]);
  const [documentsPage, setDocumentsPage] = useState(1);
  const [analysisStarting, setAnalysisStarting] = useState(false);
  const [analysisNotice, setAnalysisNotice] = useState('');
  const [analysisError, setAnalysisError] = useState('');
  const [articleStats, setArticleStats] = useState(null);
  const [statsLoading, setStatsLoading] = useState(false);
  const [ideaClusters, setIdeaClusters] = useState({ clusters: [], total: 0, limit: 10, offset: 0 });
  const [ideaClustersLoading, setIdeaClustersLoading] = useState(false);
  const [ideaClustersError, setIdeaClustersError] = useState('');
  const [ideaOffset, setIdeaOffset] = useState(0);
  const [openingClusterId, setOpeningClusterId] = useState(null);
  const [clusterOpenErrors, setClusterOpenErrors] = useState({});

  const project = useMemo(
    () => projects.find((item) => Number(item.id) === Number(params.projectId)) || null,
    [projects, params.projectId]
  );

  // Reset project-scoped controls after navigation. React 19 can reject
  // render-phase state updates as a render loop, so this belongs in an effect.
  useEffect(() => {
    setDocumentsPage(1);
    setAnalysisNotice('');
    setAnalysisError('');
    setIdeaOffset(0);
    setOpeningClusterId(null);
    setClusterOpenErrors({});
  }, [project?.id]);

  useEffect(() => {
    const controller = new AbortController();
    async function loadArticleStats() {
      if (!project?.id) {
        setArticleStats(null);
        return;
      }
      setStatsLoading(true);
      try {
        const data = await getArticleStats({ project_id: project.id }, controller.signal);
        setArticleStats(data);
      } catch (err) {
        if (err?.name !== 'AbortError') setArticleStats(null);
      } finally {
        setStatsLoading(false);
      }
    }
    loadArticleStats();
    return () => controller.abort();
  }, [project?.id]);

  useEffect(() => {
    const controller = new AbortController();
    async function loadIdeaClusters() {
      if (!project?.id) {
        setIdeaClusters({ clusters: [], total: 0, limit: 10, offset: 0 });
        return;
      }
      setIdeaClustersLoading(true);
      setIdeaClustersError('');
      try {
        const data = await listIdeaClusters(project.id, { limit: 10, offset: ideaOffset }, controller.signal);
        setIdeaClusters({
          clusters: Array.isArray(data?.clusters) ? data.clusters : [],
          total: Number(data?.total) || 0,
          limit: Number(data?.limit) || 10,
          offset: Number(data?.offset) || 0,
        });
      } catch (err) {
        if (err?.name !== 'AbortError') {
          setIdeaClusters({ clusters: [], total: 0, limit: 10, offset: 0 });
          setIdeaClustersError(err?.code ? translateApiError(tErrors, err) : (err?.message || t('detail.ideas.errors.loadFailed')));
        }
      } finally {
        setIdeaClustersLoading(false);
      }
    }
    loadIdeaClusters();
    return () => controller.abort();
  }, [project?.id, ideaOffset, t, tErrors]);

  // A cluster's persisted frequency can span far more articles than fit in
  // this page's list - fetch a large-but-bounded page of its representative
  // articles up front, then hand them to TopicDetailPage via router state so
  // its chart/attribution can be built from real data without a second fetch.
  const openClusterTopic = async (cluster) => {
    setOpeningClusterId(cluster.id);
    setClusterOpenErrors((current) => ({ ...current, [cluster.id]: '' }));
    try {
      const data = await listIdeaClusterArticles(project.id, cluster.id, { limit: 200 });
      const clusterSources = (Array.isArray(data?.articles) ? data.articles : []).map((article) => ({
        id: article.id,
        url: article.url,
        title: article.title,
        pipelineRunId: article.pipeline_run_id,
        published: article.published,
        source: article.source,
        summary: article.summary,
        sentiment: article.sentiment,
      }));
      navigate(`/projects/${project.id}/topics`, {
        state: {
          idea: cluster.idea,
          type: cluster.type,
          category: cluster.category,
          frequencyEstimate: cluster.frequency_estimate,
          projectId: project.id,
          sources: clusterSources,
          backTo: '/dashboard',
          backLabel: t('detail.ideas.backToDashboard'),
        },
      });
    } catch (err) {
      setClusterOpenErrors((current) => ({
        ...current,
        [cluster.id]: err?.code ? translateApiError(tErrors, err) : (err?.message || t('detail.ideas.errors.openArticlesFailed')),
      }));
    } finally {
      setOpeningClusterId(null);
    }
  };

  useEffect(() => {
    if (!project?.id) {
      setDocuments([]);
      return undefined;
    }
    let cancelled = false;
    listDocuments(project.id)
      .then((data) => { if (!cancelled) setDocuments(Array.isArray(data?.documents) ? data.documents : []); })
      .catch(() => { if (!cancelled) setDocuments([]); });
    return () => { cancelled = true; };
  }, [project?.id]);

  const startAnalysis = async () => {
    if (!project?.id) return;
    setAnalysisStarting(true);
    setAnalysisNotice('');
    setAnalysisError('');
    try {
      const data = await startAnalysisRun({ project_id: Number(project.id), scope: 'pending' });
      setAnalysisNotice(data?.message || t('detail.analysis.started'));
    } catch (err) {
      setAnalysisError(err?.code ? translateApiError(tErrors, err) : (err?.message || t('detail.errors.startAnalysisFailed')));
    } finally {
      setAnalysisStarting(false);
    }
  };

  const linkedUsers = useMemo(() => {
    if (!project) return [];
    const userIds = new Set((project.user_ids || []).map((value) => Number(value)));
    return users.filter((user) => userIds.has(Number(user.id)));
  }, [project, users]);

  const totalDocumentsPages = Math.max(1, Math.ceil(documents.length / DOCUMENTS_PAGE_SIZE));
  const safeDocumentsPage = Math.min(documentsPage, totalDocumentsPages);
  const pagedDocuments = useMemo(() => {
    const start = (safeDocumentsPage - 1) * DOCUMENTS_PAGE_SIZE;
    return documents.slice(start, start + DOCUMENTS_PAGE_SIZE);
  }, [documents, safeDocumentsPage]);

  const keywordList = normalizeList(project?.keywords);

  const status = String(project?.status || 'draft').toLowerCase();
  const isActive = status === 'active';
  const isArchived = status === 'archived';
  const statusLabel = (t(`shared.statusLabels.${status}`, { defaultValue: status }) || status).toUpperCase();

  if (!project) {
    return (
      <div className="admin-page-shell project-detail-page">
        <div className="glass-card" style={{ maxWidth: 960, margin: '0 auto' }}>
          <div className="admin-empty-state" style={{ padding: '34px 20px' }}>
            <div className="admin-empty-state-icon">
              <CalendarDays size={18} />
            </div>
            <strong>{t('detail.notFound.title')}</strong>
            <span>{t('detail.notFound.body')}</span>
            <Link to="/projects" className="btn-primary" style={{ marginTop: 8, textDecoration: 'none' }}>
              <ArrowLeft size={16} className="rtl-mirror" /> {t('detail.notFound.backToProjects')}
            </Link>
          </div>
        </div>
      </div>
    );
  }

  const handleDelete = async () => {
    if (!onDeleteProject) return;
    await onDeleteProject(project.id);
    navigate('/projects');
  };

  return (
    <div className="admin-page-shell project-detail-page">
      <div className="admin-page-header">
        <div>
          <div className="admin-page-kicker">
            <CalendarDays size={14} /> {t('detail.kicker')}
          </div>
          <h1 className="admin-page-title" dir="auto">{project.name}</h1>
          <p className="admin-page-subtitle">
            {t('detail.subtitle')}
          </p>
        </div>

        <div className="admin-page-toolbar">
          <div className="admin-page-toolbar-meta">
            <span>{t('detail.toolbar.statusLabel')}</span>
            <strong>{statusLabel}</strong>
          </div>
          <div className="admin-page-toolbar-meta">
            <span>{t('detail.toolbar.documentsLabel')}</span>
            <strong>{formatNumber(documents.length, locale)}</strong>
          </div>
          <Link to={`/projects/${project.id}/evidence`} className="btn-secondary" style={{ textDecoration: 'none' }}>
            <ShieldCheck size={16} /> {t('detail.actions.evidence')}
          </Link>
          {canEdit && (
            <>
              <Link to={`/projects/${project.id}/edit`} className="btn-secondary" style={{ textDecoration: 'none' }}>
                <Pencil size={16} /> {t('detail.actions.editProject')}
              </Link>
              <button
                type="button"
                className="btn-secondary"
                onClick={() => setDeleteOpen(true)}
                style={{ color: '#ff4757' }}
              >
                <Trash2 size={16} /> {t('common:actions.delete')}
              </button>
            </>
          )}
        </div>
      </div>

      <div className="project-detail-layout">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35 }}
          className="glass-card"
          style={{ display: 'flex', flexDirection: 'column', gap: 16 }}
        >
          <div className="panel-header-tight">
            <strong style={{ fontSize: '1rem' }}>{t('detail.overview.title')}</strong>
            <span className={`panel-chip ${isActive ? 'success' : isArchived ? 'muted' : 'warning'}`}>{statusLabel}</span>
          </div>

          <div className="project-detail-summary-grid">
            <div className="admin-item-card" style={{ margin: 0 }}>
              <div className="admin-item-meta" style={{ marginBottom: 8 }}>
                <span><CalendarDays size={12} /> {t('detail.overview.start')}</span>
                <span><CalendarDays size={12} /> {t('detail.overview.end')}</span>
              </div>
              <strong style={{ fontSize: '0.98rem' }}>{formatDate(project.start_date)}</strong>
              <div style={{ color: 'var(--text-light)', fontSize: '0.84rem', marginTop: 4 }}>{formatDate(project.end_date)}</div>
            </div>

            <div className="admin-item-card" style={{ margin: 0 }}>
              <div className="admin-item-meta" style={{ marginBottom: 8 }}>
                <span><MapPin size={12} /> {t('detail.overview.location')}</span>
                <span><Tag size={12} /> {t('detail.overview.audience')}</span>
              </div>
              <strong style={{ fontSize: '0.98rem' }} dir="auto">
                {project.location || t('detail.overview.notSet')}
                {project.location_type ? ` (${locationTypeLabels[project.location_type] || prettyLabel(project.location_type)})` : ''}
              </strong>
              <div style={{ color: 'var(--text-light)', fontSize: '0.84rem', marginTop: 4 }} dir="auto">{project.target_audience || t('detail.overview.noAudience')}</div>
            </div>
          </div>

          <div className="admin-item-card" style={{ margin: 0 }}>
            <div className="panel-header-tight" style={{ marginBottom: 10 }}>
              <strong style={{ fontSize: '0.94rem' }}><RefreshCw size={14} style={{ verticalAlign: -2 }} /> {t('detail.analysis.title')}</strong>
              <span className={`panel-chip ${project.last_run_status === 'success' ? 'success' : 'muted'}`}>
                {project.last_run_status ? (lastRunStatusLabels[project.last_run_status] || project.last_run_status) : t('detail.analysis.neverRun')}
              </span>
            </div>
            <div style={{ display: 'grid', gap: 10, color: 'var(--text-light)', fontSize: '0.86rem' }}>
              <div className="admin-item-meta">
                <span>{t('detail.analysis.lastRun', { value: formatDateTime(project.last_run_at) })}</span>
                <Link to="/pipeline-runs">{t('detail.analysis.allRuns')}</Link>
              </div>
              {canRunAnalysis ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={startAnalysis}
                    disabled={analysisStarting}
                    style={{ padding: '8px 12px', fontSize: '0.82rem' }}
                  >
                    <Play size={14} /> {analysisStarting ? t('detail.analysis.starting') : t('detail.analysis.analyzeButton')}
                  </button>
                  <span>{t('detail.analysis.hint')}</span>
                </div>
              ) : null}
              {analysisNotice ? <div style={{ color: 'var(--text-dark)' }} dir="auto">{analysisNotice}</div> : null}
              {analysisError ? <div style={{ color: '#b42318' }} dir="auto">{analysisError}</div> : null}
            </div>
          </div>

          <div className="admin-item-card" style={{ margin: 0 }}>
            <div className="panel-header-tight" style={{ marginBottom: 10 }}>
              <strong style={{ fontSize: '0.94rem' }}>{t('detail.description.title')}</strong>
            </div>
            <div style={{ color: 'var(--text-light)', lineHeight: 1.7, whiteSpace: 'pre-wrap' }} dir="auto">
              {project.description || t('detail.description.empty')}
            </div>
          </div>

          <div className="admin-item-card" style={{ margin: 0 }}>
            <div className="panel-header-tight" style={{ marginBottom: 10 }}>
              <strong style={{ fontSize: '0.94rem' }}>{t('detail.topics.title')}</strong>
            </div>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, color: 'var(--text-light)', fontSize: '0.8rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                <Link2 size={14} /> {t('detail.topics.keywordsLabel')}
              </div>
              <div className="admin-item-chips">
                {keywordList.length ? keywordList.map((item) => (
                  <span key={item} className="admin-tag muted" dir="auto">{item}</span>
                )) : <span className="admin-tag muted">{t('detail.topics.noKeywords')}</span>}
              </div>
              <div style={{ color: 'var(--text-light)', fontSize: '0.82rem', marginTop: 8 }}>
                {t('detail.topics.hint')}
              </div>
            </div>
          </div>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, delay: 0.05 }}
          className="glass-card"
          style={{ display: 'flex', flexDirection: 'column', gap: 16 }}
        >
          <div className="panel-header-tight">
            <strong style={{ fontSize: '1rem' }}>{t('documents:detail.documents.title')}</strong>
            <span style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span className="panel-chip">{t('documents:detail.documents.uploadedCount', { count: documents.length, formattedCount: formatNumber(documents.length, locale) })}</span>
              <Link to={`/sources?project_id=${project.id}`} style={{ color: '#2563eb', fontWeight: 600, textDecoration: 'none', fontSize: '0.82rem', whiteSpace: 'nowrap' }}>
                {t('documents:detail.documents.viewSources')}
              </Link>
            </span>
          </div>

          {documents.length === 0 ? (
            <div className="admin-empty-state" style={{ padding: '20px 12px' }}>
              <div className="admin-empty-state-icon">
                <FileText size={18} />
              </div>
              <strong>{t('documents:detail.documents.emptyTitle')}</strong>
              <span>{t('documents:detail.documents.emptyBody')}</span>
            </div>
          ) : (
            <>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {pagedDocuments.map((document) => (
                  <div key={document.id} className="admin-item-card" style={{ margin: 0 }}>
                    <div className="admin-item-top">
                      <div style={{ minWidth: 0 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 6 }}>
                          <strong className="admin-item-title project-detail-break-text" dir="auto">
                            {document.original_filename || t('documents:detail.documents.fallbackName', { id: document.id })}
                          </strong>
                          <span className={`panel-chip ${documentStatusTone(document.status)}`}>
                            {documentStatusLabels[document.status] || document.status || documentStatusLabels.uploaded}
                          </span>
                        </div>
                        <div className="admin-item-meta">
                          <span>{formatBytes(document.size_bytes, locale)}</span>
                          <span>{t('documents:detail.documents.articlesLabel', { value: articlesStatusLabels[document.articles_status] || document.articles_status || articlesStatusLabels.pending })}</span>
                          <span>{t('documents:detail.documents.added', { value: formatDate(document.created_at) })}</span>
                        </div>
                        {document.extraction_error ? (
                          <div className="admin-item-meta" style={{ color: '#b42318' }}>
                            <span dir="auto">{document.extraction_error}</span>
                          </div>
                        ) : null}
                      </div>
                    </div>
                  </div>
                ))}
              </div>

              {documents.length > DOCUMENTS_PAGE_SIZE && (
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    gap: 12,
                    flexWrap: 'wrap',
                    paddingTop: 6,
                    borderTop: '1px solid rgba(15, 23, 42, 0.08)',
                  }}
                >
                  <div style={{ fontSize: '0.84rem', color: 'var(--text-light)' }}>
                    {t('documents:detail.documents.pagination.showingRange', {
                      from: formatNumber((safeDocumentsPage - 1) * DOCUMENTS_PAGE_SIZE + 1, locale),
                      to: formatNumber(Math.min(safeDocumentsPage * DOCUMENTS_PAGE_SIZE, documents.length), locale),
                      total: formatNumber(documents.length, locale),
                    })}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={() => setDocumentsPage((value) => Math.max(1, value - 1))}
                      disabled={safeDocumentsPage <= 1}
                      style={{ padding: '8px 10px', fontSize: '0.8rem' }}
                    >
                      <ChevronLeft size={14} className="rtl-mirror" /> {t('common:actions.previous')}
                    </button>
                    <span className="panel-chip">
                      {t('common:pagination.pageOfTotal', { page: formatNumber(safeDocumentsPage, locale), totalPages: formatNumber(totalDocumentsPages, locale) })}
                    </span>
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={() => setDocumentsPage((value) => Math.min(totalDocumentsPages, value + 1))}
                      disabled={safeDocumentsPage >= totalDocumentsPages}
                      style={{ padding: '8px 10px', fontSize: '0.8rem' }}
                    >
                      {t('common:actions.next')} <ChevronRight size={14} className="rtl-mirror" />
                    </button>
                  </div>
                </div>
              )}
            </>
          )}

          <div className="admin-item-card" style={{ margin: 0 }}>
            <div className="panel-header-tight" style={{ marginBottom: 10 }}>
              <strong style={{ fontSize: '0.94rem' }}>{t('detail.quickFacts.title')}</strong>
            </div>
            <div style={{ display: 'grid', gap: 10 }}>
              <div className="admin-item-meta">
                <span>{t('detail.quickFacts.created', { value: formatDate(project.created_at) })}</span>
                <span>{t('detail.quickFacts.updated', { value: formatDate(project.updated_at) })}</span>
              </div>
              <div className="admin-item-meta">
                <span>{t('detail.quickFacts.documentCount', { count: documents.length, formattedCount: formatNumber(documents.length, locale) })}</span>
                <span>{t('detail.quickFacts.keywordCount', { count: keywordList.length, formattedCount: formatNumber(keywordList.length, locale) })}</span>
              </div>
              {canLinkUsers && (
                <div className="admin-item-meta">
                  <span>{t('detail.quickFacts.linkedUserCount', { count: linkedUsers.length, formattedCount: formatNumber(linkedUsers.length, locale) })}</span>
                </div>
              )}
              {canLinkUsers && linkedUsers.length > 0 && (
                <div className="admin-item-chips">
                  {linkedUsers.map((user) => (
                    <span key={user.id} className="admin-tag muted" dir="auto">{user.username}</span>
                  ))}
                </div>
              )}
            </div>
          </div>
        </motion.div>
      </div>

      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, delay: 0.1 }}
        className="glass-card"
        style={{ display: 'flex', flexDirection: 'column', gap: 16, marginTop: 24 }}
      >
        <div className="panel-header-tight">
          <strong style={{ fontSize: '1rem' }}>{t('detail.insights.title')}</strong>
          <span className="panel-chip">{t('detail.insights.analyzedCount', { count: articleStats?.total || 0, formattedCount: formatNumber(articleStats?.total || 0, locale) })}</span>
        </div>

        {statsLoading ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-light)', fontSize: '0.86rem', padding: '12px 0' }}>
            <Loader2 size={16} className="spin" /> {t('detail.insights.loading')}
          </div>
        ) : !articleStats?.total ? (
          <div className="admin-empty-state" style={{ padding: '20px 12px' }}>
            <div className="admin-empty-state-icon">
              <BarChart3 size={18} />
            </div>
            <strong>{t('detail.insights.emptyTitle')}</strong>
            <span>{t('detail.insights.emptyBody')}</span>
          </div>
        ) : (
          <>
            {(articleStats?.insights?.survey_observations || []).length ? (
              <div className="admin-item-card" style={{ margin: 0, gridColumn: '1 / -1' }}>
                <SurveyObservationsChart observations={articleStats.insights.survey_observations} />
              </div>
            ) : null}
            <div className="project-detail-summary-grid">
              <div className="admin-item-card" style={{ margin: 0 }}>
                <div className="admin-item-meta" style={{ marginBottom: 8 }}>
                  <span>{t('detail.insights.overallMood')}</span>
                </div>
                <strong style={{ fontSize: '0.98rem' }}>{prettyLabel(articleStats?.insights?.overall_mood || 'neutral')}</strong>
              </div>

              <div className="admin-item-card" style={{ margin: 0 }}>
                <div className="admin-item-meta" style={{ marginBottom: 8 }}>
                  <span>{t('detail.insights.overallTone')}</span>
                </div>
                <strong style={{ fontSize: '0.98rem' }}>{prettyLabel(articleStats?.insights?.overall_tone || 'neutral')}</strong>
              </div>
            </div>

            <div className="admin-item-card" style={{ margin: 0 }}>
              <div className="panel-header-tight" style={{ marginBottom: 10 }}>
                <strong style={{ fontSize: '0.94rem' }}>{t('detail.insights.writerToneBreakdown')}</strong>
              </div>
              <div className="admin-item-chips">
                {(articleStats?.insights?.writer_tone_breakdown || []).length ? (
                  articleStats.insights.writer_tone_breakdown.map((item) => (
                    <span key={item.tone} className="admin-tag muted">{prettyLabel(item.tone)} ({formatNumber(item.count, locale)})</span>
                  ))
                ) : (
                  <span className="admin-tag muted">{t('common:emptyState.noData')}</span>
                )}
              </div>
            </div>

            <div className="admin-item-card" style={{ margin: 0 }}>
              <div className="panel-header-tight" style={{ marginBottom: 10 }}>
                <strong style={{ fontSize: '0.94rem' }}>{t('detail.insights.articleToneBreakdown')}</strong>
              </div>
              <div className="admin-item-chips">
                {(articleStats?.insights?.article_tone_breakdown || []).length ? (
                  articleStats.insights.article_tone_breakdown.map((item) => (
                    <span key={item.tone} className="admin-tag muted">{prettyLabel(item.tone)} ({formatNumber(item.count, locale)})</span>
                  ))
                ) : (
                  <span className="admin-tag muted">{t('common:emptyState.noData')}</span>
                )}
              </div>
            </div>

            <div className="admin-item-card" style={{ margin: 0 }}>
              <div className="panel-header-tight" style={{ marginBottom: 10 }}>
                <strong style={{ fontSize: '0.94rem' }}>{t('detail.insights.sentimentByRegion')}</strong>
              </div>
              <DemographicSentimentChart title={t('detail.insights.chartTitleRegion')} data={articleStats?.insights?.region_breakdown} />
            </div>

            <div className="admin-item-card" style={{ margin: 0 }}>
              <div className="panel-header-tight" style={{ marginBottom: 10 }}>
                <strong style={{ fontSize: '0.94rem' }}>{t('detail.insights.sentimentByGender')}</strong>
              </div>
              <DemographicSentimentChart title={t('detail.insights.chartTitleGender')} data={articleStats?.insights?.gender_breakdown} />
            </div>

            <div className="admin-item-card" style={{ margin: 0 }}>
              <div className="panel-header-tight" style={{ marginBottom: 10 }}>
                <strong style={{ fontSize: '0.94rem' }}>{t('detail.insights.sentimentByAgeRange')}</strong>
              </div>
              <DemographicSentimentChart title={t('detail.insights.chartTitleAgeRange')} data={articleStats?.insights?.age_range_breakdown} />
            </div>

            <div className="admin-item-card" style={{ margin: 0 }}>
              <div className="panel-header-tight" style={{ marginBottom: 10 }}>
                <strong style={{ fontSize: '0.94rem' }}>{t('detail.insights.sentimentBySegment')}</strong>
              </div>
              <DemographicSentimentChart title={t('detail.insights.chartTitleSegment')} data={articleStats?.insights?.segment_breakdown} />
            </div>
          </>
        )}
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, delay: 0.15 }}
        className="glass-card"
        style={{ display: 'flex', flexDirection: 'column', gap: 16, marginTop: 24 }}
      >
        <div className="panel-header-tight">
          <strong style={{ fontSize: '1rem' }}>{t('detail.ideas.title')}</strong>
          <span className="panel-chip">{t('detail.ideas.clusterCount', { count: ideaClusters.total, formattedCount: formatNumber(ideaClusters.total, locale) })}</span>
        </div>
        <p className="subtitle" style={{ margin: 0 }}>
          {t('detail.ideas.description')}
        </p>

        {ideaClustersError ? (
          <div className="admin-empty-state" style={{ padding: '20px 12px' }}>
            <div className="admin-empty-state-icon">
              <Lightbulb size={18} />
            </div>
            <strong>{t('detail.ideas.loadError')}</strong>
            <span dir="auto">{ideaClustersError}</span>
          </div>
        ) : ideaClustersLoading ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-light)', fontSize: '0.86rem', padding: '12px 0' }}>
            <Loader2 size={16} className="spin" /> {t('detail.ideas.loading')}
          </div>
        ) : ideaClusters.clusters.length === 0 ? (
          <div className="admin-empty-state" style={{ padding: '20px 12px' }}>
            <div className="admin-empty-state-icon">
              <Lightbulb size={18} />
            </div>
            <strong>{t('detail.ideas.emptyTitle')}</strong>
            <span>{t('detail.ideas.emptyBody')}</span>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {ideaClusters.clusters.map((cluster) => {
              const isOpening = openingClusterId === cluster.id;
              const openError = clusterOpenErrors[cluster.id];
              return (
                <div key={cluster.id} className="admin-item-card admin-item-card-clickable" style={{ margin: 0 }}>
                  <button
                    type="button"
                    onClick={() => openClusterTopic(cluster)}
                    disabled={isOpening}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      width: '100%',
                      gap: 10,
                      background: 'none',
                      border: 'none',
                      padding: 0,
                      cursor: isOpening ? 'wait' : 'pointer',
                      textAlign: 'left',
                      font: 'inherit',
                      color: 'inherit',
                    }}
                  >
                    <span style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                      {isOpening ? <Loader2 size={16} className="spin" style={{ flexShrink: 0 }} /> : <ChevronRight size={16} style={{ flexShrink: 0 }} />}
                      <strong style={{ fontSize: '0.92rem' }} dir="auto">{cluster.idea}</strong>
                      <span className="admin-tag muted">{cluster.type || 'issue'}</span>
                    </span>
                    <span className="panel-chip" style={{ flexShrink: 0 }}>
                      {t('detail.ideas.articlesCount', { count: cluster.frequency_estimate || 0, formattedCount: formatNumber(cluster.frequency_estimate || 0, locale) })}
                    </span>
                  </button>
                  {openError ? (
                    <span dir="auto" style={{ display: 'block', marginTop: 8, color: '#b42318', fontSize: '0.82rem' }}>{openError}</span>
                  ) : null}
                </div>
              );
            })}
          </div>
        )}

        {ideaClusters.total > ideaClusters.limit ? (
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
            <button
              className="btn-secondary"
              onClick={() => setIdeaOffset((prev) => Math.max(0, prev - ideaClusters.limit))}
              disabled={ideaOffset === 0 || ideaClustersLoading}
              style={{ padding: '6px 10px', fontSize: '0.78rem' }}
            >
              <ChevronLeft size={14} className="rtl-mirror" /> {t('common:actions.previous')}
            </button>
            <button
              className="btn-secondary"
              onClick={() => setIdeaOffset((prev) => prev + ideaClusters.limit)}
              disabled={ideaOffset + ideaClusters.limit >= ideaClusters.total || ideaClustersLoading}
              style={{ padding: '6px 10px', fontSize: '0.78rem' }}
            >
              {t('common:actions.next')} <ChevronRight size={14} className="rtl-mirror" />
            </button>
          </div>
        ) : null}
      </motion.div>

      <ConfirmModal
        open={deleteOpen}
        title={t('detail.deleteModal.title', { name: project.name })}
        message={t('detail.deleteModal.body')}
        confirmLabel={t('detail.deleteModal.confirmLabel')}
        cancelLabel={t('detail.deleteModal.cancelLabel')}
        confirmButtonStyle={{
          background: 'linear-gradient(135deg, #ff4757, #e03131)',
          boxShadow: '0 4px 15px rgba(255, 71, 87, 0.28)',
        }}
        onClose={() => setDeleteOpen(false)}
        onConfirm={handleDelete}
      />
    </div>
  );
}
