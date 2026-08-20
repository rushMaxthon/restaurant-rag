import { createContext } from 'react';
import type { ToastMessage, User, UserRole } from '../types/app';

export interface AdminStoreValue {
  token: string | null;
  role: UserRole | null;
  restaurantId: string | null;
  user: User | null;
  isAuthenticated: boolean;
  toasts: ToastMessage[];
  setSession: (session: {
    token: string;
    role: UserRole;
    restaurantId: string | null;
    user: User;
  }) => void;
  logout: () => void;
  pushToast: (title: string, description: string, tone?: ToastMessage['tone']) => void;
  dismissToast: (id: number) => void;
}

export const AdminStoreContext = createContext<AdminStoreValue | null>(null);
