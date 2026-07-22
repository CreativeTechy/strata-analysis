import { useEffect, useState } from 'react';
import { useNavigate, useParams, Link } from 'react-router-dom';
import { Pencil, ShieldAlert, ArrowLeft } from 'lucide-react';
import RoleForm from './RoleForm';

// Edit-only: loads one existing role and its permission set and saves changes
// back to it. Creating a new role lives in RoleCreatePage.
export default function RoleEditPage() {
  const navigate = useNavigate();
  const { roleId } = useParams();
  const [permissions, setPermissions] = useState([]);
  const [role, setRole] = useState(null);
  const [value, setValue] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    (async () => {
      setLoading(true);
      setLoadError('');
      try {
        const [rolesRes, permsRes] = await Promise.all([fetch('/api/roles'), fetch('/api/permissions')]);
        const rolesData = await rolesRes.json().catch(() => ({}));
        const permsData = await permsRes.json().catch(() => ({}));
        if (!rolesRes.ok) throw new Error(rolesData?.error || `Failed to load roles (${rolesRes.status})`);
        if (!permsRes.ok) throw new Error(permsData?.error || `Failed to load permissions (${permsRes.status})`);

        const roleList = Array.isArray(rolesData?.roles) ? rolesData.roles : [];
        const found = roleList.find((item) => String(item.id) === String(roleId)) || null;

        setPermissions(Array.isArray(permsData?.permissions) ? permsData.permissions : []);
        setRole(found);
        setValue(
          found
            ? { name: found.name, description: found.description || '', permissions: [...(found.permissions || [])] }
            : null
        );
      } catch (err) {
        setLoadError(err.message);
      } finally {
        setLoading(false);
      }
    })();
  }, [roleId]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!role) return;
    setError('');
    setSubmitting(true);
    try {
      const res = await fetch(`/api/roles/${role.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(value),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.error || `Failed to update role (${res.status})`);
      navigate('/admin/roles');
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  if (!loading && !role) {
    return (
      <div className="admin-page-shell">
        <div className="glass-card" style={{ maxWidth: 960, margin: '0 auto' }}>
          <div className="admin-empty-state" style={{ padding: '34px 20px' }}>
            <div className="admin-empty-state-icon">
              <ShieldAlert size={18} />
            </div>
            <strong>Role not found</strong>
            <span>{loadError || 'It may have been removed, or you may not have access to it.'}</span>
            <Link to="/admin/roles" className="btn-primary" style={{ marginTop: 8, textDecoration: 'none' }}>
              <ArrowLeft size={16} /> Back to Roles
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
            <Pencil size={14} /> Access control
          </div>
          <h1 className="admin-page-title">Edit role{role ? `: ${role.name}` : ''}</h1>
          <p className="admin-page-subtitle">Rename the role or adjust the permissions it grants.</p>
        </div>
      </div>

      {loadError && (
        <div className="panel-chip" style={{ background: '#fde2e2', color: '#9c1c1c', marginBottom: 16 }}>
          {loadError}
        </div>
      )}

      {loading && (
        <div className="glass-card" style={{ display: 'flex', alignItems: 'center', gap: 10, color: 'var(--text-light)' }}>
          <div className="loading-spinner" /> Loading role...
        </div>
      )}

      {!loading && value && (
        <RoleForm
          value={value}
          onChange={setValue}
          permissions={permissions}
          fullAccess={Boolean(role?.full_access)}
          submitLabel="Save changes"
          submitting={submitting}
          error={error}
          onSubmit={handleSubmit}
          onCancel={() => navigate('/admin/roles')}
        />
      )}
    </div>
  );
}
