import React, { useEffect, useMemo, useState } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { motion } from 'framer-motion';
import ConfirmModal from './ConfirmModal';
import { useAuth } from '../auth/useAuth.js';
import {
  Rss,
  Plus,
  Pencil,
  Trash2,
  Check,
  X,
  ToggleLeft,
  ToggleRight,
  Search,
  Link2,
  CheckCircle2,
  Layers3,
} from 'lucide-react';

const emptyDraft = {
  url: '',
  name: '',
  source_type: 'rss',
  category: '',
  enabled: true,
  limited: false,
  project_ids: [],
};

const SOURCE_TYPE_OPTIONS = [
  { value: 'rss', label: 'RSS' },
  { value: 'web', label: 'Web' },
  { value: 'social', label: 'Social' },
  { value: 'hashtag', label: 'Hashtag' },
  { value: 'keyword', label: 'Keyword' },
  { value: 'username', label: 'X Account' },
];

const TERM_SOURCE_TYPES = new Set(['hashtag', 'keyword', 'username']);

const TERM_SOURCE_PLACEHOLDERS = {
  hashtag: 'Hashtag, without # (e.g. EVSummit)',
  username: 'X account, without @ (e.g. elonmusk)',
  keyword: 'Keyword or phrase (e.g. electric vehicles)',
};

function sourceTypeLabel(sourceType) {
  const match = SOURCE_TYPE_OPTIONS.find((option) => option.value === (sourceType || 'rss'));
  return match ? match.label : (sourceType || 'RSS');
}

const PAGE_SIZE = 3;

function normalizeDraftForCompare(value) {
  return {
    url: String(value?.url || '').trim(),
    name: String(value?.name || '').trim(),
    source_type: String(value?.source_type || 'rss').trim().toLowerCase(),
    category: String(value?.category || '').trim(),
    enabled: Boolean(value?.enabled),
    limited: Boolean(value?.limited),
    project_ids: Array.isArray(value?.project_ids)
      ? [...new Set(value.project_ids.map((item) => Number(item)).filter((item) => Number.isFinite(item)))].sort((a, b) => a - b)
      : [],
  };
}

