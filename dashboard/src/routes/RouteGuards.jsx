// Route-level guards used by App.jsx's <Routes> tree: RequireAuth gates
// everything behind a session, RequirePermission additionally gates one
// route behind a specific permission key once a session exists.

import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '../auth/useAuth.js';

export function RequireAuth() {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '100vh' }}>
        Loading...
      </div>
    );
  }
  if (!user) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }
  return <Outlet />;
}

export function RequirePermission({ permissions, children }) {
  const { hasPermission } = useAuth();
  if (!hasPermission(...permissions)) {
    return (
      <div style={{ padding: 60, textAlign: 'center' }}>
        <h2>Access denied</h2>
        <p className="subtitle">You don't have permission to view this page.</p>
      </div>
    );
  }
  return children;
}
