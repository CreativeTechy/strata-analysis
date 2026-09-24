import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Eye, Layers3, Link2, Pencil, Search, Users } from 'lucide-react';
import { formatNumber } from '../lib/i18nFormat.js';
import '../styles/ProjectLinkage.css';

// Status codes are literal, backend-checked values (mirrored in filter
// comparisons below) - never translated, same as a permission key or a
// user's active/disabled status.
const STATUS_OPTIONS = ['draft', 'active', 'archived'];
const PAGE_SIZE = 10;

// List-only entry point for project<->user linkage management. Viewing and
// editing a single project's linkage live on their own routed pages
// (ProjectLinkageDetailPage / ProjectLinkageEditPage); this page never
// renders the assignment UI itself.
export default function ProjectLinkageListPage({ projects = [], users = [], isLoadingProjects, isLoadingUsers }) {
  const { t, i18n } = useTranslation(['admin', 'common']);
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [userFilter, setUserFilter] = useState('all');
  const [currentPage, setCurrentPage] = useState(1);

  const sortedUsers = useMemo(
    () => [...users].sort((a, b) => String(a.username || '').localeCompare(String(b.username || ''))),
    [users]
  );

  const visibleProjects = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return projects.filter((project) => {
      const matchesQuery = !needle || String(project.name || '').toLowerCase().includes(needle);
      const matchesStatus = statusFilter === 'all' || (project.status || 'draft').toLowerCase() === statusFilter;
      const matchesUser =
        userFilter === 'all' || (project.user_ids || []).map(Number).includes(Number(userFilter));
      return matchesQuery && matchesStatus && matchesUser;
    });
  }, [projects, query, statusFilter, userFilter]);

  const totalPages = Math.max(1, Math.ceil(visibleProjects.length / PAGE_SIZE));
  const safePage = Math.min(currentPage, totalPages);
  const pagedProjects = useMemo(() => {
    const start = (safePage - 1) * PAGE_SIZE;
    return visibleProjects.slice(start, start + PAGE_SIZE);
  }, [visibleProjects, safePage]);

  useEffect(() => {
    setCurrentPage(1);
  }, [query, statusFilter, userFilter]);

  useEffect(() => {
    if (currentPage > totalPages) setCurrentPage(totalPages);
  }, [currentPage, totalPages]);

  return (
    <div className="admin-page-shell project-linkage-page">
      <div className="admin-page-header">
        <div>
          <div className="admin-page-kicker">
            <Link2 size={14} /> {t('kickers.accessControl')}
          </div>
          <h1 className="admin-page-title">{t('projectLinkage.list.title')}</h1>
          <p className="admin-page-subtitle">
            {t('projectLinkage.list.subtitle')}
          </p>
        </div>
        <div className="admin-page-toolbar">
          <div className="admin-page-toolbar-meta">
            <span>{t('projectLinkage.list.projectsMeta')}</span>
            <strong>{formatNumber(projects.length, i18n.language)}</strong>
          </div>
          <div className="admin-page-toolbar-meta">
            <span>{t('projectLinkage.list.matchesMeta')}</span>
            <strong>{formatNumber(visibleProjects.length, i18n.language)}</strong>
          </div>
        </div>
      </div>

      <div className="admin-stats-grid">
        <div className="admin-stat-card">
          <div className="admin-stat-icon">
            <Layers3 size={18} />
          </div>
          <div>
            <span>{t('projectLinkage.list.totalProjects')}</span>
            <strong>{formatNumber(projects.length, i18n.language)}</strong>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon" style={{ background: 'rgba(46, 134, 222, 0.12)', color: '#2e86de' }}>
            <Users size={18} />
          </div>
          <div>
            <span>{t('projectLinkage.list.dashboardUsers')}</span>
            <strong>{formatNumber(users.length, i18n.language)}</strong>
          </div>
        </div>
      </div>

      <div className="admin-toolbar-row">
        <label className="admin-search">
          <Search size={16} />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t('projectLinkage.list.searchPlaceholder')}
          />
        </label>

        <select className="filter-select" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="all">{t('projectLinkage.list.allStatuses')}</option>
          {STATUS_OPTIONS.map((status) => (
            <option key={status} value={status}>
              {status[0].toUpperCase() + status.slice(1)}
            </option>
          ))}
        </select>

        <select
          className="filter-select"
          value={userFilter}
          onChange={(e) => setUserFilter(e.target.value)}
          disabled={isLoadingUsers}
        >
          <option value="all">{isLoadingUsers ? t('projectLinkage.list.loadingUsers') : t('projectLinkage.list.allLinkedUsers')}</option>
          {sortedUsers.map((user) => (
            <option key={user.id} value={user.id}>
              {user.username}
            </option>
          ))}
        </select>
      </div>

      <div className="glass-card admin-list-panel">
        <div className="panel-header-tight">
          <strong style={{ fontSize: '1rem' }}>{t('projectLinkage.list.panelTitle')}</strong>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            {isLoadingProjects && <span style={{ fontSize: '0.72rem', color: 'var(--text-light)' }}>{t('projectLinkage.list.loading')}</span>}
            <span className="panel-chip">{t('projectLinkage.list.visibleCount', { count: visibleProjects.length })}</span>
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {projects.length === 0 && !isLoadingProjects && (
            <div className="admin-empty-state">
              <div className="admin-empty-state-icon">
                <Link2 size={18} />
              </div>
              <strong>{t('projectLinkage.list.emptyTitle')}</strong>
              <span>{t('projectLinkage.list.emptyBody')}</span>
            </div>
          )}

          {pagedProjects.map((project) => {
            const linkedCount = (project.user_ids || []).length;
            const status = (project.status || 'draft').toLowerCase();
            const isActive = status === 'active';
            return (
              <div key={project.id} className="admin-item-card">
                <div className="admin-item-top">
                  <div style={{ minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8, flexWrap: 'wrap' }}>
                      <strong className="admin-item-title" dir="auto">{project.name}</strong>
                      <span className={`panel-chip ${isActive ? 'success' : status === 'archived' ? 'muted' : 'warning'}`}>
                        {status.toUpperCase()}
                      </span>
                    </div>
                    <div className="admin-item-meta">
                      <span>
                        {t('projectLinkage.list.linkedUserCount', { count: linkedCount })}
                      </span>
                    </div>
                  </div>

                  <div className="admin-item-actions">
                    <Link
                      className="btn-secondary project-linkage-compact-btn"
                      to={`/admin/project-linkage/${project.id}`}
                    >
                      <Eye size={14} /> {t('common:actions.view')}
                    </Link>
                    <Link
                      className="btn-secondary project-linkage-compact-btn"
                      to={`/admin/project-linkage/${project.id}/edit`}
                    >
                      <Pencil size={14} /> {t('common:actions.edit')}
                    </Link>
                  </div>
                </div>
              </div>
            );
          })}

          {!isLoadingProjects && visibleProjects.length === 0 && projects.length > 0 && (
            <div className="admin-empty-state">
              <div className="admin-empty-state-icon">
                <Search size={18} />
              </div>
              <strong>{t('projectLinkage.list.noMatchTitle')}</strong>
              <span>{t('projectLinkage.list.noMatchBody')}</span>
            </div>
          )}
        </div>

        {visibleProjects.length > 0 && (
          <div
            style={{
              marginTop: 14,
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              gap: 12,
              flexWrap: 'wrap',
              paddingTop: 12,
              borderTop: '1px solid rgba(15, 23, 42, 0.08)',
            }}
          >
            <div style={{ fontSize: '0.84rem', color: 'var(--text-light)' }}>
              {t('projectLinkage.list.showingRange', {
                start: (safePage - 1) * PAGE_SIZE + 1,
                end: Math.min(safePage * PAGE_SIZE, visibleProjects.length),
                total: visibleProjects.length,
              })}
            </div>
            <div className="project-linkage-pagination-controls">
              <button
                className="btn-secondary project-linkage-compact-btn"
                onClick={() => setCurrentPage((value) => Math.max(1, value - 1))}
                disabled={safePage <= 1}
              >
                {t('common:actions.previous')}
              </button>
              <span className="panel-chip">
                {t('common:pagination.pageOfTotal', { page: safePage, totalPages })}
              </span>
              <button
                className="btn-secondary project-linkage-compact-btn"
                onClick={() => setCurrentPage((value) => Math.min(totalPages, value + 1))}
                disabled={safePage >= totalPages}
              >
                {t('common:actions.next')}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
