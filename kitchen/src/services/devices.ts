import { request } from '@services/api';

export interface DeviceRegistration {
  installation_id: string;
  fcm_token: string;
  platform: 'IOS' | 'ANDROID';
}

// POST /notifications/device-tokens — the same endpoint the customer app
// uses. Any signed-in account may register, so a kitchen account's device is
// stored against that account and reached by the kitchen new-order push.
export const registerDevice = (token: string, device: DeviceRegistration) =>
  request<unknown>('/notifications/device-tokens', {
    method: 'POST',
    token,
    body: device,
  });

// DELETE /notifications/device-tokens/{installation_id} — stops pushes to
// this device for this account. Idempotent on the server.
export const unregisterDevice = (token: string, installationId: string) =>
  request<void>(`/notifications/device-tokens/${encodeURIComponent(installationId)}`, {
    method: 'DELETE',
    token,
  });