export default function SourcesPage({
  sources = [],
  projects = [],
  sourcesSource,
  onCreateSource,
  onUpdateSource,
  onDeleteSource,
  isLoadingSources,
}) {
  const location = useLocation();
  const navigate = useNavigate();
  const params = useParams();
  const { hasRole } = useAuth();
  const canEdit = hasRole('editor');
  const pathname = location.pathname;
  const isCreateRoute = pathname.endsWith('/new');
  const isEditRoute = pathname.endsWith('/edit');
  const isFormRoute = isCreateRoute || isEditRoute;
  const editingId = isEditRoute ? Number(params.sourceId) : null;
  const currentSource = useMemo(
    () => (editingId != null ? sources.find((source) => Number(source.id) === Number(editingId)) || null : null),
    [editingId, sources]
  );

  const [draft, setDraft] = useState(emptyDraft);
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [typeFilter, setTypeFilter] = useState('all');
  const [reachFilter, setReachFilter] = useState('all');
  const [currentPage, setCurrentPage] = useState(1);
  const [initialDraft, setInitialDraft] = useState(emptyDraft);
  const [showCancelModal, setShowCancelModal] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);

  useEffect(() => {
    if (!isFormRoute) {
      setDraft(emptyDraft);
      setInitialDraft(emptyDraft);
      setShowCancelModal(false);
      setDeleteTarget(null);
      return;
    }

    if (isEditRoute) {
      if (!currentSource) {
        setDraft(emptyDraft);
        setInitialDraft(emptyDraft);
        return;
      }

      const assignedProjectIds = projects
        .filter((project) => Array.isArray(project.source_ids) && project.source_ids.map(Number).includes(Number(currentSource.id)))
        .map((project) => Number(project.id));

      setDraft({
        url: currentSource.url || '',
        name: currentSource.name || '',
        source_type: currentSource.source_type || 'rss',
        category: currentSource.category || '',
        enabled: currentSource.enabled ?? true,
        limited: currentSource.limited ?? false,
        project_ids: assignedProjectIds,
      });
      setInitialDraft({
        url: currentSource.url || '',
        name: currentSource.name || '',
        source_type: currentSource.source_type || 'rss',
        category: currentSource.category || '',
        enabled: currentSource.enabled ?? true,
        limited: currentSource.limited ?? false,
        project_ids: assignedProjectIds,
      });
      return;
    }

    setDraft(emptyDraft);
    setInitialDraft(emptyDraft);
  }, [currentSource, projects, isEditRoute, isFormRoute]);

  const sourceProjectsById = useMemo(() => {
    const map = new Map();
    projects.forEach((project) => {
      (project.source_ids || []).forEach((sourceId) => {
        const id = Number(sourceId);
        if (!map.has(id)) map.set(id, []);
        map.get(id).push(project);
      });
    });
    return map;
  }, [projects]);

  const stats = useMemo(() => {
    const total = sources.length;
    const enabled = sources.filter((source) => source.enabled).length;
    const assigned = sources.filter((source) => (sourceProjectsById.get(Number(source.id)) || []).length > 0).length;
    const rss = sources.filter((source) => (source.source_type || 'rss') === 'rss').length;
    return { total, enabled, assigned, rss };
  }, [sources, sourceProjectsById]);

  const visibleSources = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return sources.filter((source) => {
      const sourceProjects = sourceProjectsById.get(Number(source.id)) || [];
      const matchesQuery =
        !needle ||
        [source.name, source.url, source.category, source.source_type, ...sourceProjects.map((project) => project.name)]
          .filter(Boolean)
          .some((value) => String(value).toLowerCase().includes(needle));
      const matchesStatus =
        statusFilter === 'all' ||
        (statusFilter === 'enabled' && source.enabled) ||
        (statusFilter === 'disabled' && !source.enabled) ||
        (statusFilter === 'assigned' && sourceProjects.length > 0) ||
        (statusFilter === 'unassigned' && sourceProjects.length === 0);
      const matchesType = typeFilter === 'all' || (source.source_type || 'rss') === typeFilter;
      const matchesReach =
        reachFilter === 'all' ||
        (reachFilter === 'limited' && source.limited) ||
        (reachFilter === 'global' && !source.limited);
      return matchesQuery && matchesStatus && matchesType && matchesReach;
    });
  }, [sources, sourceProjectsById, query, statusFilter, typeFilter, reachFilter]);

  const totalPages = Math.max(1, Math.ceil(visibleSources.length / PAGE_SIZE));
  const safePage = Math.min(currentPage, totalPages);
  const pagedSources = useMemo(() => {
    const start = (safePage - 1) * PAGE_SIZE;
    return visibleSources.slice(start, start + PAGE_SIZE);
  }, [visibleSources, safePage]);

  useEffect(() => {
    setCurrentPage(1);
  }, [query, statusFilter, typeFilter, reachFilter]);

  useEffect(() => {
    if (currentPage > totalPages) {
      setCurrentPage(totalPages);
    }
  }, [currentPage, totalPages]);

  const beginEdit = (source) => {
    navigate(`/sources/${source.id}/edit`);
  };

  const discardChanges = () => {
    setShowCancelModal(false);
    setDraft(emptyDraft);
    navigate('/sources');
  };

  const submit = async () => {
    const isTermType = TERM_SOURCE_TYPES.has(draft.source_type);
    const payload = {
      url: isTermType ? '' : draft.url.trim(),
      name: draft.name.trim(),
      source_type: draft.source_type,
      category: draft.category.trim(),
      enabled: Boolean(draft.enabled),
      limited: Boolean(draft.limited),
      project_ids: draft.project_ids,
    };

    if (isTermType ? !payload.name : !payload.url) return;

    if (editingId) {
      await onUpdateSource?.(editingId, payload);
    } else {
      await onCreateSource?.(payload);
    }

    navigate('/sources');
  };

  const toggleProject = (projectId) => {
    const id = Number(projectId);
    setDraft((prev) => ({
      ...prev,
      project_ids: prev.project_ids.includes(id)
        ? prev.project_ids.filter((value) => value !== id)
        : [...prev.project_ids, id],
    }));
  };

  const remove = async (source) => {
    await onDeleteSource?.(source.id);
    if (editingId === source.id) {
      navigate('/sources');
    }
  };

  const isDirty = useMemo(() => {
    return JSON.stringify(normalizeDraftForCompare(draft)) !== JSON.stringify(normalizeDraftForCompare(initialDraft));
  }, [draft, initialDraft]);

  const handleCancel = () => {
    if (isDirty) {
      setShowCancelModal(true);
      return;
    }
    discardChanges();
  };

  if (isFormRoute) {
    const heading = isEditRoute ? 'Edit Source' : 'Create Source';
    const buttonLabel = isEditRoute ? 'Save Source' : 'Create Source';
    return (
      <div className="admin-page-shell">
        <div className="admin-page-header">
          <div>
            <div className="admin-page-kicker">
              <Rss size={14} /> Source library
            </div>
            <h1 className="admin-page-title">{heading}</h1>
            <p className="admin-page-subtitle">
              {isEditRoute
                ? 'Update a tracked source and keep its project assignments in sync.'
                : 'Add a new source, classify it, and assign it to the projects it should power.'}
            </p>
          </div>
          <div className="admin-page-toolbar">
            <div className="admin-page-toolbar-meta">
              <span>Mode</span>
              <strong>{isEditRoute ? 'Editing' : 'Creating'}</strong>
            </div>
            <div className="admin-page-toolbar-meta">
              <span>Projects</span>
              <strong>{draft.project_ids.length.toLocaleString()}</strong>
            </div>
          </div>
        </div>

        <div className="glass-card admin-form-panel" style={{ maxWidth: 860, margin: '0 auto' }}>
          <div className="panel-header-tight">
            <strong style={{ fontSize: '1rem' }}>{heading}</strong>
            <span className="panel-chip">{isEditRoute ? 'Updating existing source' : 'Create a new source'}</span>
          </div>

          <label style={{ display: 'grid', gap: 6 }}>
            <span style={{ fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-light)' }}>Source type</span>
            <select
              className="filter-select"
              value={draft.source_type}
              onChange={(e) => setDraft((prev) => ({ ...prev, source_type: e.target.value }))}
            >
              {SOURCE_TYPE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          {!TERM_SOURCE_TYPES.has(draft.source_type) && (
            <label style={{ display: 'grid', gap: 6 }}>
              <span style={{ fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-light)' }}>Source URL</span>
              <input
                type="text"
                className="source-input"
                placeholder="Source URL"
                value={draft.url}
                onChange={(e) => setDraft((prev) => ({ ...prev, url: e.target.value }))}
              />
            </label>
          )}
          <label style={{ display: 'grid', gap: 6 }}>
            <span style={{ fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-light)' }}>Display name</span>
            <input
              type="text"
              className="source-input"
              placeholder={TERM_SOURCE_PLACEHOLDERS[draft.source_type] || 'Display name'}
              value={draft.name}
              onChange={(e) => setDraft((prev) => ({ ...prev, name: e.target.value }))}
            />
          </label>
          <label style={{ display: 'grid', gap: 6 }}>
            <span style={{ fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-light)' }}>Category</span>
            <input
              type="text"
              className="source-input"
              placeholder="Category"
              value={draft.category}
              onChange={(e) => setDraft((prev) => ({ ...prev, category: e.target.value }))}
            />
          </label>
          <div
            style={{
              padding: '14px 16px',
              borderRadius: 14,
              border: '1px solid rgba(15, 23, 42, 0.08)',
              background: 'rgba(255, 255, 255, 0.7)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 12,
              flexWrap: 'wrap',
            }}
          >
            <div style={{ minWidth: 0 }}>
              <strong style={{ display: 'block', fontSize: '0.9rem', color: 'var(--text-dark)' }}>Source status</strong>
              <span style={{ display: 'block', marginTop: 4, fontSize: '0.82rem', color: 'var(--text-light)' }}>
                Disable this source to keep it in the library without using it in pipelines.
              </span>
            </div>
            <button
              type="button"
              onClick={() => setDraft((prev) => ({ ...prev, enabled: !prev.enabled }))}
              className={`btn-secondary ${draft.enabled ? 'active' : ''}`}
              style={{
                minWidth: 160,
                justifyContent: 'center',
                background: draft.enabled ? 'rgba(46, 213, 115, 0.12)' : 'rgba(116, 125, 140, 0.12)',
                borderColor: draft.enabled ? 'rgba(46, 213, 115, 0.24)' : 'rgba(116, 125, 140, 0.16)',
                color: draft.enabled ? '#1e9e57' : '#5f6b7a',
              }}
            >
              {draft.enabled ? <ToggleRight size={18} /> : <ToggleLeft size={18} />}
              {draft.enabled ? 'Enabled' : 'Disabled'}
            </button>
          </div>

          <div
            style={{
              padding: '14px 16px',
              borderRadius: 14,
              border: '1px solid rgba(15, 23, 42, 0.08)',
              background: 'rgba(255, 255, 255, 0.7)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 12,
              flexWrap: 'wrap',
            }}
          >
            <div style={{ minWidth: 0 }}>
              <strong style={{ display: 'block', fontSize: '0.9rem', color: 'var(--text-dark)' }}>Source reach</strong>
              <span style={{ display: 'block', marginTop: 4, fontSize: '0.82rem', color: 'var(--text-light)' }}>
                Limited sources stay out of the assignable list on project create/edit pages unless already attached to that project.
              </span>
            </div>
            <button
              type="button"
              onClick={() => setDraft((prev) => ({ ...prev, limited: !prev.limited }))}
              className={`btn-secondary ${draft.limited ? 'active' : ''}`}
              style={{
                minWidth: 160,
                justifyContent: 'center',
                background: draft.limited ? 'rgba(255, 159, 67, 0.14)' : 'rgba(46, 134, 222, 0.1)',
                borderColor: draft.limited ? 'rgba(255, 159, 67, 0.28)' : 'rgba(46, 134, 222, 0.24)',
                color: draft.limited ? 'var(--primary-color)' : '#2e86de',
              }}
            >
              {draft.limited ? <ToggleLeft size={18} /> : <ToggleRight size={18} />}
              {draft.limited ? 'Limited' : 'Global'}
            </button>
          </div>

          <div style={{ padding: '8px 0 2px', fontSize: '0.86rem', color: 'var(--text-light)' }}>Assign to projects</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 220, overflow: 'auto' }}>
            {projects.length === 0 ? (
              <div style={{ color: 'var(--text-light)', fontSize: '0.85rem' }}>No projects yet. Create a project first.</div>
            ) : (
              projects.map((project) => (
                <label
                  key={project.id}
                  style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.85rem', color: 'var(--text-dark)' }}
                >
                  <input
                    type="checkbox"
                    checked={draft.project_ids.includes(Number(project.id))}
                    onChange={() => toggleProject(project.id)}
                  />
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{project.name}</span>
                </label>
              ))
            )}
          </div>

          <div style={{ display: 'flex', gap: 10, marginTop: 12 }}>
            <button className="btn-primary" onClick={submit} style={{ flex: 1 }}>
              {editingId ? (
                <>
                  <Check size={18} /> {buttonLabel}
                </>
              ) : (
                <>
                  <Plus size={18} /> {buttonLabel}
                </>
              )}
            </button>
            <button className="btn-secondary" type="button" onClick={handleCancel} style={{ flexShrink: 0 }}>
              <X size={18} /> Cancel
            </button>
          </div>
        </div>

        <ConfirmModal
          open={showCancelModal}
          title="Discard changes?"
          message="You have unsaved changes on this source. If you cancel now, all edits on this page will be lost."
          confirmLabel="Discard changes"
          cancelLabel="Keep editing"
          onClose={() => setShowCancelModal(false)}
          onConfirm={discardChanges}
        />

      </div>
    );
  }

  return (
    <div className="admin-page-shell">
      <div className="admin-page-header">
        <div>
          <div className="admin-page-kicker">
            <Rss size={14} /> Source library
          </div>
          <h1 className="admin-page-title">Source Manager</h1>
          <p className="admin-page-subtitle">
            Curate the source pool, assign sources to one or more projects, and keep enabled sources easy to scan.
          </p>
        </div>
        <div className="admin-page-toolbar">
          <div className="admin-page-toolbar-meta">
            <span>Source</span>
            <strong>{sourcesSource || 'supabase'}</strong>
          </div>
          <div className="admin-page-toolbar-meta">
            <span>Search</span>
            <strong>{visibleSources.length.toLocaleString()} matches</strong>
          </div>
          {canEdit && (
            <Link to="/sources/new" className="btn-primary" style={{ textDecoration: 'none' }}>
              <Plus size={16} /> Add Source
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
            <span>Total sources</span>
            <strong>{stats.total.toLocaleString()}</strong>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon" style={{ background: 'rgba(46, 213, 115, 0.12)', color: '#2ed573' }}>
            <CheckCircle2 size={18} />
          </div>
          <div>
            <span>Enabled</span>
            <strong>{stats.enabled.toLocaleString()}</strong>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon" style={{ background: 'rgba(46, 134, 222, 0.12)', color: 'var(--secondary-color)' }}>
            <Link2 size={18} />
          </div>
          <div>
            <span>Assigned</span>
            <strong>{stats.assigned.toLocaleString()}</strong>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon" style={{ background: 'rgba(255, 159, 67, 0.14)', color: 'var(--primary-color)' }}>
            <Rss size={18} />
          </div>
          <div>
            <span>RSS sources</span>
            <strong>{stats.rss.toLocaleString()}</strong>
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
            placeholder="Search sources, URLs, categories, or project names"
          />
        </label>

        <select className="filter-select" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="all">All sources</option>
          <option value="enabled">Enabled</option>
          <option value="disabled">Disabled</option>
          <option value="assigned">Assigned</option>
          <option value="unassigned">Unassigned</option>
        </select>

        <select className="filter-select" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
          <option value="all">All types</option>
          {SOURCE_TYPE_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>

        <select className="filter-select" value={reachFilter} onChange={(e) => setReachFilter(e.target.value)}>
          <option value="all">Global &amp; limited</option>
          <option value="global">Global</option>
          <option value="limited">Limited</option>
        </select>
      </div>

      <div className="glass-card admin-list-panel">
        <div className="panel-header-tight">
          <strong style={{ fontSize: '1rem' }}>Tracked Sources</strong>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            {isLoadingSources && <span style={{ fontSize: '0.72rem', color: 'var(--text-light)' }}>Loading...</span>}
            <span className="panel-chip">{visibleSources.length} visible</span>
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {sources.length === 0 && !isLoadingSources && (
            <div className="admin-empty-state">
              <div className="admin-empty-state-icon">
                <Rss size={18} />
              </div>
              <strong>No sources yet</strong>
              <span>Add your first source, then attach it to one or more projects.</span>
              {canEdit && (
                <Link to="/sources/new" className="btn-primary" style={{ marginTop: 8, textDecoration: 'none' }}>
                  <Plus size={16} /> Add Source
                </Link>
              )}
            </div>
          )}

          {pagedSources.map((source, index) => {
            const sourceProjects = sourceProjectsById.get(Number(source.id)) || [];
            return (
              <motion.div
                key={source.id ?? source.url}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: index * 0.03 }}
                className="admin-item-card"
              >
                <div className="admin-item-top">
                  <div style={{ minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8, flexWrap: 'wrap' }}>
                      <strong className="admin-item-title">{source.name || source.url?.replace('https://www.', '')}</strong>
                      <span className={`panel-chip ${source.enabled ? 'success' : 'muted'}`}>
                        {source.enabled ? 'Enabled' : 'Disabled'}
                      </span>
                      {source.limited && <span className="panel-chip warning">Limited</span>}
                    </div>
                    <div className="admin-item-url">{source.url}</div>
                    <div className="admin-item-meta">
                      <span>{sourceTypeLabel(source.source_type)}</span>
                      {source.category ? <span>{source.category}</span> : null}
                      <span>
                        {sourceProjects.length} project{sourceProjects.length === 1 ? '' : 's'}
                      </span>
                    </div>
                  </div>

                  {canEdit && (
                    <div className="admin-item-actions">
                      <Link
                        className="btn-secondary"
                        to={`/sources/${source.id}/edit`}
                        style={{ padding: '8px 10px', fontSize: '0.8rem', textDecoration: 'none' }}
                      >
                        <Pencil size={14} /> Edit
                      </Link>
                      <button
                        className="btn-secondary"
                        onClick={() => setDeleteTarget(source)}
                        style={{ padding: '8px 10px', fontSize: '0.8rem', color: '#ff4757' }}
                      >
                        <Trash2 size={14} /> Delete
                      </button>
                    </div>
                  )}
                </div>
                <div className="admin-item-chips">
                  {sourceProjects.length ? (
                    sourceProjects.slice(0, 4).map((project) => (
                      <span key={project.id} className="admin-tag">
                        {project.name}
                      </span>
                    ))
                  ) : (
                    <span className="admin-tag muted">Unassigned</span>
                  )}
                </div>
              </motion.div>
            );
          })}

          {!isLoadingSources && visibleSources.length === 0 && sources.length > 0 && (
            <div className="admin-empty-state">
              <div className="admin-empty-state-icon">
                <Search size={18} />
              </div>
              <strong>No matching sources</strong>
              <span>Try a different search term or status filter.</span>
            </div>
          )}
        </div>

        {visibleSources.length > 0 && (
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
              Showing {(safePage - 1) * PAGE_SIZE + 1}-{Math.min(safePage * PAGE_SIZE, visibleSources.length)} of {visibleSources.length}
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

        <ConfirmModal
          open={Boolean(deleteTarget)}
          title={`Delete source "${deleteTarget?.name || deleteTarget?.url || ''}"?`}
          message="This will permanently remove the source and detach it from any linked projects."
          confirmLabel="Delete source"
          cancelLabel="Keep source"
          confirmButtonStyle={{
            background: 'linear-gradient(135deg, #ff4757, #e03131)',
            boxShadow: '0 4px 15px rgba(255, 71, 87, 0.28)',
          }}
          onClose={() => setDeleteTarget(null)}
          onConfirm={async () => {
            if (!deleteTarget) return;
            const target = deleteTarget;
            setDeleteTarget(null);
            await remove(target);
          }}
        />
      </div>
    </div>
  );
}
