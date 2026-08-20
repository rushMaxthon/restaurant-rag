import type { AuthSession } from '../types/app';

const AUTH_KEY = 'restaurant-rag-admin-auth';

function isValidAdminAuth(value: AuthSession | null): value is AuthSession {
  if (!value?.token || !value.role || !value.user) {
    return false;
  }

  if (value.role !== 'ADMIN' && value.role !== 'OWNER') {
    return false;
  }

  return value.user.role === value.role;
}

export const storage = {
  readAuth(): AuthSession | null {
    const raw = window.localStorage.getItem(AUTH_KEY);
    if (!raw) {
      return null;
    }

    try {
      const parsed = JSON.parse(raw) as AuthSession;
      if (!isValidAdminAuth(parsed)) {
        window.localStorage.removeItem(AUTH_KEY);
        return null;
      }
      return parsed;
    } catch {
      window.localStorage.removeItem(AUTH_KEY);
      return null;
    }
  },
  writeAuth(value: AuthSession | null): void {
    if (!value) {
      window.localStorage.removeItem(AUTH_KEY);
      return;
    }
    window.localStorage.setItem(AUTH_KEY, JSON.stringify(value));
  },
};
