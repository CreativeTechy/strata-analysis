import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, Link2, RefreshCw, Save, Search, X } from 'lucide-react';

// Edit-only: changes which dashboard users are linked to one project. Viewing
// the current linkage lives on ProjectLinkageDetailPage; this page only
// renders the assignment form and hands back to the detail page on save.
export default function ProjectLinkageEditPage({ projects = [], users = [], onSetProjectUsers }) {
  const navigate = useNavigate();
  const params = useParams();

  const project = useMemo(
    () => projects.find((item) => Number(item.id) === Number(params.projectId)) || null,
    [projects, params.projectId]
  );

  const [query, setQuery] = useState('');
  const [draftUserIds, setDraftUserIds] = useState([]);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    setDraftUserIds(Array.isArray(project?.user_ids) ? project.user_ids.map(Number) : []);
    setError('');
  }, [project]);

  const visibleUsers = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return users;
    return users.filter((user) =>
      [user.username, user.email, user.role].filter(Boolean).some((value) => String(value).toLowerCase().includes(needle))
    );
  }, [users, query]);

  const isDirty = useMemo(() => {
    const current = new Set((project?.user_ids || []).map(Number));
    if (current.size !== draftUserIds.length) return true;
    return draftUserIds.some((id) => !current.has(id));
  }, [project, draftUserIds]);

  const toggleUser = (userId) => {
    const id = Number(userId);
    setDraftUserIds((prev) => (prev.includes(id) ? prev.filter((value) => value !== id) : [...prev, id]));
  };

  const save = async () => {
    if (!project || isSaving) return;
    setIsSaving(true);
    setError('');
    try {
      await onSetProjectUsers?.(project.id, draftUserIds);
      navigate(`/admin/project-linkage/${project.id}`);
    } catch (err) {
      setError(err?.message || 'Failed to update linked users.');
    } finally {
      setIsSaving(false);
    }
  };

  if (!project) {
    return (
      <div className="admin-page-shell">
        <div className="glass-card" style={{ maxWidth: 760, margin: '0 auto' }}>
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

  return (
    <div className="admin-page-shell">
      <div className="admin-page-header">
        <div>
          <div className="admin-page-kicker">
            <Link2 size={14} /> Project linkage
          </div>
          <h1 className="admin-page-title">Edit linkage: {project.name}</h1>
          <p className="admin-page-subtitle">Add or remove the dashboard users linked to this project.</p>
        </div>
        <div className="admin-page-toolbar">
          <div className="admin-page-toolbar-meta">
            <span>Selected</span>
            <strong>{draftUserIds.length}</strong>
          </div>
        </div>
      </div>

      <div className="glass-card admin-form-panel" style={{ maxWidth: 780, margin: '0 auto' }}>
        {error && (
          <div
            style={{
              padding: '12px 14px',
              borderRadius: 14,
              background: 'rgba(255, 71, 87, 0.08)',
              border: '1px solid rgba(255, 71, 87, 0.16)',
              color: '#b42318',
              fontSize: '0.84rem',
              lineHeight: 1.5,
            }}
          >
            {error}
          </div>
        )}

        <div className="assign-sources-panel">
          <div className="assign-sources-header">
            <div>
              <div className="assign-sources-kicker">Linked users</div>
              <strong className="assign-sources-title">Choose dashboard users linked to this project</strong>
            </div>
            <div className="assign-sources-summary">
              <span className="panel-chip">{draftUserIds.length} selected</span>
            </div>
          </div>

          <div className="assign-sources-toolbar">
            <label className="assign-sources-search">
              <Search size={14} />
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Filter users by username, email, or role"
                disabled={isSaving}
              />
            </label>
          </div>

          <div className="assign-sources-list">
            {users.length === 0 ? (
              <div style={{ color: 'var(--text-light)', fontSize: '0.85rem' }}>No dashboard users yet.</div>
            ) : visibleUsers.length === 0 ? (
              <div className="admin-empty-state" style={{ padding: '16px 10px' }}>
                <div className="admin-empty-state-icon" style={{ width: 36, height: 36 }}>
                  <Search size={16} />
                </div>
                <strong>No matching users</strong>
                <span>Try a different search term.</span>
              </div>
            ) : (
              visibleUsers.map((user) => {
                const userId = Number(user.id);
                const isSelected = draftUserIds.includes(userId);
                return (
                  <label key={user.id} className={`assign-source-item ${isSelected ? 'selected' : ''}`}>
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => toggleUser(userId)}
                      disabled={isSaving}
                    />
                    <div className="assign-source-copy">
                      <div className="assign-source-topline">
                        <strong className="assign-source-name">{user.username}</strong>
                        <span className={`panel-chip role-${user.role}`}>{user.role}</span>
                      </div>
                      <div className="assign-source-url">{user.email || 'No email on file'}</div>
                    </div>
                  </label>
                );
              })
            )}
          </div>
        </div>

        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 16, flexWrap: 'wrap' }}>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => navigate(`/admin/project-linkage/${project.id}`)}
            disabled={isSaving}
          >
            <X size={16} /> Cancel
          </button>
          <button type="button" className="btn-primary" onClick={save} disabled={isSaving || !isDirty}>
            {isSaving ? (
              <>
                <RefreshCw size={16} className="spin" /> Saving...
              </>
            ) : (
              <>
                <Save size={16} /> Save linkage
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
