import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { UserPlus, Users as UsersIcon, Ban, CheckCircle2, Trash2 } from 'lucide-react';
import { useAuth } from '../auth/useAuth.js';
import ConfirmModal from './ConfirmModal';
import {
  listUsers as apiListUsers, createUser as apiCreateUser, updateUser, deleteUser, listRoles,
} from '../api/adminApi.js';
import { formatNumber } from '../lib/i18nFormat.js';
import '../styles/AdminUsers.css';

const emptyDraft = { username: '', email: '', password: '', role: '' };

export default function UsersPage() {
  const { t, i18n } = useTranslation(['admin', 'common']);
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
      const data = await apiListUsers();
      setUsers(Array.isArray(data?.users) ? data.users : []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const loadRoles = async () => {
    try {
      const data = await listRoles();
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
      await apiCreateUser(draft);
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
      await updateUser(userId, { status });
      await loadUsers();
    } catch (err) {
      setError(err.message);
    }
  };

  const setRole = async (userId, role) => {
    setError('');
    try {
      await updateUser(userId, { role });
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
      await deleteUser(target.id);
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
            <UsersIcon size={14} /> {t('kickers.userManagement')}
          </div>
          <h1 className="admin-page-title">{t('users.title')}</h1>
          <p className="admin-page-subtitle">{t('users.subtitle')}</p>
        </div>
        <div className="admin-page-toolbar">
          <div className="admin-page-toolbar-meta">
            <span>{t('users.totalUsers')}</span>
            <strong>{formatNumber(users.length, i18n.language)}</strong>
          </div>
        </div>
      </div>

      {error && (
        <div className="panel-chip" style={{ background: '#fde2e2', color: '#9c1c1c', marginBottom: 16 }} dir="auto">
          {error}
        </div>
      )}

      <form onSubmit={createUser} className="glass-card user-create-form" style={{ marginBottom: 24 }}>
        <label className="user-create-field">
          <span style={{ fontSize: '0.8rem' }}>{t('users.fields.username')}</span>
          <input className="filter-select" value={draft.username} onChange={(e) => setDraft({ ...draft, username: e.target.value })} required />
        </label>
        <label className="user-create-field">
          <span style={{ fontSize: '0.8rem' }}>{t('users.fields.email')}</span>
          <input className="filter-select" type="email" dir="ltr" value={draft.email} onChange={(e) => setDraft({ ...draft, email: e.target.value })} />
        </label>
        <label className="user-create-field">
          <span style={{ fontSize: '0.8rem' }}>{t('users.fields.password')}</span>
          <input className="filter-select" type="password" value={draft.password} onChange={(e) => setDraft({ ...draft, password: e.target.value })} minLength={8} required />
        </label>
        <label className="user-create-field">
          <span style={{ fontSize: '0.8rem' }}>{t('users.fields.role')}</span>
          <select className="filter-select" value={draft.role} onChange={(e) => setDraft({ ...draft, role: e.target.value })}>
            {roles.map((role) => <option key={role.id} value={role.name}>{role.name}</option>)}
          </select>
        </label>
        <button type="submit" className="btn-primary" disabled={creating}>
          <UserPlus size={16} /> {creating ? t('users.form.creating') : t('users.form.createButton')}
        </button>
      </form>

      <div className="glass-card" style={{ padding: 0, overflow: 'hidden' }}>
        <div className="table-scroll">
          <table>
            <thead>
              <tr style={{ textAlign: 'left', background: 'rgba(0,0,0,0.03)' }}>
                <th style={{ padding: 12 }}>{t('users.fields.username')}</th>
                <th className="admin-table-col-optional" style={{ padding: 12 }}>{t('users.fields.email')}</th>
                <th style={{ padding: 12 }}>{t('users.fields.role')}</th>
                <th style={{ padding: 12 }}>{t('users.fields.status')}</th>
                <th style={{ padding: 12 }}>{t('users.fields.actions')}</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr>
                  <td colSpan={5} style={{ padding: 16 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: 'var(--text-light)' }}>
                      <div className="loading-spinner" /> {t('users.table.loading')}
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
                      <strong>{t('users.table.emptyTitle')}</strong>
                      <span>{t('users.table.emptyBody')}</span>
                    </div>
                  </td>
                </tr>
              )}
              {users.map((u) => {
                const isSelf = currentUser && Number(currentUser.id) === Number(u.id);
                return (
                  <tr key={u.id} style={{ borderTop: '1px solid rgba(0,0,0,0.06)' }}>
                    <td style={{ padding: 12 }}>
                      <span dir="auto">{u.username}</span>{isSelf && t('users.table.youSuffix')}
                    </td>
                    <td className="admin-table-col-optional" style={{ padding: 12 }}>
                      {u.email ? <span dir="ltr">{u.email}</span> : '-'}
                    </td>
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
                            <Ban size={14} /> {t('users.actions.disable')}
                          </button>
                        ) : (
                          <button className="btn-secondary" onClick={() => setStatus(u.id, 'active')}>
                            <CheckCircle2 size={14} /> {t('users.actions.enable')}
                          </button>
                        )}
                        {canDelete && (
                          <button
                            className="btn-secondary"
                            disabled={isSelf}
                            title={isSelf ? t('users.actions.cannotDeleteSelf') : undefined}
                            onClick={() => setDeleteTarget(u)}
                            style={{ color: isSelf ? undefined : '#ff4757' }}
                          >
                            <Trash2 size={14} /> {t('common:actions.delete')}
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
        title={t('users.deleteModal.title', { username: deleteTarget?.username || '' })}
        message={t('users.deleteModal.message')}
        confirmLabel={deleting ? t('users.deleteModal.deleting') : t('users.deleteModal.confirmLabel')}
        cancelLabel={t('users.deleteModal.cancelLabel')}
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
