/**
 * Which experience the visitor chose: worker or safety admin.
 *
 * This is a UI preference, NOT a security control. The brief asks for role selection rather than
 * production authentication, so the choice lives in localStorage and anyone can change it. The
 * privacy guarantee that matters is enforced server-side: the worker endpoints never return raw
 * reports, reviewer notes or unpublished hotspots, so selecting "worker" here cannot expose
 * anything a worker should not see, and selecting "admin" here grants nothing on its own.
 *
 * A real deployment would put authentication in front of `/api/admin/*`.
 */
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';

export type Role = 'worker' | 'admin' | null;

const STORAGE_KEY = 'ecosentinel.role.v1';

interface RoleValue {
  role: Role;
  setRole: (role: Role) => void;
  clearRole: () => void;
}

const RoleContext = createContext<RoleValue | null>(null);

function load(): Role {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw === 'worker' || raw === 'admin' ? raw : null;
  } catch {
    return null; // private browsing / blocked storage — the app still works, unselected
  }
}

export function RoleProvider({ children }: { children: ReactNode }) {
  const [role, setRoleState] = useState<Role>(load);

  const setRole = useCallback((next: Role) => {
    setRoleState(next);
    try {
      if (next) window.localStorage.setItem(STORAGE_KEY, next);
      else window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      /* preference is in-memory only when storage is unavailable */
    }
  }, []);

  const clearRole = useCallback(() => setRole(null), [setRole]);
  const value = useMemo(() => ({ role, setRole, clearRole }), [role, setRole, clearRole]);
  return <RoleContext.Provider value={value}>{children}</RoleContext.Provider>;
}

export function useRole() {
  const context = useContext(RoleContext);
  if (!context) throw new Error('useRole must be used inside RoleProvider');
  return context;
}
