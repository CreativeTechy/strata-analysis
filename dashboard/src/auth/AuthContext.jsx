import { useCallback, useEffect, useState } from 'react';
import { AuthContext, permissionsSatisfy } from './authContext.js';
import { getCurrentUser, login as loginRequest, logout as logoutRequest } from '../api/authApi.js';

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    const currentUser = await getCurrentUser();
    setUser(currentUser);
    return currentUser;
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
    const loggedInUser = await loginRequest(username, password);
    setUser(loggedInUser);
    return loggedInUser;
  }, []);

  const logout = useCallback(async () => {
    try {
      await logoutRequest();
    } finally {
      setUser(null);
    }
  }, []);

  const hasPermission = useCallback((...perms) => !!user && permissionsSatisfy(user.permissions, perms), [user]);

  const value = { user, loading, login, logout, refresh, hasPermission };
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
