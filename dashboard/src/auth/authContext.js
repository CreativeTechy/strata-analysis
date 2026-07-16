import { createContext } from 'react';

export const AuthContext = createContext(null);

// True if `permissions` (the user's granted permission keys) includes every
// entry in `required`. Mirrors the backend's require_permission().
export function permissionsSatisfy(permissions, required) {
  if (!required || required.length === 0) return true;
  const granted = new Set(permissions || []);
  return required.every((perm) => granted.has(perm));
}
