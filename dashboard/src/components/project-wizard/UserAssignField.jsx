import { useMemo } from 'react';
import { Search, Users } from 'lucide-react';

export default function UserAssignField({ users, selectedIds, onToggle, query, onQueryChange, disabled }) {
  const visibleUsers = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return users;
    return users.filter((user) =>
      [user.username, user.email, user.role].filter(Boolean).some((value) => String(value).toLowerCase().includes(needle))
    );
  }, [users, query]);

  return (
    <div className="assign-sources-panel">
      <div className="assign-sources-header">
        <div>
          <div className="assign-sources-kicker">
            <Users size={12} style={{ verticalAlign: -1, marginRight: 4 }} /> Linked users
          </div>
          <strong className="assign-sources-title">Choose dashboard users linked to this project</strong>
        </div>
        <div className="assign-sources-summary">
          <span className="panel-chip">{selectedIds.length} selected</span>
        </div>
      </div>

      <div className="assign-sources-toolbar">
        <label className="assign-sources-search">
          <Search size={14} />
          <input
            type="text"
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            placeholder="Filter users by username, email, or role"
            disabled={disabled}
          />
        </label>
      </div>

      <div className="assign-sources-list">
        {users.length === 0 ? (
          <div style={{ color: 'var(--text-light)', fontSize: '0.85rem' }}>
            No dashboard users yet.
          </div>
        ) : visibleUsers.length === 0 ? (
          <div className="admin-empty-state" style={{ padding: '16px 10px' }}>
            <div className="admin-empty-state-icon" style={{ width: 36, height: 36 }}>
              <Search size={16} />
            </div>
            <strong>No matching users</strong>
            <span>Try a different search term in this assignment box.</span>
          </div>
        ) : (
          visibleUsers.map((user) => {
            const userId = Number(user.id);
            const isSelected = selectedIds.includes(userId);
            return (
              <label key={user.id} className={`assign-source-item ${isSelected ? 'selected' : ''}`}>
                <input
                  type="checkbox"
                  checked={isSelected}
                  onChange={() => onToggle(userId)}
                  disabled={disabled}
                />
                <div className="assign-source-copy">
                  <div className="assign-source-topline">
                    <strong className="assign-source-name project-term-name">{user.username}</strong>
                    <span className={`panel-chip role-${user.role}`}>{user.role}</span>
                  </div>
                  <div className="assign-source-url">{user.email || 'No email on file'}</div>
                </div>
              </label>
            );
          })
        )}
      </div>
    </div>
  );
}
