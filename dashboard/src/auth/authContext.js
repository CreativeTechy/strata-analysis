import { createContext } from 'react';

export const AuthContext = createContext(null);

// True if `role` is allowed to do something that requires at least one of
// `required` roles (admin always passes, matching the backend's require_role()).
export function roleSatisfies(role, required) {
  if (!required || required.length === 0) return true;
  if (role === 'admin') return true;
  return required.includes(role);
}
