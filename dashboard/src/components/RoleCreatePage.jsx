import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ShieldPlus } from 'lucide-react';
import RoleForm from './RoleForm';

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
        const res = await fetch('/api/permissions');
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data?.error || `Failed to load permissions (${res.status})`);
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
      const res = await fetch('/api/roles', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(value),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.error || `Failed to create role (${res.status})`);
      navigate('/admin/roles');
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="content-shell" style={{ maxWidth: 1100, margin: '0 auto' }}>
      <header style={{ marginBottom: 20 }}>
        <h2 style={{ fontSize: '1.8rem' }}>
          <ShieldPlus size={22} style={{ marginRight: 8, verticalAlign: 'middle' }} />
          New role
        </h2>
        <p className="subtitle">Name the role and choose which permissions it grants.</p>
      </header>

      {loadError && (
        <div className="panel-chip" style={{ background: '#fde2e2', color: '#9c1c1c', marginBottom: 16 }}>
          {loadError}
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
