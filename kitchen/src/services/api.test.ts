import { ApiError, NETWORK_ERROR_STATUS, onUnauthorized, request, requestPage } from './api';

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

const respond = (status: number, body: unknown, headers: Record<string, string> = {}) => {
  globalThis.fetch = jest.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    headers: { get: (name: string) => headers[name] ?? null },
  }) as unknown as typeof fetch;
};

test('keeps the total count beside a page', async () => {
  respond(200, [{ id: 1 }], { 'X-Total-Count': '206' });
  expect(await requestPage('/orders')).toEqual({ rows: [{ id: 1 }], total: 206 });
});

test('reads a missing count as "no overflow known", not as zero', async () => {
  respond(200, [{ id: 1 }, { id: 2 }]);
  expect((await requestPage('/orders')).total).toBe(2);
});

test('drops empty query values and encodes the rest', async () => {
  respond(200, []);
  await request('/orders', { query: { a: 'x y', b: null, c: undefined, d: '' } });
  expect((globalThis.fetch as jest.Mock).mock.calls[0][0]).toMatch(/\/orders\?a=x%20y$/);
});

test('passes the server’s sentence through, and joins 422 field messages', async () => {
  respond(409, { detail: 'Invalid status transition' });
  await expect(request('/x')).rejects.toThrow('Invalid status transition');
  respond(422, { detail: [{ msg: 'Field required' }, { msg: 'Too short' }] });
  await expect(request('/x')).rejects.toThrow('Field required Too short');
});

test('marks an unreachable server with status 0', async () => {
  globalThis.fetch = jest.fn().mockRejectedValue(new TypeError('Network request failed')) as unknown as typeof fetch;
  await expect(request('/x')).rejects.toMatchObject({ status: NETWORK_ERROR_STATUS });
});

test('reports a 401 only when a token was sent, naming that token', async () => {
  const listener = jest.fn();
  const stop = onUnauthorized(listener);
  respond(401, { detail: 'no' });
  await expect(request('/auth/login')).rejects.toBeInstanceOf(ApiError);
  expect(listener).not.toHaveBeenCalled();
  await expect(request('/orders', { token: 't-1' })).rejects.toBeInstanceOf(ApiError);
  expect(listener).toHaveBeenCalledWith('t-1');
  stop();
});
