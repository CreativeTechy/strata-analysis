import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { motion } from 'framer-motion';
import ConfirmModal from './ConfirmModal';
import DemographicSentimentChart from './DemographicSentimentChart';
import { useAuth } from '../auth/useAuth.js';
import {
  ArrowLeft,
  BarChart3,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  Hash,
  Lightbulb,
  Link2,
  Loader2,
  MapPin,
  AtSign,
  Tag,
  Pencil,
  RefreshCw,
  Trash2,
} from 'lucide-react';
import '../styles/ProjectDetail.css';

const SOURCES_PAGE_SIZE = 3;

const SOURCE_TYPE_OPTIONS = [
  { value: 'rss', label: 'RSS' },
  { value: 'web', label: 'Web' },
  { value: 'social', label: 'Social' },
  { value: 'hashtag', label: 'Hashtag' },
  { value: 'keyword', label: 'Keyword' },
  { value: 'username', label: 'X Account' },
  { value: 'reddit', label: 'Reddit' },
  { value: 'telegram', label: 'Telegram' },
];

const SOURCE_ASSIGN_TABS = [{ value: 'all', label: 'All' }, ...SOURCE_TYPE_OPTIONS];

function sourceTypeLabel(sourceType) {
  const match = SOURCE_TYPE_OPTIONS.find((option) => option.value === (sourceType || 'rss'));
  return match ? match.label : (sourceType || 'RSS');
}

function formatDate(value) {
  if (!value) return 'Not set';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return parsed.toLocaleDateString();
}

