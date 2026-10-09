import { ApiError, messageFor, request, setUnauthorizedHandler } from './http';

describe('messageFor', () => {
  it('turns a backend code into a sentence for the rider', () => {
    expect(messageFor(409, 'offer_taken')).toEqual({ message: 'Another rider took this order.', code: 'offer_taken' });
  });
  it('reads a structured detail with a code', () => {
    expect(messageFor(422, { code: 'otp_wrong', attempts_left: 3 }).code).toBe('otp_wrong');
  });
  it('shows the first validation message', () => {
    expect(messageFor(422, [{ msg: 'Field required' }]).message).toBe('Field required');
  });
  it('explains an expired session', () => {
    expect(messageFor(401, null).code).toBe('auth');
  });
  it('passes through a plain sentence from the server', () => {
    expect(messageFor(400, 'Enter a valid phone number').message).toBe('Enter a valid phone number');
  });
});

describe('request and a 401', () => {
  const realFetch = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = realFetch;
    setUnauthorizedHandler(null);
  });

  const answer = (status: number, body: unknown) =>
    jest.fn().mockResolvedValue({ ok: status < 400, status, json: async () => body });

  it('signs out the token that got the 401', async () => {
    const signOut = jest.fn();
    setUnauthorizedHandler(signOut);
    globalThis.fetch = answer(401, { detail: 'Could not validate credentials' }) as never;
    await expect(request('/rider/me', { token: 'tok-1' })).rejects.toMatchObject({ status: 401 });
    expect(signOut).toHaveBeenCalledWith('tok-1');
  });

  it('does not sign anybody out for a 401 on a request with no token (a wrong password)', async () => {
    const signOut = jest.fn();
    setUnauthorizedHandler(signOut);
    globalThis.fetch = answer(401, { detail: 'Invalid credentials' }) as never;
    await expect(request('/auth/login', { method: 'POST', body: {} })).rejects.toMatchObject({ status: 401 });
    expect(signOut).not.toHaveBeenCalled();
  });

  it('reports no connection as a network error the trip queue retries', async () => {
    globalThis.fetch = jest.fn().mockRejectedValue(new TypeError('Network request failed')) as never;
    const error: ApiError = await request('/rider/me', { token: 't' }).then(
      () => { throw new Error('expected a failure'); },
      (e: ApiError) => e,
    );
    expect(error).toBeInstanceOf(ApiError);
    expect(error.isNetwork).toBe(true);
  });
});
