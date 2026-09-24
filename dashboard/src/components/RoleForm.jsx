import { useEffect, useMemo, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import '../styles/AdminUsers.css';

// Resource identifiers a permission key's prefix can take - these are
// literal backend-checked strings (see backend/schema.sql's permission
// catalogue), never translated. Only their display label (looked up via
// t('roleForm.categories.<resource>')) is.
const CATEGORY_ORDER = ['articles', 'pipeline', 'projects', 'roles', 'sources', 'users'];

function categoryLabel(resource, t) {
  const translated = t(`roleForm.categories.${resource}`, { defaultValue: '' });
  if (translated) return translated;
  return resource.charAt(0).toUpperCase() + resource.slice(1);
}

// Prefer a translated label keyed on the permission's own key (never
// translated itself - see roleForm.permissionLabels.<resource>.<action> in
// admin.json), then the permission's own description from the API (already
// human-readable, no category prefix), then fall back to deriving one from
// the key if both are missing (e.g. a permission added to the backend
// before its translation catalogue entry).
function permissionLabel(perm, t) {
  const [resource, ...rest] = perm.key.split('.');
  const action = rest.join('.');
  const translated = t(`roleForm.permissionLabels.${resource}.${action}`, { defaultValue: '' });
  if (translated) return translated;
  if (perm.description) return perm.description;
  const label = rest.join(' ').replace(/_/g, ' ');
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

function GroupSelectAll({ perms, selected, onToggleGroup, t }) {
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
      {allChecked ? t('roleForm.deselectAll') : t('common:actions.selectAll')}
    </label>
  );
}

function PermissionGrid({ permissions, selected, onToggle, onToggleGroup, t }) {
  const groups = useMemo(() => groupPermissions(permissions), [permissions]);
  return (
    <div className="permission-groups">
      {groups.map(({ resource, perms }) => (
        <div key={resource} className="permission-group-card">
          <div className="permission-group-header">
            <span className="permission-group-title">{categoryLabel(resource, t)}</span>
            <GroupSelectAll perms={perms} selected={selected} onToggleGroup={onToggleGroup} t={t} />
          </div>
          <div className="permission-group-body">
            {perms.map((perm) => (
              <label key={perm.key} className="permission-row" title={perm.key}>
                <input type="checkbox" checked={selected.has(perm.key)} onChange={() => onToggle(perm.key)} />
                {permissionLabel(perm, t)}
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
  const { t } = useTranslation(['admin', 'common']);
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
        <div className="panel-chip" style={{ background: '#fde2e2', color: '#9c1c1c' }} dir="auto">
          {error}
        </div>
      )}

      <div className="role-fields">
        <label className="role-field">
          <span className="role-field-label">{t('roleForm.fields.name')}</span>
          <input
            className="filter-select"
            value={value.name}
            onChange={(e) => onChange({ ...value, name: e.target.value })}
            placeholder={t('roleForm.fields.namePlaceholder')}
            required
          />
        </label>
        <label className="role-field">
          <span className="role-field-label">{t('roleForm.fields.description')}</span>
          <textarea
            className="filter-select role-textarea"
            value={value.description}
            onChange={(e) => onChange({ ...value, description: e.target.value })}
            placeholder={t('roleForm.fields.descriptionPlaceholder')}
            rows={3}
          />
        </label>
      </div>

      {fullAccess ? (
        <p className="subtitle">{t('roleForm.fullAccessNotice')}</p>
      ) : (
        <div className="role-permissions">
          <span className="role-field-label">{t('roleForm.fields.permissions')}</span>
          <PermissionGrid
            permissions={permissions}
            selected={new Set(value.permissions)}
            onToggle={togglePermission}
            onToggleGroup={toggleGroup}
            t={t}
          />
        </div>
      )}

      <div className="role-form-actions">
        <button type="button" className="btn-secondary" onClick={onCancel}>
          {t('common:actions.cancel')}
        </button>
        <button type="submit" className="btn-primary" disabled={submitting || !nameValid}>
          {submitting ? t('roleForm.saving') : submitLabel}
        </button>
      </div>
    </form>
  );
}
