// Pins every request this app makes to the backend's contract, as the API's
// OpenAPI spec states it: path, method, query names, body and headers. A
// rename on either side fails here instead of on a kitchen wall.
import { API_BASE_URL } from '@/config/api';
import { login } from './auth';
import { advanceOrder, fetchCompletedOrders, fetchOrder, fetchOrdersByStatus } from './orders';
import { fetchRestaurant } from './restaurants';

const realFetch = globalThis.fetch;
let calls: { url: string; init: RequestInit }[] = [];

beforeEach(() => {
  calls = [];
  globalThis.fetch = jest.fn(async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    return {
      ok: true,
      status: 200,
      json: async () => (url.includes('/restaurants/') ? { id: 'r', name: 'R', locations: [] } : []),
      headers: { get: () => '0' },
    };
  }) as unknown as typeof fetch;
});
afterEach(() => {
  globalThis.fetch = realFetch;
});

const last = () => {
  const { url, init } = calls[calls.length - 1];
  const [path, query = ''] = url.replace(API_BASE_URL, '').split('?');
  return {
    path,
    params: Object.fromEntries(new URLSearchParams(query)),
    method: init.method,
    body: init.body ? JSON.parse(String(init.body)) : undefined,
    headers: init.headers as Record<string, string>,
  };
};

const scope = { restaurantId: 'r-1', locationId: 'l-1' };

test('login: POST /auth/login {email, password}, no token, no app identity headers', async () => {
  await login('cook@example.com', 'password123').catch(() => undefined);
  const call = last();
  expect(call).toMatchObject({ path: '/auth/login', method: 'POST' });
  expect(call.body).toEqual({ email: 'cook@example.com', password: 'password123' });
  // A bundle id would make the backend treat this as a branded customer app,
  // which never signs in staff.
  for (const header of ['Authorization', 'X-App-Bundle-Id', 'X-App-Platform', 'X-Forwarded-Host']) {
    expect(call.headers).not.toHaveProperty(header);
  }
});

test('board column: GET /orders with the live-window query', async () => {
  await fetchOrdersByStatus('tok', 'PREPARING', scope, '2026-10-04T12:00:00.000Z');
  const call = last();
  expect(call).toMatchObject({ path: '/orders', method: 'GET' });
  expect(call.params).toEqual({
    order_status: 'PREPARING',
    restaurant_id: 'r-1',
    restaurant_location_id: 'l-1',
    due_from: '2026-10-04T12:00:00.000Z',
    limit: '200',
    sort: 'placed_at:desc',
  });
  expect(call.headers.Authorization).toBe('Bearer tok');
});

test('board column for all branches omits the location rather than sending "null"', async () => {
  await fetchOrdersByStatus('tok', 'PLACED', { restaurantId: 'r-1', locationId: null }, 'x');
  expect(last().params).not.toHaveProperty('restaurant_location_id');
});

test('completed orders: today, then a search across all dates', async () => {
  await fetchCompletedOrders('tok', { scope, completedFrom: '2026-10-05T00:00:00.000Z', limit: 20, offset: 40 });
  expect(last().params).toEqual({
    order_status: 'DELIVERED',
    restaurant_id: 'r-1',
    restaurant_location_id: 'l-1',
    completed_from: '2026-10-05T00:00:00.000Z',
    sort: 'completed_at:desc',
    limit: '20',
    offset: '40',
  });

  await fetchCompletedOrders('tok', { scope, search: '3f2a', limit: 20, offset: 0 });
  expect(last().params).toMatchObject({ search: '3f2a', offset: '0' });
  expect(last().params).not.toHaveProperty('completed_from');
});

test('one order: GET /orders/{id}, scoped by the token alone', async () => {
  await fetchOrder('tok', 'abc-123');
  expect(last()).toMatchObject({ path: '/orders/abc-123', method: 'GET', params: {} });
});

test('advance: PATCH /orders/{id}/status {status}, restaurant_id as the only query', async () => {
  await advanceOrder('tok', 'abc-123', 'ACCEPTED', scope);
  const call = last();
  expect(call).toMatchObject({ path: '/orders/abc-123/status', method: 'PATCH' });
  expect(call.body).toEqual({ status: 'ACCEPTED' });
  expect(call.params).toEqual({ restaurant_id: 'r-1' });
  expect(call.headers['Content-Type']).toBe('application/json');
});

test('restaurant: GET /restaurants/{id} WITHOUT a token — a KITCHEN token is refused 403', async () => {
  await fetchRestaurant('r-1');
  const call = last();
  expect(call).toMatchObject({ path: '/restaurants/r-1', method: 'GET' });
  expect(call.headers.Authorization).toBeUndefined();
});
