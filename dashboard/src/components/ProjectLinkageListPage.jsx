import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Eye, Layers3, Link2, Pencil, Search, Users } from 'lucide-react';

const STATUS_OPTIONS = ['draft', 'active', 'archived'];
const PAGE_SIZE = 10;

// List-only entry point for project<->user linkage management. Viewing and
// editing a single project's linkage live on their own routed pages
// (ProjectLinkageDetailPage / ProjectLinkageEditPage); this page never
// renders the assignment UI itself.
export default function ProjectLinkageListPage({ projects = [], users = [], isLoadingProjects, isLoadingUsers }) {
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
    <div className="admin-page-shell">
      <div className="admin-page-header">
        <div>
          <div className="admin-page-kicker">
            <Link2 size={14} /> Access control
          </div>
          <h1 className="admin-page-title">Project Linkage</h1>
          <p className="admin-page-subtitle">
            See which dashboard users are linked to each project. Open a project to review its linked users, or edit
            the linkage directly.
          </p>
        </div>
        <div className="admin-page-toolbar">
          <div className="admin-page-toolbar-meta">
            <span>Projects</span>
            <strong>{projects.length}</strong>
          </div>
          <div className="admin-page-toolbar-meta">
            <span>Matches</span>
            <strong>{visibleProjects.length}</strong>
          </div>
        </div>
      </div>

      <div className="admin-stats-grid">
        <div className="admin-stat-card">
          <div className="admin-stat-icon">
            <Layers3 size={18} />
          </div>
          <div>
            <span>Total projects</span>
            <strong>{projects.length.toLocaleString()}</strong>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon" style={{ background: 'rgba(46, 134, 222, 0.12)', color: '#2e86de' }}>
            <Users size={18} />
          </div>
          <div>
            <span>Dashboard users</span>
            <strong>{users.length.toLocaleString()}</strong>
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
            placeholder="Search projects by name"
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

        <select
          className="filter-select"
          value={userFilter}
          onChange={(e) => setUserFilter(e.target.value)}
          disabled={isLoadingUsers}
        >
          <option value="all">{isLoadingUsers ? 'Loading users...' : 'All linked users'}</option>
          {sortedUsers.map((user) => (
            <option key={user.id} value={user.id}>
              {user.username}
            </option>
          ))}
        </select>
      </div>

      <div className="glass-card admin-list-panel">
        <div className="panel-header-tight">
          <strong style={{ fontSize: '1rem' }}>Projects</strong>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            {isLoadingProjects && <span style={{ fontSize: '0.72rem', color: 'var(--text-light)' }}>Loading...</span>}
            <span className="panel-chip">{visibleProjects.length} visible</span>
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {projects.length === 0 && !isLoadingProjects && (
            <div className="admin-empty-state">
              <div className="admin-empty-state-icon">
                <Link2 size={18} />
              </div>
              <strong>No projects yet</strong>
              <span>Create a project first, then manage its linked users here.</span>
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
                      <strong className="admin-item-title">{project.name}</strong>
                      <span className={`panel-chip ${isActive ? 'success' : status === 'archived' ? 'muted' : 'warning'}`}>
                        {status.toUpperCase()}
                      </span>
                    </div>
                    <div className="admin-item-meta">
                      <span>
                        {linkedCount} linked user{linkedCount === 1 ? '' : 's'}
                      </span>
                    </div>
                  </div>

                  <div className="admin-item-actions">
                    <Link
                      className="btn-secondary"
                      to={`/admin/project-linkage/${project.id}`}
                      style={{ padding: '8px 10px', fontSize: '0.8rem', textDecoration: 'none' }}
                    >
                      <Eye size={14} /> View
                    </Link>
                    <Link
                      className="btn-secondary"
                      to={`/admin/project-linkage/${project.id}/edit`}
                      style={{ padding: '8px 10px', fontSize: '0.8rem', textDecoration: 'none' }}
                    >
                      <Pencil size={14} /> Edit
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
              <strong>No matching projects</strong>
              <span>Try another search term or adjust the filters.</span>
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
              Showing {(safePage - 1) * PAGE_SIZE + 1}-{Math.min(safePage * PAGE_SIZE, visibleProjects.length)} of{' '}
              {visibleProjects.length}
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
