import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, CalendarDays, Link2, Pencil } from 'lucide-react';
import { formatDate as formatDateLocale, formatNumber } from '../lib/i18nFormat.js';
import '../styles/ProjectLinkage.css';

// View-only: shows a single project's metadata and its linked users.
// Changing the linkage happens on ProjectLinkageEditPage.
export default function ProjectLinkageDetailPage({ projects = [], users = [] }) {
  const { t, i18n } = useTranslation(['admin', 'common']);
  const params = useParams();

  const formatDate = (value) => (value ? formatDateLocale(value, i18n.language) || String(value) : t('projectLinkage.detail.notSet'));

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
            <strong>{t('notFound.projectTitle')}</strong>
            <span>{t('notFound.hint')}</span>
            <Link to="/admin/project-linkage" className="btn-primary" style={{ marginTop: 8, textDecoration: 'none' }}>
              <ArrowLeft size={16} className="rtl-mirror" /> {t('notFound.backToProjectLinkage')}
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
            <Link2 size={14} /> {t('kickers.projectLinkage')}
          </div>
          <h1 className="admin-page-title" dir="auto">{project.name}</h1>
          <p className="admin-page-subtitle">{t('projectLinkage.detail.subtitle')}</p>
        </div>
        <div className="admin-page-toolbar">
          <div className="admin-page-toolbar-meta">
            <span>{t('projectLinkage.detail.statusLabel')}</span>
            <strong>{status.toUpperCase()}</strong>
          </div>
          <div className="admin-page-toolbar-meta">
            <span>{t('projectLinkage.linkedUsers')}</span>
            <strong>{formatNumber(linkedUsers.length, i18n.language)}</strong>
          </div>
          <Link
            to={`/admin/project-linkage/${project.id}/edit`}
            className="btn-secondary"
            style={{ textDecoration: 'none' }}
          >
            <Pencil size={16} /> {t('projectLinkage.detail.editLinkage')}
          </Link>
        </div>
      </div>

      <div className="project-detail-layout">
        <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div className="panel-header-tight">
            <strong style={{ fontSize: '1rem' }}>{t('projectLinkage.detail.detailsTitle')}</strong>
            <span className={`panel-chip ${isActive ? 'success' : isArchived ? 'muted' : 'warning'}`}>
              {status.toUpperCase()}
            </span>
          </div>

          <div className="project-detail-summary-grid">
            <div className="admin-item-card" style={{ margin: 0 }}>
              <div className="admin-item-meta" style={{ marginBottom: 8 }}>
                <span>
                  <CalendarDays size={12} /> {t('projectLinkage.detail.start')}
                </span>
                <span>
                  <CalendarDays size={12} /> {t('projectLinkage.detail.end')}
                </span>
              </div>
              <strong style={{ fontSize: '0.98rem' }}>{formatDate(project.start_date)}</strong>
              <div style={{ color: 'var(--text-light)', fontSize: '0.84rem', marginTop: 4 }}>
                {formatDate(project.end_date)}
              </div>
            </div>

            <div className="admin-item-card" style={{ margin: 0 }}>
              <div className="admin-item-meta" style={{ marginBottom: 8 }}>
                <span>{t('projectLinkage.detail.location')}</span>
                <span>{t('projectLinkage.detail.audience')}</span>
              </div>
              <strong style={{ fontSize: '0.98rem', overflowWrap: 'anywhere' }} dir="auto">
                {project.location || t('projectLinkage.detail.notSet')}
              </strong>
              <div style={{ color: 'var(--text-light)', fontSize: '0.84rem', marginTop: 4, overflowWrap: 'anywhere' }} dir="auto">
                {project.target_audience || t('projectLinkage.detail.noAudience')}
              </div>
            </div>
          </div>

          <div className="admin-item-card" style={{ margin: 0 }}>
            <div className="panel-header-tight" style={{ marginBottom: 10 }}>
              <strong style={{ fontSize: '0.94rem' }}>{t('projectLinkage.detail.descriptionTitle')}</strong>
            </div>
            <div style={{ color: 'var(--text-light)', lineHeight: 1.7, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }} dir="auto">
              {project.description || t('projectLinkage.detail.noDescription')}
            </div>
          </div>
        </div>

        <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div className="panel-header-tight">
            <strong style={{ fontSize: '1rem' }}>{t('projectLinkage.linkedUsers')}</strong>
            <span className="panel-chip">{t('projectLinkage.detail.linkedBadge', { count: linkedUsers.length })}</span>
          </div>

          {linkedUsers.length === 0 ? (
            <div className="admin-empty-state" style={{ padding: '20px 12px' }}>
              <div className="admin-empty-state-icon">
                <Link2 size={18} />
              </div>
              <strong>{t('projectLinkage.detail.noUsersTitle')}</strong>
              <span>{t('projectLinkage.detail.noUsersBody')}</span>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {linkedUsers.map((user) => (
                <div key={user.id} className="admin-item-card" style={{ margin: 0 }}>
                  <div className="admin-item-top">
                    <div style={{ minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 6 }}>
                        <strong className="admin-item-title" dir="auto">{user.username}</strong>
                        <span className={`panel-chip role-${user.role}`} dir="auto">{user.role}</span>
                      </div>
                      <div className="admin-item-meta">
                        <span dir="ltr">{user.email || t('projectLinkage.noEmailOnFile')}</span>
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
