import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { useAuth } from '../auth/useAuth.js';
import { PAGE_SIZE, STATUS_OPTIONS, formatDateTime } from '../lib/projectHelpers.js';
import '../styles/Projects.css';
import { CalendarDays, Eye, Plus, Search, Flag, Layers3, RefreshCw, FileText } from 'lucide-react';

// The Opinion Monitor project browser, extracted out of ProjectsPage.jsx:
// search/filter/paginate the project list. Mounted only on /projects, so
// (unlike when this lived inside ProjectsPage) it owns nothing wizard-related
// - no draft, no document pipeline state.
export default function ProjectsListView({ projects = [], isLoadingProjects }) {
  const { hasPermission } = useAuth();
  const canEdit = hasPermission('projects.create') || hasPermission('projects.update') || hasPermission('projects.delete');

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
            <CalendarDays size={14} /> Opinion monitoring
          </div>
          <h1 className="admin-page-title">Opinion Monitor</h1>
          <p className="admin-page-subtitle">
            Track what people are saying about each project as its own workspace: upload the documents it covers, approve the articles they hold, and keep every analysis tied to a named project.
          </p>
        </div>
        <div className="admin-page-toolbar">
          <div className="admin-page-toolbar-meta">
            <span>Status</span>
            <strong>{projects.length ? 'Configured' : 'Empty'}</strong>
          </div>
          <div className="admin-page-toolbar-meta">
            <span>Search</span>
            <strong>{visibleProjects.length.toLocaleString()} matches</strong>
          </div>
          {canEdit && (
            <Link to="/projects/new" className="btn-primary" style={{ textDecoration: 'none' }}>
              <Plus size={16} /> Add Project
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
            <span>Total projects</span>
            <strong>{stats.total.toLocaleString()}</strong>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon" style={{ background: 'rgba(46, 213, 115, 0.12)', color: '#2ed573' }}>
            <Flag size={18} />
          </div>
          <div>
            <span>Active</span>
            <strong>{stats.active.toLocaleString()}</strong>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon" style={{ background: 'rgba(255, 159, 67, 0.14)', color: 'var(--primary-color)' }}>
            <FileText size={18} />
          </div>
          <div>
            <span>Draft</span>
            <strong>{stats.draftCount.toLocaleString()}</strong>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon" style={{ background: 'rgba(116, 125, 140, 0.14)', color: '#747d8c' }}>
            <Layers3 size={18} />
          </div>
          <div>
            <span>Archived</span>
            <strong>{stats.archived.toLocaleString()}</strong>
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
            placeholder="Search projects, dates, statuses, or keywords"
          />
        </label>

        <select className="filter-select" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="all">All statuses</option>
          {STATUS_OPTIONS.map((status) => (
            <option key={status} value={status}>
              {status[0].toUpperCase() + status.slice(1)}
            </option>
          ))}
        </select>
      </div>

      <div className="glass-card admin-list-panel">
        <div className="panel-header-tight">
          <strong style={{ fontSize: '1rem' }}>Tracked Projects</strong>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            {isLoadingProjects && <span style={{ fontSize: '0.72rem', color: 'var(--text-light)' }}>Loading...</span>}
            <span className="panel-chip">{visibleProjects.length} visible</span>
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {isLoadingProjects && projects.length === 0 && (
            <div className="admin-empty-state">
              <div className="admin-empty-state-icon">
                <RefreshCw size={18} className="spin" />
              </div>
              <strong>Loading projects...</strong>
              <span>Fetching the latest project list from the workspace.</span>
            </div>
          )}

          {projects.length === 0 && !isLoadingProjects && (
            <div className="admin-empty-state">
              <div className="admin-empty-state-icon">
                <CalendarDays size={18} />
              </div>
              <strong>No projects yet</strong>
              <span>Start by creating a project, then upload the documents it should analyze.</span>
              {canEdit && (
                <Link to="/projects/new" className="btn-primary" style={{ marginTop: 8, textDecoration: 'none' }}>
                  <Plus size={16} /> Add Project
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
                      <strong className="admin-item-title project-item-title">{project.name}</strong>
                      <span className={`panel-chip ${isActive ? 'success' : project.status === 'archived' ? 'muted' : 'warning'}`}>
                        {(project.status || 'draft').toUpperCase()}
                      </span>
                      {project.repeat_enabled && (
                        <span className="panel-chip success">
                          <RefreshCw size={12} /> Every {project.repeat_interval_value} {project.repeat_interval_unit}
                        </span>
                      )}
                    </div>
                    <div className="admin-item-meta">
                      <span>{project.start_date || 'No start date'}</span>
                      <span>{project.end_date || 'No end date'}</span>
                      <span>
                        {assignedSourceCount} source{assignedSourceCount === 1 ? '' : 's'}
                      </span>
                      {project.repeat_enabled && (
                        <span>Next run: {formatDateTime(project.next_run_at) || 'Pending first run'}</span>
                      )}
                      {project.last_run_at && <span>Last run: {formatDateTime(project.last_run_at)}</span>}
                    </div>
                    <div style={{ marginTop: 10, color: 'var(--text-light)', fontSize: '0.88rem', lineHeight: 1.5, overflowWrap: 'anywhere', wordBreak: 'break-word' }}>
                      {project.description || 'Open the project to see assigned sources, tags, and metadata.'}
                    </div>
                  </div>

                  <div className="admin-item-actions">
                    <Link
                      className="btn-secondary"
                      to={`/projects/${project.id}`}
                      style={{ padding: '8px 10px', fontSize: '0.8rem', textDecoration: 'none' }}
                    >
                      <Eye size={14} /> View
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
              <strong>No matching projects</strong>
              <span>Try another search term or switch the status filter.</span>
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
              Showing {(safePage - 1) * PAGE_SIZE + 1}-{Math.min(safePage * PAGE_SIZE, visibleProjects.length)} of {visibleProjects.length}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <button
                className="btn-secondary"
                onClick={() => setCurrentPage((value) => Math.max(1, value - 1))}
                disabled={safePage <= 1}
                style={{ padding: '8px 10px', fontSize: '0.8rem' }}
              >
                Previous
              </button>
              <span className="panel-chip">
                Page {safePage} of {totalPages}
              </span>
              <button
                className="btn-secondary"
                onClick={() => setCurrentPage((value) => Math.min(totalPages, value + 1))}
                disabled={safePage >= totalPages}
                style={{ padding: '8px 10px', fontSize: '0.8rem' }}
              >
                Next
              </button>
            </div>
          </div>
        )}

      </div>
    </div>
  );
}
