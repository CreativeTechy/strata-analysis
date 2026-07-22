import { useMemo } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, CalendarDays, Link2, Pencil } from 'lucide-react';
import '../styles/ProjectLinkage.css';

function formatDate(value) {
  if (!value) return 'Not set';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return parsed.toLocaleDateString();
}

// View-only: shows a single project's metadata and its linked users.
// Changing the linkage happens on ProjectLinkageEditPage.
export default function ProjectLinkageDetailPage({ projects = [], users = [] }) {
  const params = useParams();

  const project = useMemo(
    () => projects.find((item) => Number(item.id) === Number(params.projectId)) || null,
    [projects, params.projectId]
  );

  const linkedUsers = useMemo(() => {
    if (!project) return [];
    const ids = new Set((project.user_ids || []).map((value) => Number(value)));
    return users.filter((user) => ids.has(Number(user.id)));
  }, [project, users]);

  if (!project) {
    return (
      <div className="admin-page-shell project-linkage-page">
        <div className="glass-card" style={{ maxWidth: 960, margin: '0 auto' }}>
          <div className="admin-empty-state" style={{ padding: '34px 20px' }}>
            <div className="admin-empty-state-icon">
              <Link2 size={18} />
            </div>
            <strong>Project not found</strong>
            <span>It may have been removed, or you may not have access to it.</span>
            <Link to="/admin/project-linkage" className="btn-primary" style={{ marginTop: 8, textDecoration: 'none' }}>
              <ArrowLeft size={16} /> Back to Project Linkage
            </Link>
          </div>
        </div>
      </div>
    );
  }

  const status = String(project.status || 'draft').toLowerCase();
  const isActive = status === 'active';
  const isArchived = status === 'archived';

  return (
    <div className="admin-page-shell project-linkage-page">
      <div className="admin-page-header">
        <div>
          <div className="admin-page-kicker">
            <Link2 size={14} /> Project linkage
          </div>
          <h1 className="admin-page-title">{project.name}</h1>
          <p className="admin-page-subtitle">Review the dashboard users linked to this project.</p>
        </div>
        <div className="admin-page-toolbar">
          <div className="admin-page-toolbar-meta">
            <span>Status</span>
            <strong>{status.toUpperCase()}</strong>
          </div>
          <div className="admin-page-toolbar-meta">
            <span>Linked users</span>
            <strong>{linkedUsers.length}</strong>
          </div>
          <Link
            to={`/admin/project-linkage/${project.id}/edit`}
            className="btn-secondary"
            style={{ textDecoration: 'none' }}
          >
            <Pencil size={16} /> Edit linkage
          </Link>
        </div>
      </div>

      <div className="project-detail-layout">
        <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div className="panel-header-tight">
            <strong style={{ fontSize: '1rem' }}>Project details</strong>
            <span className={`panel-chip ${isActive ? 'success' : isArchived ? 'muted' : 'warning'}`}>
              {status.toUpperCase()}
            </span>
          </div>

          <div className="project-detail-summary-grid">
            <div className="admin-item-card" style={{ margin: 0 }}>
              <div className="admin-item-meta" style={{ marginBottom: 8 }}>
                <span>
                  <CalendarDays size={12} /> Start
                </span>
                <span>
                  <CalendarDays size={12} /> End
                </span>
              </div>
              <strong style={{ fontSize: '0.98rem' }}>{formatDate(project.start_date)}</strong>
              <div style={{ color: 'var(--text-light)', fontSize: '0.84rem', marginTop: 4 }}>
                {formatDate(project.end_date)}
              </div>
            </div>

            <div className="admin-item-card" style={{ margin: 0 }}>
              <div className="admin-item-meta" style={{ marginBottom: 8 }}>
                <span>Location</span>
                <span>Audience</span>
              </div>
              <strong style={{ fontSize: '0.98rem', overflowWrap: 'anywhere' }}>{project.location || 'Not set'}</strong>
              <div style={{ color: 'var(--text-light)', fontSize: '0.84rem', marginTop: 4, overflowWrap: 'anywhere' }}>
                {project.target_audience || 'No audience specified'}
              </div>
            </div>
          </div>

          <div className="admin-item-card" style={{ margin: 0 }}>
            <div className="panel-header-tight" style={{ marginBottom: 10 }}>
              <strong style={{ fontSize: '0.94rem' }}>Description</strong>
            </div>
            <div style={{ color: 'var(--text-light)', lineHeight: 1.7, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
              {project.description || 'No description has been added for this project yet.'}
            </div>
          </div>
        </div>

        <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div className="panel-header-tight">
            <strong style={{ fontSize: '1rem' }}>Linked users</strong>
            <span className="panel-chip">{linkedUsers.length} linked</span>
          </div>

          {linkedUsers.length === 0 ? (
            <div className="admin-empty-state" style={{ padding: '20px 12px' }}>
              <div className="admin-empty-state-icon">
                <Link2 size={18} />
              </div>
              <strong>No users linked</strong>
              <span>Use Edit linkage to add dashboard users to this project.</span>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {linkedUsers.map((user) => (
                <div key={user.id} className="admin-item-card" style={{ margin: 0 }}>
                  <div className="admin-item-top">
                    <div style={{ minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 6 }}>
                        <strong className="admin-item-title">{user.username}</strong>
                        <span className={`panel-chip role-${user.role}`}>{user.role}</span>
                      </div>
                      <div className="admin-item-meta">
                        <span>{user.email || 'No email on file'}</span>
                        <span>{user.status}</span>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
