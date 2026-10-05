import { API_BASE_URL } from '@/config/api';
import type { Page } from '@/types/app';

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = 'ApiError';
  }
}

// Status 0 marks a request that never got an answer — no network, server
// down, or the timeout below. Callers word that differently from a refusal.
export const NETWORK_ERROR_STATUS = 0;

// Kitchen Wi-Fi drops. React Native's fetch has no timeout of its own, so a
// request into a dead connection would leave a spinner up indefinitely.
const REQUEST_TIMEOUT_MS = 15000;

type Query = Record<string, string | number | null | undefined>;

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE';
  token?: string | null;
  body?: unknown;
  query?: Query;
}

// Told when the server refuses a token this app sent. The store decides
// whether that token is still the signed-in one — a slow request from a
// previous login must not sign out the account that replaced it.
type UnauthorizedListener = (token: string) => void;
const unauthorizedListeners = new Set<UnauthorizedListener>();

export const onUnauthorized = (listener: UnauthorizedListener): (() => void) => {
  unauthorizedListeners.add(listener);
  return () => {
    unauthorizedListeners.delete(listener);
  };
};

const withQuery = (path: string, query?: Query): string => {
  if (!query) {
    return path;
  }
  const parts = Object.entries(query)
    .filter(([, value]) => value !== undefined && value !== null && value !== '')
    .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`);
  return parts.length ? `${path}?${parts.join('&')}` : path;
};

// FastAPI sends `detail` as a sentence for a refusal and as a list of field
// errors for a 422. The sentence is the server's own reason — a payment that
// has not settled, a status that moved under the cook's finger — and is shown
// as written rather than paraphrased.
const detailOf = (payload: unknown): string | null => {
  const detail = (payload as { detail?: unknown } | null)?.detail;
  if (typeof detail === 'string') {
    return detail;
  }
  if (Array.isArray(detail)) {
    const messages = detail
      .map(entry => (entry as { msg?: unknown } | null)?.msg)
      .filter((msg): msg is string => typeof msg === 'string');
    return messages.length ? messages.join(' ') : null;
  }
  return null;
};

const send = async (
  path: string,
  { method = 'GET', token, body, query }: RequestOptions,
): Promise<Response> => {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${withQuery(path, query)}`, {
      method,
      headers: {
        Accept: 'application/json',
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
  } catch {
    throw new ApiError('Could not reach the server.', NETWORK_ERROR_STATUS);
  } finally {
    clearTimeout(timer);
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    if (response.status === 401 && token) {
      unauthorizedListeners.forEach(listener => listener(token));
    }
    throw new ApiError(
      detailOf(payload) ?? `Request failed (${response.status}).`,
      response.status,
    );
  }
  return response;
};

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await send(path, options);
  // 204 No Content (an unregister, say) has no body to parse.
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

// Like `request`, but keeps X-Total-Count beside the page. A live queue that
// outgrows one page must be able to say so: a board showing 200 of 260 with
// no sign of the other 60 is worse than one that admits it.
export async function requestPage<T>(
  path: string,
  options: RequestOptions = {},
): Promise<Page<T>> {
  const response = await send(path, options);
  const rows = (await response.json()) as T[];
  const header = response.headers.get('X-Total-Count');
  const total = header === null ? Number.NaN : Number(header);
  // An absent header reads as "no overflow known", not as "there are none".
  return { rows, total: Number.isFinite(total) ? total : rows.length };
}
