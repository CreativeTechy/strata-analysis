import { useMemo } from 'react';

function groupPermissions(permissions) {
  const groups = {};
  for (const perm of permissions) {
    const [resource] = perm.key.split('.');
    if (!groups[resource]) groups[resource] = [];
    groups[resource].push(perm);
  }
  return groups;
}

function PermissionGrid({ permissions, selected, onToggle }) {
  const groups = useMemo(() => groupPermissions(permissions), [permissions]);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {Object.entries(groups).map(([resource, perms]) => (
        <div key={resource}>
          <div style={{ fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.05em', opacity: 0.6, marginBottom: 6 }}>
            {resource}
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
            {perms.map((perm) => (
              <label key={perm.key} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.85rem' }}>
                <input type="checkbox" checked={selected.has(perm.key)} onChange={() => onToggle(perm.key)} />
                {perm.key}
              </label>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

// Shared by RoleCreatePage and RoleEditPage: name/description fields plus the
// permission checkbox grid. The caller owns `value` and persistence - this
// component only renders the fields and reports changes.
export default function RoleForm({
  value,
  onChange,
  permissions,
  fullAccess = false,
  submitLabel,
  submitting = false,
  error = '',
  onSubmit,
  onCancel,
}) {
  const togglePermission = (key) => {
    const next = new Set(value.permissions);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    onChange({ ...value, permissions: Array.from(next) });
  };

  return (
    <form onSubmit={onSubmit} className="glass-card" style={{ padding: 32, display: 'flex', flexDirection: 'column', gap: 20 }}>
      {error && (
        <div className="panel-chip" style={{ background: '#fde2e2', color: '#9c1c1c' }}>
          {error}
        </div>
      )}

      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span style={{ fontSize: '0.8rem' }}>Role name</span>
          <input
            className="filter-select"
            value={value.name}
            onChange={(e) => onChange({ ...value, name: e.target.value })}
            required
          />
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1, minWidth: 240 }}>
          <span style={{ fontSize: '0.8rem' }}>Description</span>
          <input
            className="filter-select"
            value={value.description}
            onChange={(e) => onChange({ ...value, description: e.target.value })}
          />
        </label>
      </div>

      {fullAccess ? (
        <p className="subtitle">This role automatically has every permission and can't be restricted.</p>
      ) : (
        <PermissionGrid permissions={permissions} selected={new Set(value.permissions)} onToggle={togglePermission} />
      )}

      <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
        <button type="button" className="btn-secondary" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="btn-primary" disabled={submitting}>
          {submitting ? 'Saving...' : submitLabel}
        </button>
      </div>
    </form>
  );
}
