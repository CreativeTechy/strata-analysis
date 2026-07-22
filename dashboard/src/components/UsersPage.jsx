import { useEffect, useState } from 'react';
import { UserPlus, Users as UsersIcon, Ban, CheckCircle2, Trash2 } from 'lucide-react';
import { useAuth } from '../auth/useAuth.js';
import ConfirmModal from './ConfirmModal';
import '../styles/AdminUsers.css';

const emptyDraft = { username: '', email: '', password: '', role: '' };

export default function UsersPage() {
  const { user: currentUser, hasPermission } = useAuth();
  const canDelete = hasPermission('users.delete');
  const [users, setUsers] = useState([]);
  const [roles, setRoles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [draft, setDraft] = useState(emptyDraft);
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleting, setDeleting] = useState(false);

  const loadUsers = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/users');
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.error || `Failed to load users (${res.status})`);
      setUsers(Array.isArray(data?.users) ? data.users : []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const loadRoles = async () => {
    try {
      const res = await fetch('/api/roles');
      const data = await res.json().catch(() => ({}));
      if (!res.ok) return;
      const roleList = Array.isArray(data?.roles) ? data.roles : [];
      setRoles(roleList);
      setDraft((prev) => (prev.role ? prev : { ...prev, role: roleList[0]?.name || '' }));
    } catch {
      // Role list is only used to populate the select options; if it fails
      // to load the selects below just render empty.
    }
  };

  useEffect(() => {
    loadUsers();
    loadRoles();
  }, []);

  const createUser = async (e) => {
    e.preventDefault();
    setError('');
    setCreating(true);
    try {
      const res = await fetch('/api/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(draft),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.error || `Failed to create user (${res.status})`);
      setDraft(emptyDraft);
      await loadUsers();
    } catch (err) {
      setError(err.message);
    } finally {
      setCreating(false);
    }
  };

  const setStatus = async (userId, status) => {
    setError('');
    try {
      const res = await fetch(`/api/users/${userId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.error || `Failed to update user (${res.status})`);
      await loadUsers();
    } catch (err) {
      setError(err.message);
    }
  };

  const setRole = async (userId, role) => {
    setError('');
    try {
      const res = await fetch(`/api/users/${userId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.error || `Failed to update user (${res.status})`);
      await loadUsers();
    } catch (err) {
      setError(err.message);
    }
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    const target = deleteTarget;
    setError('');
    setDeleting(true);
    try {
      const res = await fetch(`/api/users/${target.id}`, { method: 'DELETE' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.error || `Failed to delete user (${res.status})`);
      setDeleteTarget(null);
      await loadUsers();
    } catch (err) {
      setError(err.message);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="admin-page-shell">
      <div className="admin-page-header">
        <div>
          <div className="admin-page-kicker">
            <UsersIcon size={14} /> User management
          </div>
          <h1 className="admin-page-title">Users</h1>
          <p className="admin-page-subtitle">Create and manage dashboard accounts.</p>
        </div>
        <div className="admin-page-toolbar">
          <div className="admin-page-toolbar-meta">
            <span>Total users</span>
            <strong>{users.length.toLocaleString()}</strong>
          </div>
        </div>
      </div>

      {error && (
        <div className="panel-chip" style={{ background: '#fde2e2', color: '#9c1c1c', marginBottom: 16 }}>
          {error}
        </div>
      )}

      <form onSubmit={createUser} className="glass-card user-create-form" style={{ marginBottom: 24 }}>
        <label className="user-create-field">
          <span style={{ fontSize: '0.8rem' }}>Username</span>
          <input className="filter-select" value={draft.username} onChange={(e) => setDraft({ ...draft, username: e.target.value })} required />
        </label>
        <label className="user-create-field">
          <span style={{ fontSize: '0.8rem' }}>Email</span>
          <input className="filter-select" type="email" value={draft.email} onChange={(e) => setDraft({ ...draft, email: e.target.value })} />
        </label>
        <label className="user-create-field">
          <span style={{ fontSize: '0.8rem' }}>Password</span>
          <input className="filter-select" type="password" value={draft.password} onChange={(e) => setDraft({ ...draft, password: e.target.value })} minLength={8} required />
        </label>
        <label className="user-create-field">
          <span style={{ fontSize: '0.8rem' }}>Role</span>
          <select className="filter-select" value={draft.role} onChange={(e) => setDraft({ ...draft, role: e.target.value })}>
            {roles.map((role) => <option key={role.id} value={role.name}>{role.name}</option>)}
          </select>
        </label>
        <button type="submit" className="btn-primary" disabled={creating}>
          <UserPlus size={16} /> {creating ? 'Creating...' : 'Create user'}
        </button>
      </form>

      <div className="glass-card" style={{ padding: 0, overflow: 'hidden' }}>
        <div className="table-scroll">
          <table>
            <thead>
              <tr style={{ textAlign: 'left', background: 'rgba(0,0,0,0.03)' }}>
                <th style={{ padding: 12 }}>Username</th>
                <th className="admin-table-col-optional" style={{ padding: 12 }}>Email</th>
                <th style={{ padding: 12 }}>Role</th>
                <th style={{ padding: 12 }}>Status</th>
                <th style={{ padding: 12 }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr>
                  <td colSpan={5} style={{ padding: 16 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: 'var(--text-light)' }}>
                      <div className="loading-spinner" /> Loading users...
                    </div>
                  </td>
                </tr>
              )}
              {!loading && users.length === 0 && (
                <tr>
                  <td colSpan={5} style={{ padding: 0 }}>
                    <div className="admin-empty-state">
                      <div className="admin-empty-state-icon">
                        <UsersIcon size={18} />
                      </div>
                      <strong>No users yet</strong>
                      <span>Create the first dashboard account using the form above.</span>
                    </div>
                  </td>
                </tr>
              )}
              {users.map((u) => {
                const isSelf = currentUser && Number(currentUser.id) === Number(u.id);
                return (
                  <tr key={u.id} style={{ borderTop: '1px solid rgba(0,0,0,0.06)' }}>
                    <td style={{ padding: 12 }}>{u.username}{isSelf && ' (you)'}</td>
                    <td className="admin-table-col-optional" style={{ padding: 12 }}>{u.email || '-'}</td>
                    <td style={{ padding: 12 }}>
                      <select
                        className="filter-select"
                        value={u.role}
                        disabled={isSelf}
                        onChange={(e) => setRole(u.id, e.target.value)}
                      >
                        {roles.map((role) => <option key={role.id} value={role.name}>{role.name}</option>)}
                      </select>
                    </td>
                    <td style={{ padding: 12 }}>{u.status}</td>
                    <td style={{ padding: 12 }}>
                      <div className="admin-row-actions">
                        {u.status === 'active' ? (
                          <button className="btn-secondary" disabled={isSelf} onClick={() => setStatus(u.id, 'disabled')}>
                            <Ban size={14} /> Disable
                          </button>
                        ) : (
                          <button className="btn-secondary" onClick={() => setStatus(u.id, 'active')}>
                            <CheckCircle2 size={14} /> Enable
                          </button>
                        )}
                        {canDelete && (
                          <button
                            className="btn-secondary"
                            disabled={isSelf}
                            title={isSelf ? 'You cannot delete your own account.' : undefined}
                            onClick={() => setDeleteTarget(u)}
                            style={{ color: isSelf ? undefined : '#ff4757' }}
                          >
                            <Trash2 size={14} /> Delete
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <ConfirmModal
        open={Boolean(deleteTarget)}
        title={`Delete user "${deleteTarget?.username || ''}"?`}
        message="This permanently removes the user account and signs them out of any active sessions."
        confirmLabel={deleting ? 'Deleting...' : 'Delete user'}
        cancelLabel="Keep user"
        confirmButtonStyle={{
          background: 'linear-gradient(135deg, #ff4757, #e03131)',
          boxShadow: '0 4px 15px rgba(255, 71, 87, 0.28)',
        }}
        onClose={() => setDeleteTarget(null)}
        onConfirm={confirmDelete}
      />
    </div>
  );
}
