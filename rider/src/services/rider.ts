import type {
  ApplicationView,
  Earnings,
  PhotoKind,
  SectionKey,
  SignupCodeResponse,
  UploadFile,
  LocationFix,
  LoginResponse,
  Offer,
  OpenOrder,
  Payout,
  RiderMe,
  Trip,
  TripAction,
} from '@/types/api';
import { request, upload } from './http';

/** Every rider endpoint, typed from the backend contract. */

export function login(phone: string, password: string) {
  return request<LoginResponse>('/auth/login', {
    method: 'POST',
    body: { phone_number: phone, password },
  });
}

/** Public: asks for the sign-up code. 409 `phone_in_use` means "sign in instead". */
export function requestSignupCode(phone: string) {
  return request<SignupCodeResponse>('/rider/signup/code', {
    method: 'POST',
    body: { phone_number: phone },
  });
}

/** Public: the code, the password and the name in one go; answers like /auth/login. */
/** Is this the code? Said on the code screen; does not use the code up. */
export function checkSignupCode(phone: string, code: string) {
  return request<void>('/rider/signup/check', {
    method: 'POST',
    body: { phone_number: phone, code },
  });
}

export function signup(body: {
  phone_number: string;
  code: string;
  password: string;
  full_name: string;
}) {
  return request<LoginResponse>('/rider/signup', { method: 'POST', body });
}

/** Public, forgot password: a code to a rider's own number. 404 `no_account`. */
export function requestResetCode(phone: string) {
  return request<SignupCodeResponse>('/rider/password/code', {
    method: 'POST',
    body: { phone_number: phone },
  });
}

/** Is this the reset code? Does not use it up. */
export function checkResetCode(phone: string, code: string) {
  return request<void>('/rider/password/check', {
    method: 'POST',
    body: { phone_number: phone, code },
  });
}

/** The new password; answers like /auth/login, so the rider is signed straight in. */
export function resetPassword(body: { phone_number: string; code: string; password: string }) {
  return request<LoginResponse>('/rider/password/reset', { method: 'POST', body });
}

export const riderApi = (token: string) => ({
  me: () => request<RiderMe>('/rider/me', { token }),
  setOnline: (online: boolean) =>
    request<RiderMe>('/rider/status', {
      method: 'POST',
      body: { online },
      token,
    }),
  sendLocation: (fixes: LocationFix[]) =>
    request<void>('/rider/location', {
      method: 'POST',
      body: { fixes },
      token,
    }),
  deviceToken: (fcmToken: string, appVersion: string) =>
    request<void>('/rider/device-token', {
      method: 'POST',
      body: { token: fcmToken, app_version: appVersion },
      token,
    }),
  currentOffer: () =>
    request<Offer | undefined>('/rider/offers/current', { token }),
  accept: (offerId: string) =>
    request<Trip>(`/rider/offers/${offerId}/accept`, { method: 'POST', token }),
  decline: (offerId: string) =>
    request<void>(`/rider/offers/${offerId}/decline`, {
      method: 'POST',
      token,
    }),
  openOrders: () => request<OpenOrder[]>('/rider/open-orders', { token }),
  claim: (orderId: string) =>
    request<Trip>(`/rider/open-orders/${orderId}/claim`, {
      method: 'POST',
      token,
    }),
  trip: () => request<Trip | undefined>('/rider/trip', { token }),
  act: (tripId: string, action: TripAction, actionId: string, otp?: string) =>
    request<Trip>(`/rider/trip/${tripId}/${action}`, {
      method: 'POST',
      body: { action_id: actionId, ...(otp ? { otp } : {}) },
      token,
    }),
  earnings: (days = 7) =>
    request<Earnings>(`/rider/earnings?days=${days}`, { token }),
  payouts: () => request<Payout[]>('/rider/payouts', { token }),
  // The rider's own application (a self-signed-up rider, until approved).
  application: () => request<ApplicationView>('/rider/application', { token }),
  saveSection: (section: SectionKey, body: Record<string, unknown>) =>
    request<ApplicationView>(`/rider/application/${section}`, {
      method: 'PUT',
      body,
      token,
    }),
  uploadPhoto: (
    kind: PhotoKind,
    file: UploadFile,
    onProgress?: (fraction: number) => void,
  ) =>
    upload<ApplicationView>(
      `/rider/application/items/${kind}`,
      file,
      token,
      onProgress,
    ),
  submitApplication: () =>
    request<ApplicationView>('/rider/application/submit', {
      method: 'POST',
      token,
    }),
  history: (before?: string) =>
    request<Trip[]>(
      `/rider/trips?limit=20${
        before ? `&before=${encodeURIComponent(before)}` : ''
      }`,
      { token },
    ),
});

export type RiderApi = ReturnType<typeof riderApi>;
