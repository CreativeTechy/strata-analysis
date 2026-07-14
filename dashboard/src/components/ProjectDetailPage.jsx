import { useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { motion } from 'framer-motion';
import ConfirmModal from './ConfirmModal';
import { useAuth } from '../auth/useAuth.js';
import {
  ArrowLeft,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  Hash,
  Link2,
  MapPin,
  AtSign,
  Tag,
  Pencil,
  RefreshCw,
  Trash2,
} from 'lucide-react';

const SOURCES_PAGE_SIZE = 3;

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

export default function ProjectDetailPage({
  projects = [],
  sources = [],
  onDeleteProject,
}) {
  const navigate = useNavigate();
  const params = useParams();
  const { hasRole } = useAuth();
  const canEdit = hasRole('editor');
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [sourcesPage, setSourcesPage] = useState(1);

  const project = useMemo(
    () => projects.find((item) => Number(item.id) === Number(params.projectId)) || null,
    [projects, params.projectId]
  );

  const assignedSources = useMemo(() => {
    if (!project) return [];
    const sourceIds = new Set((project.source_ids || []).map((value) => Number(value)));
    return sources.filter((source) => sourceIds.has(Number(source.id)));
  }, [project, sources]);

  const totalSourcesPages = Math.max(1, Math.ceil(assignedSources.length / SOURCES_PAGE_SIZE));
  const safeSourcesPage = Math.min(sourcesPage, totalSourcesPages);
  const pagedAssignedSources = useMemo(() => {
    const start = (safeSourcesPage - 1) * SOURCES_PAGE_SIZE;
    return assignedSources.slice(start, start + SOURCES_PAGE_SIZE);
  }, [assignedSources, safeSourcesPage]);

  const hashtagList = normalizeList(project?.hashtags);
  const keywordList = normalizeList(project?.keywords);
  const usernameList = normalizeList(project?.usernames);

  const status = String(project?.status || 'draft').toLowerCase();
  const isActive = status === 'active';
  const isArchived = status === 'archived';
  const statusLabel = status.toUpperCase();

  if (!project) {
    return (
      <div className="admin-page-shell">
        <div className="glass-card" style={{ maxWidth: 760, margin: '0 auto' }}>
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
    <div className="admin-page-shell">
      <div className="admin-page-header">
        <div>
          <div className="admin-page-kicker">
            <CalendarDays size={14} /> Project details
          </div>
          <h1 className="admin-page-title">{project.name}</h1>
          <p className="admin-page-subtitle">
            Review the sources, tags, and metadata attached to this project. This page is the best place to inspect the working scope before running the pipeline.
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
              <strong style={{ fontSize: '0.98rem' }}>{project.location || 'Not set'}</strong>
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
                </div>
                <div className="admin-item-meta">
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
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {pagedAssignedSources.map((source) => (
                <div key={source.id} className="admin-item-card" style={{ margin: 0 }}>
                  <div className="admin-item-top">
                    <div style={{ minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 6 }}>
                        <strong className="admin-item-title">{source.name || source.url}</strong>
                        <span className={`panel-chip ${source.enabled ? 'success' : 'muted'}`}>
                          {source.enabled ? 'Enabled' : 'Disabled'}
                        </span>
                      </div>
                      <div className="admin-item-url">{source.url}</div>
                      <div className="admin-item-meta">
                        <span>{source.source_type || 'rss'}</span>
                        {source.category ? <span>{source.category}</span> : null}
                      </div>
                    </div>
                  </div>
                </div>
                ))}
              </div>

              {assignedSources.length > SOURCES_PAGE_SIZE && (
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
                    Showing {(safeSourcesPage - 1) * SOURCES_PAGE_SIZE + 1}-{Math.min(safeSourcesPage * SOURCES_PAGE_SIZE, assignedSources.length)} of {assignedSources.length}
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
            </div>
          </div>
        </motion.div>
      </div>

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
