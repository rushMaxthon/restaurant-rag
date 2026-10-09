import { API_BASE_URL, REQUEST_TIMEOUT_MS } from '@/config/api';
import type { Key } from '@/i18n/strings';
import { translate } from '@/i18n/translate';

/**
 * One error type for every request, carrying a sentence a rider can read.
 * Screens show `message`; logic branches on `status` and `code`.
 */
export class ApiError extends Error {
  status: number;
  code: string | null;
  detail: unknown;

  constructor(status: number, message: string, code: string | null = null, detail: unknown = null) {
    super(message);
    this.status = status;
    this.code = code;
    this.detail = detail;
  }

  get isNetwork() {
    return this.status === 0;
  }
}

/**
 * Backend codes the app reacts to, in words for the rider. Keys rather than
 * sentences, translated when the error is made, so a language switch applies.
 * A detail the server wrote itself is shown as it came.
 */
const SENTENCES: Record<string, Key> = {
  offer_taken: 'system.errOfferTaken',
  offer_expired: 'system.errOfferExpired',
  out_of_order: 'system.errOutOfOrder',
  otp_locked: 'system.errOtpLocked',
  too_early: 'system.errTooEarly',
  on_trip: 'system.errOnTrip',
  trip_ended: 'system.errTripEnded',
};

function sentenceFor(code: string): string | null {
  const key = Object.prototype.hasOwnProperty.call(SENTENCES, code) ? SENTENCES[code] : undefined;
  return key ? translate(key) : null;
}

export function messageFor(status: number, detail: unknown): { message: string; code: string | null } {
  if (typeof detail === 'string') {
    return { message: sentenceFor(detail) ?? detail, code: detail };
  }
  if (detail && typeof detail === 'object' && 'code' in detail) {
    const code = String((detail as { code: unknown }).code);
    return { message: sentenceFor(code) ?? code, code };
  }
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: string };
    return { message: first?.msg ?? translate('system.errValidation'), code: 'validation' };
  }
  if (status === 401) return { message: translate('system.errAuth'), code: 'auth' };
  if (status === 403) return { message: translate('system.errForbidden'), code: 'forbidden' };
  if (status === 429) return { message: translate('system.errRateLimited'), code: 'rate_limited' };
  if (status >= 500) return { message: translate('system.errServer'), code: 'server' };
  return { message: translate('system.errGeneric'), code: null };
}

type Options = { method?: string; body?: unknown; token?: string | null; signal?: AbortSignal };

let onUnauthorized: ((token: string) => void) | null = null;

/** Set by the session: a 401 on the CURRENT token signs out; an older token's 401 is ignored. */
export function setUnauthorizedHandler(handler: ((token: string) => void) | null) {
  onUnauthorized = handler;
}

export async function request<T>(path: string, { method = 'GET', body, token, signal }: Options = {}): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  signal?.addEventListener('abort', () => controller.abort());
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers: {
        Accept: 'application/json',
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
  } catch {
    throw new ApiError(0, translate('system.errNetwork'), 'network');
  } finally {
    clearTimeout(timer);
  }
  if (response.status === 204) return undefined as T;
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const detail = payload && typeof payload === 'object' ? (payload as { detail?: unknown }).detail : null;
    const { message, code } = messageFor(response.status, detail);
    if (response.status === 401 && token && onUnauthorized) onUnauthorized(token);
    throw new ApiError(response.status, message, code, detail);
  }
  return payload as T;
}
