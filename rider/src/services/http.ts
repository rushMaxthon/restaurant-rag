import { API_BASE_URL, REQUEST_TIMEOUT_MS } from '@/config/api';
import type { Key } from '@/i18n/strings';
import { translate } from '@/i18n/translate';
import { ONBOARDING_ERRORS } from '@utils/onboarding';
import type { UploadFile } from '@/types/api';

/**
 * One error type for every request, carrying a sentence a rider can read.
 * Screens show `message`; logic branches on `status` and `code`.
 */
export class ApiError extends Error {
  status: number;
  code: string | null;
  detail: unknown;

  constructor(
    status: number,
    message: string,
    code: string | null = null,
    detail: unknown = null,
  ) {
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
  // Refer & earn (`fleet/referral.py`)
  referral_unknown: 'referral.errUnknown',
  referral_self: 'referral.errSelf',
  referral_inactive: 'referral.errInactive',
  referral_taken: 'referral.errTaken',
  referral_closed: 'referral.errClosed',
  // Sign-up and the application: the same table the step forms use.
  ...ONBOARDING_ERRORS,
};

function sentenceFor(code: string): string | null {
  const key = Object.prototype.hasOwnProperty.call(SENTENCES, code)
    ? SENTENCES[code]
    : undefined;
  return key ? translate(key) : null;
}

export function messageFor(
  status: number,
  detail: unknown,
): { message: string; code: string | null } {
  if (typeof detail === 'string') {
    return { message: sentenceFor(detail) ?? detail, code: detail };
  }
  if (detail && typeof detail === 'object' && 'code' in detail) {
    const code = String((detail as { code: unknown }).code);
    return { message: sentenceFor(code) ?? code, code };
  }
  // A section save's 422 is {field, error}; the field is in `detail` for the
  // form to put the sentence under it.
  if (detail && typeof detail === 'object' && 'error' in detail) {
    const code = String((detail as { error: unknown }).error);
    return {
      message: sentenceFor(code) ?? translate('system.errValidation'),
      code,
    };
  }
  // Submit's 422 lists what is missing or flagged.
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    for (const code of ['missing', 'flagged']) {
      if (code in detail)
        return {
          message: sentenceFor(code) ?? translate('system.errValidation'),
          code,
        };
    }
  }
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: string };
    return {
      message: first?.msg ?? translate('system.errValidation'),
      code: 'validation',
    };
  }
  if (status === 401)
    return { message: translate('system.errAuth'), code: 'auth' };
  if (status === 403)
    return { message: translate('system.errForbidden'), code: 'forbidden' };
  if (status === 429)
    return {
      message: translate('system.errRateLimited'),
      code: 'rate_limited',
    };
  if (status >= 500)
    return { message: translate('system.errServer'), code: 'server' };
  return { message: translate('system.errGeneric'), code: null };
}

type Options = {
  method?: string;
  body?: unknown;
  token?: string | null;
  signal?: AbortSignal;
};

let onUnauthorized: ((token: string) => void) | null = null;

/** Set by the session: a 401 on the CURRENT token signs out; an older token's 401 is ignored. */
export function setUnauthorizedHandler(
  handler: ((token: string) => void) | null,
) {
  onUnauthorized = handler;
}

export async function request<T>(
  path: string,
  { method = 'GET', body, token, signal }: Options = {},
): Promise<T> {
  // The timeout covers the WHOLE answer, body included: it used to stop when
  // the headers arrived, so a body stalling on a weak cell hung for ever -
  // and a body that failed on a 200 came back as null, which reads as
  // "no trip". The caller's signal is let go of in every case.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  const onAbort = () => controller.abort();
  signal?.addEventListener('abort', onAbort);
  try {
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
    }
    if (response.status === 204) return undefined as T;
    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      if (controller.signal.aborted)
        throw new ApiError(0, translate('system.errNetwork'), 'network');
      payload = null;
    }
    if (!response.ok) {
      const detail =
        payload && typeof payload === 'object'
          ? (payload as { detail?: unknown }).detail
          : null;
      const { message, code } = messageFor(response.status, detail);
      if (response.status === 401 && token && onUnauthorized)
        onUnauthorized(token);
      throw new ApiError(response.status, message, code, detail);
    }
    return payload as T;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', onAbort);
  }
}

/**
 * A photo, as multipart `file`. XMLHttpRequest rather than fetch because
 * fetch reports no upload progress, and on a slow cell a 900 KB photo takes
 * long enough that a bar standing still reads as a hang. Errors map exactly
 * as `request` maps them.
 */
export function upload<T>(
  path: string,
  file: UploadFile,
  token: string | null,
  onProgress?: (fraction: number) => void,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${API_BASE_URL}${path}`);
    xhr.setRequestHeader('Accept', 'application/json');
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    // Photos are big and cells are slow: four times a JSON request's patience.
    xhr.timeout = REQUEST_TIMEOUT_MS * 4;
    if (onProgress && xhr.upload) {
      xhr.upload.onprogress = event => {
        if (event.lengthComputable && event.total > 0)
          onProgress(event.loaded / event.total);
      };
    }
    const network = () =>
      reject(new ApiError(0, translate('system.errNetwork'), 'network'));
    xhr.onerror = network;
    xhr.ontimeout = network;
    xhr.onload = () => {
      let payload: unknown = null;
      try {
        payload = xhr.responseText ? JSON.parse(xhr.responseText) : null;
      } catch {
        payload = null;
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(payload as T);
        return;
      }
      const detail =
        payload && typeof payload === 'object'
          ? (payload as { detail?: unknown }).detail
          : null;
      const { message, code } = messageFor(xhr.status, detail);
      if (xhr.status === 401 && token && onUnauthorized) onUnauthorized(token);
      reject(new ApiError(xhr.status, message, code, detail));
    };
    const form = new FormData();
    // React Native's FormData takes {uri, type, name} for a file on the device.
    form.append('file', file as unknown as Blob);
    xhr.send(form);
  });
}
