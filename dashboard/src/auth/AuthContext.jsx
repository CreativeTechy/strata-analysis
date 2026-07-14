import { useCallback, useEffect, useState } from 'react';
import { AuthContext, roleSatisfies } from './authContext.js';

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const res = await fetch('/api/auth/me');
      if (!res.ok) {
        setUser(null);
        return null;
      }
      const data = await res.json().catch(() => ({}));
      setUser(data?.user ?? null);
      return data?.user ?? null;
    } catch {
      setUser(null);
      return null;
    }
  }, []);

  useEffect(() => {
    (async () => {
      await refresh();
      setLoading(false);
    })();
  }, [refresh]);

  // If the global fetch interceptor sees a 401 on any API call, treat the
  // session as gone immediately rather than waiting for the next /me poll.
  useEffect(() => {
    const onUnauthorized = () => setUser(null);
    window.addEventListener('strata:unauthorized', onUnauthorized);
    return () => window.removeEventListener('strata:unauthorized', onUnauthorized);
  }, []);

  const login = useCallback(async (username, password) => {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data?.error || data?.detail || 'Login failed.');
    }
    setUser(data?.user ?? null);
    return data?.user ?? null;
  }, []);

  const logout = useCallback(async () => {
    try {
      await fetch('/api/auth/logout', { method: 'POST' });
    } finally {
      setUser(null);
    }
  }, []);

  const hasRole = useCallback((...roles) => !!user && roleSatisfies(user.role, roles), [user]);

  const value = { user, loading, login, logout, refresh, hasRole };
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
