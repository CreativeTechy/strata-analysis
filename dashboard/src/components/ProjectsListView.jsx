import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../auth/useAuth.js';
import { PAGE_SIZE, STATUS_OPTIONS } from '../lib/projectHelpers.js';
import { formatDateTime, formatNumber } from '../lib/i18nFormat.js';
import '../styles/Projects.css';
import { CalendarDays, Eye, Plus, Search, Flag, Layers3, RefreshCw, FileText } from 'lucide-react';

// The Opinion Monitor project browser, extracted out of ProjectsPage.jsx:
// search/filter/paginate the project list. Mounted only on /projects, so
// (unlike when this lived inside ProjectsPage) it owns nothing wizard-related
// - no draft, no document pipeline state.
export default function ProjectsListView({ projects = [], isLoadingProjects }) {
  const { t, i18n } = useTranslation('projects');
  const { hasPermission } = useAuth();
  const canEdit = hasPermission('projects.create') || hasPermission('projects.update') || hasPermission('projects.delete');
  const locale = i18n.language;
  const statusLabels = {
    draft: t('shared.statusLabels.draft'),
    active: t('shared.statusLabels.active'),
    archived: t('shared.statusLabels.archived'),
  };

  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [currentPage, setCurrentPage] = useState(1);

  const stats = useMemo(() => {
    const total = projects.length;
    const active = projects.filter((project) => (project.status || '').toLowerCase() === 'active').length;
    const draftCount = projects.filter((project) => (project.status || '').toLowerCase() === 'draft').length;
    const archived = projects.filter((project) => (project.status || '').toLowerCase() === 'archived').length;
    return { total, active, draftCount, archived };
  }, [projects]);

  const visibleProjects = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return projects.filter((project) => {
      const keywordNames = (project.keywords || []).map((value) => String(value).trim()).filter(Boolean);
      const matchesQuery =
        !needle ||
        [
          project.name,
          project.status,
          project.description,
          project.location,
          project.target_audience,
          project.start_date,
          project.end_date,
          ...keywordNames,
        ]
          .filter(Boolean)
          .some((value) => String(value).toLowerCase().includes(needle));
      const matchesStatus = statusFilter === 'all' || (project.status || 'draft').toLowerCase() === statusFilter;
      return matchesQuery && matchesStatus;
    });
  }, [projects, query, statusFilter]);

  const totalPages = Math.max(1, Math.ceil(visibleProjects.length / PAGE_SIZE));
  const safePage = Math.min(currentPage, totalPages);
  const pagedProjects = useMemo(() => {
    const start = (safePage - 1) * PAGE_SIZE;
    return visibleProjects.slice(start, start + PAGE_SIZE);
  }, [visibleProjects, safePage]);

  useEffect(() => {
    setCurrentPage(1);
  }, [query, statusFilter]);

  useEffect(() => {
    if (currentPage > totalPages) {
      setCurrentPage(totalPages);
    }
  }, [currentPage, totalPages]);

  return (
    <div className="admin-page-shell">
      <div className="admin-page-header">
        <div>
          <div className="admin-page-kicker">
            <CalendarDays size={14} /> {t('shared.opinionMonitoringKicker')}
          </div>
          <h1 className="admin-page-title">{t('list.title')}</h1>
          <p className="admin-page-subtitle">
            {t('list.subtitle')}
          </p>
        </div>
        <div className="admin-page-toolbar">
          <div className="admin-page-toolbar-meta">
            <span>{t('list.toolbar.statusLabel')}</span>
            <strong>{projects.length ? t('list.toolbar.statusConfigured') : t('list.toolbar.statusEmpty')}</strong>
          </div>
          <div className="admin-page-toolbar-meta">
            <span>{t('list.toolbar.searchLabel')}</span>
            <strong>{t('list.toolbar.matchesCount', { count: visibleProjects.length, formattedCount: formatNumber(visibleProjects.length, locale) })}</strong>
          </div>
          {canEdit && (
            <Link to="/projects/new" className="btn-primary" style={{ textDecoration: 'none' }}>
              <Plus size={16} /> {t('list.actions.addProject')}
            </Link>
          )}
        </div>
      </div>

      <div className="admin-stats-grid">
        <div className="admin-stat-card">
          <div className="admin-stat-icon">
            <Layers3 size={18} />
          </div>
          <div>
            <span>{t('list.stats.totalProjects')}</span>
            <strong>{formatNumber(stats.total, locale)}</strong>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon" style={{ background: 'rgba(46, 213, 115, 0.12)', color: '#2ed573' }}>
            <Flag size={18} />
          </div>
          <div>
            <span>{t('list.stats.active')}</span>
            <strong>{formatNumber(stats.active, locale)}</strong>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon" style={{ background: 'rgba(255, 159, 67, 0.14)', color: 'var(--primary-color)' }}>
            <FileText size={18} />
          </div>
          <div>
            <span>{t('list.stats.draft')}</span>
            <strong>{formatNumber(stats.draftCount, locale)}</strong>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon" style={{ background: 'rgba(116, 125, 140, 0.14)', color: '#747d8c' }}>
            <Layers3 size={18} />
          </div>
          <div>
            <span>{t('list.stats.archived')}</span>
            <strong>{formatNumber(stats.archived, locale)}</strong>
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
            placeholder={t('list.search.placeholder')}
            dir="auto"
          />
        </label>

        <select className="filter-select" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="all">{t('list.filters.allStatuses')}</option>
          {STATUS_OPTIONS.map((status) => (
            <option key={status} value={status}>
              {statusLabels[status] || (status[0].toUpperCase() + status.slice(1))}
            </option>
          ))}
        </select>
      </div>

      <div className="glass-card admin-list-panel">
        <div className="panel-header-tight">
          <strong style={{ fontSize: '1rem' }}>{t('list.panel.title')}</strong>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            {isLoadingProjects && <span style={{ fontSize: '0.72rem', color: 'var(--text-light)' }}>{t('list.panel.loadingInline')}</span>}
            <span className="panel-chip">{t('list.panel.visibleCount', { count: visibleProjects.length, formattedCount: formatNumber(visibleProjects.length, locale) })}</span>
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {isLoadingProjects && projects.length === 0 && (
            <div className="admin-empty-state">
              <div className="admin-empty-state-icon">
                <RefreshCw size={18} className="spin" />
              </div>
              <strong>{t('list.emptyState.loadingTitle')}</strong>
              <span>{t('list.emptyState.loadingBody')}</span>
            </div>
          )}

          {projects.length === 0 && !isLoadingProjects && (
            <div className="admin-empty-state">
              <div className="admin-empty-state-icon">
                <CalendarDays size={18} />
              </div>
              <strong>{t('list.emptyState.noProjectsTitle')}</strong>
              <span>{t('list.emptyState.noProjectsBody')}</span>
              {canEdit && (
                <Link to="/projects/new" className="btn-primary" style={{ marginTop: 8, textDecoration: 'none' }}>
                  <Plus size={16} /> {t('list.actions.addProject')}
                </Link>
              )}
            </div>
          )}

          {pagedProjects.map((project, index) => {
            const assignedSourceCount = Array.isArray(project.source_ids) ? project.source_ids.length : 0;
            const isActive = (project.status || '').toLowerCase() === 'active';
            return (
              <motion.div
                key={project.id}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: index * 0.03 }}
                className="admin-item-card"
              >
                <div className="admin-item-top">
                  <div style={{ minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8, flexWrap: 'wrap' }}>
                      <strong className="admin-item-title project-item-title" dir="auto">{project.name}</strong>
                      <span className={`panel-chip ${isActive ? 'success' : project.status === 'archived' ? 'muted' : 'warning'}`}>
                        {(statusLabels[(project.status || 'draft').toLowerCase()] || project.status || 'draft').toUpperCase()}
                      </span>
                      {project.repeat_enabled && (
                        <span className="panel-chip success">
                          <RefreshCw size={12} /> {t('list.item.repeatEvery', { value: project.repeat_interval_value, unit: project.repeat_interval_unit })}
                        </span>
                      )}
                    </div>
                    <div className="admin-item-meta">
                      <span>{project.start_date || t('list.item.noStartDate')}</span>
                      <span>{project.end_date || t('list.item.noEndDate')}</span>
                      <span>
                        {t('list.item.sourceCount', { count: assignedSourceCount, formattedCount: formatNumber(assignedSourceCount, locale) })}
                      </span>
                      {project.repeat_enabled && (
                        <span>{t('list.item.nextRun', { value: formatDateTime(project.next_run_at, locale) || t('list.item.pendingFirstRun') })}</span>
                      )}
                      {project.last_run_at && <span>{t('list.item.lastRun', { value: formatDateTime(project.last_run_at, locale) })}</span>}
                    </div>
                    <div dir="auto" style={{ marginTop: 10, color: 'var(--text-light)', fontSize: '0.88rem', lineHeight: 1.5, overflowWrap: 'anywhere', wordBreak: 'break-word' }}>
                      {project.description || t('list.item.defaultDescription')}
                    </div>
                  </div>

                  <div className="admin-item-actions">
                    <Link
                      className="btn-secondary"
                      to={`/projects/${project.id}`}
                      style={{ padding: '8px 10px', fontSize: '0.8rem', textDecoration: 'none' }}
                    >
                      <Eye size={14} /> {t('common:actions.view')}
                    </Link>
                  </div>
                </div>
              </motion.div>
            );
          })}

          {!isLoadingProjects && visibleProjects.length === 0 && projects.length > 0 && (
            <div className="admin-empty-state">
              <div className="admin-empty-state-icon">
                <Search size={18} />
              </div>
              <strong>{t('list.emptyState.noMatchesTitle')}</strong>
              <span>{t('list.emptyState.noMatchesBody')}</span>
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
              {t('list.pagination.showingRange', {
                from: formatNumber((safePage - 1) * PAGE_SIZE + 1, locale),
                to: formatNumber(Math.min(safePage * PAGE_SIZE, visibleProjects.length), locale),
                total: formatNumber(visibleProjects.length, locale),
              })}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <button
                className="btn-secondary"
                onClick={() => setCurrentPage((value) => Math.max(1, value - 1))}
                disabled={safePage <= 1}
                style={{ padding: '8px 10px', fontSize: '0.8rem' }}
              >
                {t('common:actions.previous')}
              </button>
              <span className="panel-chip">
                {t('common:pagination.pageOfTotal', { page: formatNumber(safePage, locale), totalPages: formatNumber(totalPages, locale) })}
              </span>
              <button
                className="btn-secondary"
                onClick={() => setCurrentPage((value) => Math.min(totalPages, value + 1))}
                disabled={safePage >= totalPages}
                style={{ padding: '8px 10px', fontSize: '0.8rem' }}
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
