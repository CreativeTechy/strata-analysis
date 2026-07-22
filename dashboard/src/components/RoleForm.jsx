import { useEffect, useMemo, useRef } from 'react';
import '../styles/AdminUsers.css';

const CATEGORY_LABELS = {
  articles: 'Articles',
  pipeline: 'Pipeline',
  projects: 'Projects',
  roles: 'Roles',
  sources: 'Sources',
  users: 'Users',
};

const CATEGORY_ORDER = Object.keys(CATEGORY_LABELS);

function categoryLabel(resource) {
  return CATEGORY_LABELS[resource] || resource.charAt(0).toUpperCase() + resource.slice(1);
}

// Prefer the permission's own description (already human-readable, no
// category prefix); fall back to deriving one from the key if it's missing.
function permissionLabel(perm) {
  if (perm.description) return perm.description;
  const label = perm.key.split('.').slice(1).join(' ').replace(/_/g, ' ');
  return label.charAt(0).toUpperCase() + label.slice(1);
}

function groupPermissions(permissions) {
  const groups = {};
  for (const perm of permissions) {
    const [resource] = perm.key.split('.');
    if (!groups[resource]) groups[resource] = [];
    groups[resource].push(perm);
  }
  const rest = Object.keys(groups)
    .filter((resource) => !CATEGORY_ORDER.includes(resource))
    .sort();
  return [...CATEGORY_ORDER, ...rest].filter((resource) => groups[resource]).map((resource) => ({
    resource,
    perms: groups[resource],
  }));
}

function GroupSelectAll({ perms, selected, onToggleGroup }) {
  const checkboxRef = useRef(null);
  const checkedCount = perms.filter((perm) => selected.has(perm.key)).length;
  const allChecked = checkedCount === perms.length;
  const someChecked = checkedCount > 0 && !allChecked;

  useEffect(() => {
    if (checkboxRef.current) checkboxRef.current.indeterminate = someChecked;
  }, [someChecked]);

  return (
    <label className="permission-group-toggle">
      <input
        ref={checkboxRef}
        type="checkbox"
        checked={allChecked}
        onChange={() => onToggleGroup(perms, !allChecked)}
      />
      {allChecked ? 'Deselect all' : 'Select all'}
    </label>
  );
}

function PermissionGrid({ permissions, selected, onToggle, onToggleGroup }) {
  const groups = useMemo(() => groupPermissions(permissions), [permissions]);
  return (
    <div className="permission-groups">
      {groups.map(({ resource, perms }) => (
        <div key={resource} className="permission-group-card">
          <div className="permission-group-header">
            <span className="permission-group-title">{categoryLabel(resource)}</span>
            <GroupSelectAll perms={perms} selected={selected} onToggleGroup={onToggleGroup} />
          </div>
          <div className="permission-group-body">
            {perms.map((perm) => (
              <label key={perm.key} className="permission-row" title={perm.key}>
                <input type="checkbox" checked={selected.has(perm.key)} onChange={() => onToggle(perm.key)} />
                {permissionLabel(perm)}
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

  const toggleGroup = (perms, shouldSelect) => {
    const next = new Set(value.permissions);
    for (const perm of perms) {
      if (shouldSelect) next.add(perm.key);
      else next.delete(perm.key);
    }
    onChange({ ...value, permissions: Array.from(next) });
  };

  const nameValid = value.name.trim().length > 0;

  return (
    <form onSubmit={onSubmit} className="glass-card role-form">
      {error && (
        <div className="panel-chip" style={{ background: '#fde2e2', color: '#9c1c1c' }}>
          {error}
        </div>
      )}

      <div className="role-fields">
        <label className="role-field">
          <span className="role-field-label">Role name</span>
          <input
            className="filter-select"
            value={value.name}
            onChange={(e) => onChange({ ...value, name: e.target.value })}
            placeholder="e.g. Content Reviewer"
            required
          />
        </label>
        <label className="role-field">
          <span className="role-field-label">Description</span>
          <textarea
            className="filter-select role-textarea"
            value={value.description}
            onChange={(e) => onChange({ ...value, description: e.target.value })}
            placeholder="What is this role for?"
            rows={3}
          />
        </label>
      </div>

      {fullAccess ? (
        <p className="subtitle">This role automatically has every permission and can't be restricted.</p>
      ) : (
        <div className="role-permissions">
          <span className="role-field-label">Permissions</span>
          <PermissionGrid
            permissions={permissions}
            selected={new Set(value.permissions)}
            onToggle={togglePermission}
            onToggleGroup={toggleGroup}
          />
        </div>
      )}

      <div className="role-form-actions">
        <button type="button" className="btn-secondary" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="btn-primary" disabled={submitting || !nameValid}>
          {submitting ? 'Saving...' : submitLabel}
        </button>
      </div>
    </form>
  );
}
