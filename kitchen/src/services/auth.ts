import { request } from '@services/api';
import type { AuthResponse } from '@/types/app';

// No app bundle-id header, on purpose: the backend treats a request carrying
// one as a branded customer app, and a branded app never signs in staff.
export const login = (email: string, password: string): Promise<AuthResponse> =>
  request<AuthResponse>('/auth/login', {
    method: 'POST',
    body: { email, password },
  });
