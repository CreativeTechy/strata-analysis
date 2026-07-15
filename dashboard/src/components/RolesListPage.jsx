import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ShieldCheck, ShieldPlus, Trash2, Pencil } from 'lucide-react';
import ConfirmModal from './ConfirmModal';
import { useAuth } from '../auth/useAuth.js';

// List-only: the entry point for role administration. Create/edit happen on
// their own routed pages (RoleCreatePage/RoleEditPage); this page never
// renders a form itself.
export default function RolesListPage() {
  const { hasPermission } = useAuth();
  const canManage = hasPermission('roles.manage');

  const [roles, setRoles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleting, setDeleting] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/roles');
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.error || `Failed to load roles (${res.status})`);
      setRoles(Array.isArray(data?.roles) ? data.roles : []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    const target = deleteTarget;
    setError('');
    setDeleting(true);
    try {
      const res = await fetch(`/api/roles/${target.id}`, { method: 'DELETE' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.error || `Failed to delete role (${res.status})`);
      setDeleteTarget(null);
      await load();
    } catch (err) {
      // Keep the dialog open so the "in use" (or other) rejection from the
      // backend - the source of truth for whether deletion is allowed - is
      // visible right next to the role the user tried to remove.
      setError(err.message);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="content-shell" style={{ maxWidth: 900, margin: '0 auto', paddingTop: 80 }}>
      <header style={{ marginBottom: 20, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <h2 style={{ fontSize: '1.8rem' }}>
            <ShieldCheck size={22} style={{ marginRight: 8, verticalAlign: 'middle' }} />
            Roles &amp; Permissions
          </h2>
          <p className="subtitle">Roles are named permission sets assigned to users.</p>
        </div>
        {canManage && (
          <Link to="/admin/roles/new" className="btn-primary" style={{ textDecoration: 'none' }}>
            <ShieldPlus size={16} /> New role
          </Link>
        )}
      </header>

      {error && (
        <div className="panel-chip" style={{ background: '#fde2e2', color: '#9c1c1c', marginBottom: 16 }}>
          {error}
        </div>
      )}

      <div className="glass-card" style={{ padding: 0, overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ textAlign: 'left', background: 'rgba(0,0,0,0.03)' }}>
              <th style={{ padding: 12 }}>Role</th>
              <th style={{ padding: 12 }}>Description</th>
              <th style={{ padding: 12 }}>Permissions</th>
              <th style={{ padding: 12 }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan={4} style={{ padding: 16 }}>Loading...</td></tr>
            )}
            {!loading && roles.length === 0 && (
              <tr><td colSpan={4} style={{ padding: 16 }}>No roles yet.</td></tr>
            )}
            {!loading && roles.map((role) => (
              <tr key={role.id} style={{ borderTop: '1px solid rgba(0,0,0,0.06)' }}>
                <td style={{ padding: 12 }}>
                  <strong>{role.name}</strong>
                  {role.is_system && <span className="panel-chip" style={{ marginLeft: 8 }}>System</span>}
                </td>
                <td style={{ padding: 12 }}>{role.description || '-'}</td>
                <td style={{ padding: 12 }}>
                  {role.full_access ? (
                    <span className="panel-chip">Full access</span>
                  ) : (
                    `${role.permissions?.length || 0} permission${role.permissions?.length === 1 ? '' : 's'}`
                  )}
                </td>
                <td style={{ padding: 12 }}>
                  {canManage ? (
                    <div style={{ display: 'flex', gap: 8 }}>
                      <Link
                        className="btn-secondary"
                        to={`/admin/roles/${role.id}/edit`}
                        style={{ padding: '8px 10px', fontSize: '0.8rem', textDecoration: 'none' }}
                      >
                        <Pencil size={14} /> Edit
                      </Link>
                      <button
                        className="btn-secondary"
                        disabled={role.is_system}
                        title={role.is_system ? 'System roles cannot be deleted.' : undefined}
                        onClick={() => setDeleteTarget(role)}
                        style={{ padding: '8px 10px', fontSize: '0.8rem', color: role.is_system ? undefined : '#ff4757' }}
                      >
                        <Trash2 size={14} /> Delete
                      </button>
                    </div>
                  ) : (
                    <span className="subtitle">View only</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ConfirmModal
        open={Boolean(deleteTarget)}
        title={`Delete role "${deleteTarget?.name || ''}"?`}
        message="This permanently removes the role. Deletion is blocked while any user is still assigned to it - move those users to another role first."
        confirmLabel={deleting ? 'Deleting...' : 'Delete role'}
        cancelLabel="Keep role"
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
