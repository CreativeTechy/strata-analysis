import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { ShieldCheck, ShieldPlus, Trash2, Pencil } from 'lucide-react';
import ConfirmModal from './ConfirmModal';
import { useAuth } from '../auth/useAuth.js';
import { listRoles, deleteRole } from '../api/adminApi.js';
import { formatNumber } from '../lib/i18nFormat.js';
import '../styles/AdminUsers.css';

// List-only: the entry point for role administration. Create/edit happen on
// their own routed pages (RoleCreatePage/RoleEditPage); this page never
// renders a form itself.
export default function RolesListPage() {
  const { t, i18n } = useTranslation(['admin', 'common']);
  const { hasPermission } = useAuth();
  const canCreate = hasPermission('roles.create');
  const canUpdate = hasPermission('roles.update');
  const canDelete = hasPermission('roles.delete');

  const [roles, setRoles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleting, setDeleting] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const data = await listRoles();
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
      await deleteRole(target.id);
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
    <div className="admin-page-shell">
      <div className="admin-page-header">
        <div>
          <div className="admin-page-kicker">
            <ShieldCheck size={14} /> {t('kickers.accessControl')}
          </div>
          <h1 className="admin-page-title">{t('roles.title')}</h1>
          <p className="admin-page-subtitle">{t('roles.subtitle')}</p>
        </div>
        <div className="admin-page-toolbar">
          <div className="admin-page-toolbar-meta">
            <span>{t('roles.totalRoles')}</span>
            <strong>{formatNumber(roles.length, i18n.language)}</strong>
          </div>
          {canCreate && (
            <Link to="/admin/roles/new" className="btn-primary" style={{ textDecoration: 'none' }}>
              <ShieldPlus size={16} /> {t('roles.newRole')}
            </Link>
          )}
        </div>
      </div>

      {error && (
        <div className="panel-chip" style={{ background: '#fde2e2', color: '#9c1c1c', marginBottom: 16 }} dir="auto">
          {error}
        </div>
      )}

      <div className="glass-card" style={{ padding: 0, overflow: 'hidden' }}>
        <div className="table-scroll">
          <table>
            <thead>
              <tr style={{ textAlign: 'left', background: 'rgba(0,0,0,0.03)' }}>
                <th style={{ padding: 12 }}>{t('roles.fields.role')}</th>
                <th className="admin-table-col-optional" style={{ padding: 12 }}>{t('roles.fields.description')}</th>
                <th style={{ padding: 12 }}>{t('roles.fields.permissions')}</th>
                <th style={{ padding: 12 }}>{t('roles.fields.actions')}</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr>
                  <td colSpan={4} style={{ padding: 16 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: 'var(--text-light)' }}>
                      <div className="loading-spinner" /> {t('roles.table.loading')}
                    </div>
                  </td>
                </tr>
              )}
              {!loading && roles.length === 0 && (
                <tr>
                  <td colSpan={4} style={{ padding: 0 }}>
                    <div className="admin-empty-state">
                      <div className="admin-empty-state-icon">
                        <ShieldCheck size={18} />
                      </div>
                      <strong>{t('roles.table.emptyTitle')}</strong>
                      <span>
                        {canCreate ? t('roles.table.emptyBodyCanCreate') : t('roles.table.emptyBodyReadOnly')}
                      </span>
                    </div>
                  </td>
                </tr>
              )}
              {!loading && roles.map((role) => (
                <tr key={role.id} style={{ borderTop: '1px solid rgba(0,0,0,0.06)' }}>
                  <td style={{ padding: 12 }}>
                    <strong dir="auto">{role.name}</strong>
                    {role.is_system && <span className="panel-chip" style={{ marginLeft: 8 }}>{t('roles.table.systemBadge')}</span>}
                  </td>
                  <td className="admin-table-col-optional" style={{ padding: 12 }} dir="auto">{role.description || '-'}</td>
                  <td style={{ padding: 12 }}>
                    {role.full_access ? (
                      <span className="panel-chip">{t('roles.table.fullAccess')}</span>
                    ) : (
                      t('roles.table.permissionCount', { count: role.permissions?.length || 0 })
                    )}
                  </td>
                  <td style={{ padding: 12 }}>
                    {(canUpdate || canDelete) ? (
                      <div className="admin-row-actions">
                        {canUpdate && (
                          <Link
                            className="btn-secondary"
                            to={`/admin/roles/${role.id}/edit`}
                            style={{ padding: '8px 10px', fontSize: '0.8rem', textDecoration: 'none' }}
                          >
                            <Pencil size={14} /> {t('roles.rowActions.edit')}
                          </Link>
                        )}
                        {canDelete && (
                          <button
                            className="btn-secondary"
                            disabled={role.is_system}
                            title={role.is_system ? t('roles.rowActions.systemCannotDelete') : undefined}
                            onClick={() => setDeleteTarget(role)}
                            style={{ padding: '8px 10px', fontSize: '0.8rem', color: role.is_system ? undefined : '#ff4757' }}
                          >
                            <Trash2 size={14} /> {t('common:actions.delete')}
                          </button>
                        )}
                      </div>
                    ) : (
                      <span className="subtitle">{t('roles.table.viewOnly')}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <ConfirmModal
        open={Boolean(deleteTarget)}
        title={t('roles.deleteModal.title', { name: deleteTarget?.name || '' })}
        message={t('roles.deleteModal.message')}
        confirmLabel={deleting ? t('roles.deleteModal.deleting') : t('roles.deleteModal.confirmLabel')}
        cancelLabel={t('roles.deleteModal.cancelLabel')}
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
