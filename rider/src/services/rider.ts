import type { Earnings, LocationFix, LoginResponse, Offer, RiderMe, Trip, TripAction } from '@/types/api';
import { request } from './http';

/** Every rider endpoint, typed from the backend contract. */

export function login(phone: string, password: string) {
  return request<LoginResponse>('/auth/login', { method: 'POST', body: { phone_number: phone, password } });
}

export const riderApi = (token: string) => ({
  me: () => request<RiderMe>('/rider/me', { token }),
  setOnline: (online: boolean) => request<RiderMe>('/rider/status', { method: 'POST', body: { online }, token }),
  sendLocation: (fixes: LocationFix[]) => request<void>('/rider/location', { method: 'POST', body: { fixes }, token }),
  deviceToken: (fcmToken: string, appVersion: string) =>
    request<void>('/rider/device-token', { method: 'POST', body: { token: fcmToken, app_version: appVersion }, token }),
  currentOffer: () => request<Offer | undefined>('/rider/offers/current', { token }),
  accept: (offerId: string) => request<Trip>(`/rider/offers/${offerId}/accept`, { method: 'POST', token }),
  decline: (offerId: string) => request<void>(`/rider/offers/${offerId}/decline`, { method: 'POST', token }),
  trip: () => request<Trip | undefined>('/rider/trip', { token }),
  act: (tripId: string, action: TripAction, actionId: string, otp?: string) =>
    request<Trip>(`/rider/trip/${tripId}/${action}`, {
      method: 'POST',
      body: { action_id: actionId, ...(otp ? { otp } : {}) },
      token,
    }),
  earnings: (days = 7) => request<Earnings>(`/rider/earnings?days=${days}`, { token }),
  history: (before?: string) =>
    request<Trip[]>(`/rider/trips?limit=20${before ? `&before=${encodeURIComponent(before)}` : ''}`, { token }),
});

export type RiderApi = ReturnType<typeof riderApi>;