function formatDateTime(value) {
  if (!value) return 'Not yet';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return parsed.toLocaleString();
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
  sources = [],
  users = [],
  onDeleteProject,
}) {
  const navigate = useNavigate();
  const params = useParams();
  const { hasPermission } = useAuth();
  const canEdit = hasPermission('projects.update') || hasPermission('projects.delete');
  const canLinkUsers = hasPermission('projects.link_users');
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [sourcesPage, setSourcesPage] = useState(1);
  const [activeSourceTab, setActiveSourceTab] = useState('all');
  const [articleStats, setArticleStats] = useState(null);
  const [statsLoading, setStatsLoading] = useState(false);
  const [seenProjectId, setSeenProjectId] = useState(null);
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

  // Reset source pagination/tab when navigating to a different project. Adjusting state
  // during render (rather than in an effect) avoids an extra render on every navigation.
  if (project?.id !== seenProjectId) {
    setSeenProjectId(project?.id ?? null);
    setSourcesPage(1);
    setActiveSourceTab('all');
    setIdeaOffset(0);
    setOpeningClusterId(null);
    setClusterOpenErrors({});
  }

  useEffect(() => {
    const controller = new AbortController();
    async function loadArticleStats() {
      if (!project?.id) {
        setArticleStats(null);
        return;
      }
      setStatsLoading(true);
      try {
        const res = await fetch(`/api/articles/stats?project_id=${project.id}`, { signal: controller.signal });
        const data = await res.json().catch(() => null);
        setArticleStats(data && typeof data === 'object' ? data : null);
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
        const params = new URLSearchParams({ limit: '10', offset: String(ideaOffset) });
        const res = await fetch(`/api/projects/${project.id}/idea-clusters?${params.toString()}`, { signal: controller.signal });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data?.detail || data?.error || `Failed to load frequent ideas (${res.status})`);
        setIdeaClusters({
          clusters: Array.isArray(data?.clusters) ? data.clusters : [],
          total: Number(data?.total) || 0,
          limit: Number(data?.limit) || 10,
          offset: Number(data?.offset) || 0,
        });
      } catch (err) {
        if (err?.name !== 'AbortError') {
          setIdeaClusters({ clusters: [], total: 0, limit: 10, offset: 0 });
          setIdeaClustersError(err?.message || 'Failed to load frequent ideas.');
        }
      } finally {
        setIdeaClustersLoading(false);
      }
    }
    loadIdeaClusters();
    return () => controller.abort();
  }, [project?.id, ideaOffset]);

  // A cluster's persisted frequency can span far more articles than fit in
  // this page's list - fetch a large-but-bounded page of its representative
  // articles up front, then hand them to TopicDetailPage via router state so
  // its chart/attribution can be built from real data without a second fetch.
  const openClusterTopic = async (cluster) => {
    setOpeningClusterId(cluster.id);
    setClusterOpenErrors((current) => ({ ...current, [cluster.id]: '' }));
    try {
      const res = await fetch(`/api/projects/${project.id}/idea-clusters/${cluster.id}/articles?limit=200`);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.detail || data?.error || `Failed to load articles (${res.status})`);
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
          sources: clusterSources,
          backTo: '/dashboard',
          backLabel: 'Back to Dashboard',
        },
      });
    } catch (err) {
      setClusterOpenErrors((current) => ({ ...current, [cluster.id]: err?.message || 'Failed to load articles for this idea.' }));
    } finally {
      setOpeningClusterId(null);
    }
  };

  const assignedSources = useMemo(() => {
    if (!project) return [];
    const sourceIds = new Set((project.source_ids || []).map((value) => Number(value)));
    return sources.filter((source) => sourceIds.has(Number(source.id)));
  }, [project, sources]);

  const linkedUsers = useMemo(() => {
    if (!project) return [];
    const userIds = new Set((project.user_ids || []).map((value) => Number(value)));
    return users.filter((user) => userIds.has(Number(user.id)));
  }, [project, users]);

  const sourceTabCounts = useMemo(() => {
    const counts = { all: assignedSources.length };
    SOURCE_TYPE_OPTIONS.forEach((option) => {
      counts[option.value] = assignedSources.filter((source) => (source.source_type || 'rss') === option.value).length;
    });
    return counts;
  }, [assignedSources]);

  const sourcesForActiveTab = useMemo(() => {
    if (activeSourceTab === 'all') return assignedSources;
    return assignedSources.filter((source) => (source.source_type || 'rss') === activeSourceTab);
  }, [assignedSources, activeSourceTab]);

  const totalSourcesPages = Math.max(1, Math.ceil(sourcesForActiveTab.length / SOURCES_PAGE_SIZE));
  const safeSourcesPage = Math.min(sourcesPage, totalSourcesPages);
  const pagedAssignedSources = useMemo(() => {
    const start = (safeSourcesPage - 1) * SOURCES_PAGE_SIZE;
    return sourcesForActiveTab.slice(start, start + SOURCES_PAGE_SIZE);
  }, [sourcesForActiveTab, safeSourcesPage]);

  const hashtagList = normalizeList(project?.hashtags);
  const keywordList = normalizeList(project?.keywords);
  const usernameList = normalizeList(project?.usernames);
  const weekdayList = normalizeList(project?.repeat_weekdays);

  const status = String(project?.status || 'draft').toLowerCase();
  const isActive = status === 'active';
  const isArchived = status === 'archived';
  const statusLabel = status.toUpperCase();

  if (!project) {
    return (
      <div className="admin-page-shell project-detail-page">
        <div className="glass-card" style={{ maxWidth: 960, margin: '0 auto' }}>
          <div className="admin-empty-state" style={{ padding: '34px 20px' }}>
            <div className="admin-empty-state-icon">
              <CalendarDays size={18} />
            </div>
            <strong>Project not found</strong>
            <span>The project may have been removed or the link is outdated.</span>
            <Link to="/projects" className="btn-primary" style={{ marginTop: 8, textDecoration: 'none' }}>
              <ArrowLeft size={16} /> Back to Projects
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
            <CalendarDays size={14} /> Project details
          </div>
          <h1 className="admin-page-title">{project.name}</h1>
          <p className="admin-page-subtitle">
            Review the sources, tags, and discovery details attached to this project. This page is the best place to inspect the working scope before running the pipeline.
          </p>
        </div>

        <div className="admin-page-toolbar">
          <div className="admin-page-toolbar-meta">
            <span>Status</span>
            <strong>{statusLabel}</strong>
          </div>
          <div className="admin-page-toolbar-meta">
            <span>Assigned sources</span>
            <strong>{assignedSources.length.toLocaleString()}</strong>
          </div>
          {canEdit && (
            <>
              <Link to={`/projects/${project.id}/edit`} className="btn-secondary" style={{ textDecoration: 'none' }}>
                <Pencil size={16} /> Edit Project
              </Link>
              <button
                type="button"
                className="btn-secondary"
                onClick={() => setDeleteOpen(true)}
                style={{ color: '#ff4757' }}
              >
                <Trash2 size={16} /> Delete
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
            <strong style={{ fontSize: '1rem' }}>Overview</strong>
            <span className={`panel-chip ${isActive ? 'success' : isArchived ? 'muted' : 'warning'}`}>{statusLabel}</span>
          </div>

          <div className="project-detail-summary-grid">
            <div className="admin-item-card" style={{ margin: 0 }}>
              <div className="admin-item-meta" style={{ marginBottom: 8 }}>
                <span><CalendarDays size={12} /> Start</span>
                <span><CalendarDays size={12} /> End</span>
              </div>
              <strong style={{ fontSize: '0.98rem' }}>{formatDate(project.start_date)}</strong>
              <div style={{ color: 'var(--text-light)', fontSize: '0.84rem', marginTop: 4 }}>{formatDate(project.end_date)}</div>
            </div>

            <div className="admin-item-card" style={{ margin: 0 }}>
              <div className="admin-item-meta" style={{ marginBottom: 8 }}>
                <span><MapPin size={12} /> Location</span>
                <span><Tag size={12} /> Audience</span>
              </div>
              <strong style={{ fontSize: '0.98rem' }}>
                {project.location || 'Not set'}
                {project.location_type ? ` (${prettyLabel(project.location_type)})` : ''}
              </strong>
              <div style={{ color: 'var(--text-light)', fontSize: '0.84rem', marginTop: 4 }}>{project.target_audience || 'No audience specified'}</div>
            </div>
          </div>

          <div className="admin-item-card" style={{ margin: 0 }}>
            <div className="panel-header-tight" style={{ marginBottom: 10 }}>
              <strong style={{ fontSize: '0.94rem' }}><RefreshCw size={14} style={{ verticalAlign: -2 }} /> Automatic Reruns</strong>
              <span className={`panel-chip ${project.repeat_enabled ? 'success' : 'muted'}`}>
                {project.repeat_enabled ? 'Enabled' : 'Disabled'}
              </span>
            </div>
            {project.repeat_enabled ? (
              <div style={{ display: 'grid', gap: 6, color: 'var(--text-light)', fontSize: '0.86rem' }}>
                <div>
                  Runs again every {project.repeat_interval_value} {project.repeat_interval_unit} after completion.
                  {weekdayList.length ? ` Restricted to ${weekdayList.map(prettyLabel).join(', ')}.` : ''}
                </div>
                <div className="admin-item-meta">
                  <span>First run at: {formatDateTime(project.first_run_at)}</span>
                  <span>Next run: {formatDateTime(project.next_run_at)}</span>
                  <span>Last run: {formatDateTime(project.last_run_at)}</span>
                  {project.last_run_status && <span>Last status: {project.last_run_status}</span>}
                </div>
              </div>
            ) : (
              <div style={{ color: 'var(--text-light)', fontSize: '0.86rem' }}>
                This project only runs when triggered manually. Edit the project to enable interval-based reruns.
                {project.last_run_at && ` Last run: ${formatDateTime(project.last_run_at)}.`}
              </div>
            )}
          </div>

          <div className="admin-item-card" style={{ margin: 0 }}>
            <div className="panel-header-tight" style={{ marginBottom: 10 }}>
              <strong style={{ fontSize: '0.94rem' }}>Description</strong>
            </div>
            <div style={{ color: 'var(--text-light)', lineHeight: 1.7, whiteSpace: 'pre-wrap' }}>
              {project.description || 'No description has been added for this project yet.'}
            </div>
          </div>

          <div className="admin-item-card" style={{ margin: 0 }}>
            <div className="panel-header-tight" style={{ marginBottom: 10 }}>
              <strong style={{ fontSize: '0.94rem' }}>Discovery Signals</strong>
            </div>
            <div style={{ display: 'grid', gap: 12 }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, color: 'var(--text-light)', fontSize: '0.8rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  <Hash size={14} /> Hashtags
                </div>
                <div className="admin-item-chips">
                  {hashtagList.length ? hashtagList.map((item) => (
                    <span key={item} className="admin-tag">{item}</span>
                  )) : <span className="admin-tag muted">No hashtags</span>}
                </div>
              </div>

              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, color: 'var(--text-light)', fontSize: '0.8rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  <AtSign size={14} /> X Accounts
                </div>
                <div className="admin-item-chips">
                  {usernameList.length ? usernameList.map((item) => (
                    <span key={item} className="admin-tag muted">{item}</span>
                  )) : <span className="admin-tag muted">No X accounts</span>}
                </div>
              </div>

              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, color: 'var(--text-light)', fontSize: '0.8rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  <Link2 size={14} /> Keywords
                </div>
                <div className="admin-item-chips">
                  {keywordList.length ? keywordList.map((item) => (
                    <span key={item} className="admin-tag muted">{item}</span>
                  )) : <span className="admin-tag muted">No keywords</span>}
                </div>
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
            <strong style={{ fontSize: '1rem' }}>Assigned Sources</strong>
            <span className="panel-chip">{assignedSources.length} linked</span>
          </div>

          {assignedSources.length === 0 ? (
            <div className="admin-empty-state" style={{ padding: '20px 12px' }}>
              <div className="admin-empty-state-icon">
                <Link2 size={18} />
              </div>
              <strong>No sources assigned</strong>
              <span>Use Edit Project to attach sources to this project.</span>
            </div>
          ) : (
            <>
              <div className="source-type-tabs" role="tablist" aria-label="Filter assigned sources by type">
                {SOURCE_ASSIGN_TABS.map((tab) => {
                  const isActive = activeSourceTab === tab.value;
                  return (
                    <button
                      key={tab.value}
                      type="button"
                      role="tab"
                      aria-selected={isActive}
                      className={`source-type-tab ${isActive ? 'active' : ''}`}
                      onClick={() => {
                        setActiveSourceTab(tab.value);
                        setSourcesPage(1);
                      }}
                    >
                      {tab.label}
                      <span className="source-type-tab-count">{sourceTabCounts[tab.value] || 0}</span>
                    </button>
                  );
                })}
              </div>

              {sourcesForActiveTab.length === 0 ? (
                <div className="admin-empty-state" style={{ padding: '20px 12px' }}>
                  <div className="admin-empty-state-icon">
                    <Link2 size={18} />
                  </div>
                  <strong>No matching sources</strong>
                  <span>No {sourceTypeLabel(activeSourceTab)} sources are assigned to this project.</span>
                </div>
              ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {pagedAssignedSources.map((source) => (
                <div key={source.id} className="admin-item-card" style={{ margin: 0 }}>
                  <div className="admin-item-top">
                    <div style={{ minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 6 }}>
                        <strong className="admin-item-title project-detail-break-text">{source.name || source.url}</strong>
                        <span className={`panel-chip ${source.enabled ? 'success' : 'muted'}`}>
                          {source.enabled ? 'Enabled' : 'Disabled'}
                        </span>
                      </div>
                      <div className="admin-item-url">{source.url}</div>
                      <div className="admin-item-meta">
                        <span>{sourceTypeLabel(source.source_type)}</span>
                      </div>
                    </div>
                  </div>
                </div>
                ))}
              </div>
              )}

              {sourcesForActiveTab.length > SOURCES_PAGE_SIZE && (
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
                    Showing {(safeSourcesPage - 1) * SOURCES_PAGE_SIZE + 1}-{Math.min(safeSourcesPage * SOURCES_PAGE_SIZE, sourcesForActiveTab.length)} of {sourcesForActiveTab.length}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={() => setSourcesPage((value) => Math.max(1, value - 1))}
                      disabled={safeSourcesPage <= 1}
                      style={{ padding: '8px 10px', fontSize: '0.8rem' }}
                    >
                      <ChevronLeft size={14} /> Previous
                    </button>
                    <span className="panel-chip">
                      Page {safeSourcesPage} of {totalSourcesPages}
                    </span>
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={() => setSourcesPage((value) => Math.min(totalSourcesPages, value + 1))}
                      disabled={safeSourcesPage >= totalSourcesPages}
                      style={{ padding: '8px 10px', fontSize: '0.8rem' }}
                    >
                      Next <ChevronRight size={14} />
                    </button>
                  </div>
                </div>
              )}
            </>
          )}

          <div className="admin-item-card" style={{ margin: 0 }}>
            <div className="panel-header-tight" style={{ marginBottom: 10 }}>
              <strong style={{ fontSize: '0.94rem' }}>Quick Facts</strong>
            </div>
            <div style={{ display: 'grid', gap: 10 }}>
              <div className="admin-item-meta">
                <span>Created {formatDate(project.created_at)}</span>
                <span>Updated {formatDate(project.updated_at)}</span>
              </div>
              <div className="admin-item-meta">
                <span>{assignedSources.length} linked source{assignedSources.length === 1 ? '' : 's'}</span>
                <span>{hashtagList.length} hashtag{hashtagList.length === 1 ? '' : 's'}</span>
              </div>
              {canLinkUsers && (
                <div className="admin-item-meta">
                  <span>{linkedUsers.length} linked user{linkedUsers.length === 1 ? '' : 's'}</span>
                </div>
              )}
              {canLinkUsers && linkedUsers.length > 0 && (
                <div className="admin-item-chips">
                  {linkedUsers.map((user) => (
                    <span key={user.id} className="admin-tag muted">{user.username}</span>
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
          <strong style={{ fontSize: '1rem' }}>Article Insights</strong>
          <span className="panel-chip">{(articleStats?.total || 0).toLocaleString()} analyzed articles</span>
        </div>

        {statsLoading ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-light)', fontSize: '0.86rem', padding: '12px 0' }}>
            <Loader2 size={16} className="spin" /> Loading article insights...
          </div>
        ) : !articleStats?.total ? (
          <div className="admin-empty-state" style={{ padding: '20px 12px' }}>
            <div className="admin-empty-state-icon">
              <BarChart3 size={18} />
            </div>
            <strong>No analyzed articles yet</strong>
            <span>Run the pipeline for this project to see tone and sentiment insights here.</span>
          </div>
        ) : (
          <>
            <div className="project-detail-summary-grid">
              <div className="admin-item-card" style={{ margin: 0 }}>
                <div className="admin-item-meta" style={{ marginBottom: 8 }}>
                  <span>Overall Mood</span>
                </div>
                <strong style={{ fontSize: '0.98rem' }}>{prettyLabel(articleStats?.insights?.overall_mood || 'neutral')}</strong>
              </div>

              <div className="admin-item-card" style={{ margin: 0 }}>
                <div className="admin-item-meta" style={{ marginBottom: 8 }}>
                  <span>Overall Tone</span>
                </div>
                <strong style={{ fontSize: '0.98rem' }}>{prettyLabel(articleStats?.insights?.overall_tone || 'neutral')}</strong>
              </div>
            </div>

            <div className="admin-item-card" style={{ margin: 0 }}>
              <div className="panel-header-tight" style={{ marginBottom: 10 }}>
                <strong style={{ fontSize: '0.94rem' }}>Writer Tone Breakdown</strong>
              </div>
              <div className="admin-item-chips">
                {(articleStats?.insights?.writer_tone_breakdown || []).length ? (
                  articleStats.insights.writer_tone_breakdown.map((item) => (
                    <span key={item.tone} className="admin-tag muted">{prettyLabel(item.tone)} ({item.count})</span>
                  ))
                ) : (
                  <span className="admin-tag muted">No data yet</span>
                )}
              </div>
            </div>

            <div className="admin-item-card" style={{ margin: 0 }}>
              <div className="panel-header-tight" style={{ marginBottom: 10 }}>
                <strong style={{ fontSize: '0.94rem' }}>Article Tone Breakdown</strong>
              </div>
              <div className="admin-item-chips">
                {(articleStats?.insights?.article_tone_breakdown || []).length ? (
                  articleStats.insights.article_tone_breakdown.map((item) => (
                    <span key={item.tone} className="admin-tag muted">{prettyLabel(item.tone)} ({item.count})</span>
                  ))
                ) : (
                  <span className="admin-tag muted">No data yet</span>
                )}
              </div>
            </div>

            <div className="admin-item-card" style={{ margin: 0 }}>
              <div className="panel-header-tight" style={{ marginBottom: 10 }}>
                <strong style={{ fontSize: '0.94rem' }}>Sentiment by Region</strong>
              </div>
              <DemographicSentimentChart title="Sentiment by region" data={articleStats?.insights?.region_breakdown} />
            </div>

            <div className="admin-item-card" style={{ margin: 0 }}>
              <div className="panel-header-tight" style={{ marginBottom: 10 }}>
                <strong style={{ fontSize: '0.94rem' }}>Sentiment by Gender</strong>
              </div>
              <DemographicSentimentChart title="Sentiment by gender" data={articleStats?.insights?.gender_breakdown} />
            </div>

            <div className="admin-item-card" style={{ margin: 0 }}>
              <div className="panel-header-tight" style={{ marginBottom: 10 }}>
                <strong style={{ fontSize: '0.94rem' }}>Sentiment by Age Range</strong>
              </div>
              <DemographicSentimentChart title="Sentiment by age range" data={articleStats?.insights?.age_range_breakdown} />
            </div>

            <div className="admin-item-card" style={{ margin: 0 }}>
              <div className="panel-header-tight" style={{ marginBottom: 10 }}>
                <strong style={{ fontSize: '0.94rem' }}>Sentiment by Segment</strong>
              </div>
              <DemographicSentimentChart title="Sentiment by segment" data={articleStats?.insights?.segment_breakdown} />
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
          <strong style={{ fontSize: '1rem' }}>Frequent Ideas</strong>
          <span className="panel-chip">{ideaClusters.total.toLocaleString()} clusters</span>
        </div>
        <p className="subtitle" style={{ margin: 0 }}>
          Ideas repeated across analyzed articles for this project, accumulated across every pipeline run.
        </p>

        {ideaClustersError ? (
          <div className="admin-empty-state" style={{ padding: '20px 12px' }}>
            <div className="admin-empty-state-icon">
              <Lightbulb size={18} />
            </div>
            <strong>Couldn't load frequent ideas</strong>
            <span>{ideaClustersError}</span>
          </div>
        ) : ideaClustersLoading ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-light)', fontSize: '0.86rem', padding: '12px 0' }}>
            <Loader2 size={16} className="spin" /> Loading frequent ideas...
          </div>
        ) : ideaClusters.clusters.length === 0 ? (
          <div className="admin-empty-state" style={{ padding: '20px 12px' }}>
            <div className="admin-empty-state-icon">
              <Lightbulb size={18} />
            </div>
            <strong>No repeated ideas yet</strong>
            <span>Run the pipeline to build up cross-article idea clusters for this project.</span>
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
                      <strong style={{ fontSize: '0.92rem' }}>{cluster.idea}</strong>
                      <span className="admin-tag muted">{cluster.type || 'issue'}</span>
                    </span>
                    <span className="panel-chip" style={{ flexShrink: 0 }}>
                      {Number(cluster.frequency_estimate || 0).toLocaleString()} articles
                    </span>
                  </button>
                  {openError ? (
                    <span style={{ display: 'block', marginTop: 8, color: '#b42318', fontSize: '0.82rem' }}>{openError}</span>
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
              <ChevronLeft size={14} /> Previous
            </button>
            <button
              className="btn-secondary"
              onClick={() => setIdeaOffset((prev) => prev + ideaClusters.limit)}
              disabled={ideaOffset + ideaClusters.limit >= ideaClusters.total || ideaClustersLoading}
              style={{ padding: '6px 10px', fontSize: '0.78rem' }}
            >
              Next <ChevronRight size={14} />
            </button>
          </div>
        ) : null}
      </motion.div>

      <ConfirmModal
        open={deleteOpen}
        title={`Delete project "${project.name}"?`}
        message="This will permanently remove the project and detach it from any linked sources."
        confirmLabel="Delete project"
        cancelLabel="Keep project"
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
