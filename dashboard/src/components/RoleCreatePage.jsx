import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ShieldPlus } from 'lucide-react';
import RoleForm from './RoleForm';
import { listPermissions, createRole } from '../api/adminApi.js';

const emptyValue = { name: '', description: '', permissions: [] };

// Create-only: builds a brand new role and its permission set, then hands
// back to the roles list. Editing an existing role lives in RoleEditPage.
export default function RoleCreatePage() {
  const navigate = useNavigate();
  const [permissions, setPermissions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [value, setValue] = useState(emptyValue);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    (async () => {
      setLoading(true);
      setLoadError('');
      try {
        const data = await listPermissions();
        setPermissions(Array.isArray(data?.permissions) ? data.permissions : []);
      } catch (err) {
        setLoadError(err.message);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      await createRole(value);
      navigate('/admin/roles');
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="admin-page-shell">
      <div className="admin-page-header">
        <div>
          <div className="admin-page-kicker">
            <ShieldPlus size={14} /> Access control
          </div>
          <h1 className="admin-page-title">New role</h1>
          <p className="admin-page-subtitle">Name the role and choose which permissions it grants.</p>
        </div>
      </div>

      {loadError && (
        <div className="panel-chip" style={{ background: '#fde2e2', color: '#9c1c1c', marginBottom: 16 }}>
          {loadError}
        </div>
      )}

      {loading && (
        <div className="glass-card" style={{ display: 'flex', alignItems: 'center', gap: 10, color: 'var(--text-light)' }}>
          <div className="loading-spinner" /> Loading permissions...
        </div>
      )}

      {!loading && (
        <RoleForm
          value={value}
          onChange={setValue}
          permissions={permissions}
          submitLabel="Create role"
          submitting={submitting}
          error={error}
          onSubmit={handleSubmit}
          onCancel={() => navigate('/admin/roles')}
        />
      )}
    </div>
  );
}
