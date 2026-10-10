import { ApiError, messageFor, request, setUnauthorizedHandler } from './http';

describe('messageFor', () => {
  it('turns a backend code into a sentence for the rider', () => {
    expect(messageFor(409, 'offer_taken')).toEqual({
      message: 'Another rider took this order.',
      code: 'offer_taken',
    });
  });
  it('reads a structured detail with a code', () => {
    expect(messageFor(422, { code: 'otp_wrong', attempts_left: 3 }).code).toBe(
      'otp_wrong',
    );
  });
  it('shows the first validation message', () => {
    expect(messageFor(422, [{ msg: 'Field required' }]).message).toBe(
      'Field required',
    );
  });
  it('explains an expired session', () => {
    expect(messageFor(401, null).code).toBe('auth');
  });
  it('reads a section 422 by its error code', () => {
    expect(messageFor(422, { field: 'ifsc', error: 'bad_ifsc' })).toEqual({
      message: 'An IFSC looks like SBIN0001234.',
      code: 'bad_ifsc',
    });
  });
  it('reads what a refused submit is missing', () => {
    expect(messageFor(422, { missing: ['PAN'] }).code).toBe('missing');
    expect(messageFor(422, { flagged: ['PAN'] }).code).toBe('flagged');
  });
  it('says sign-up codes in words', () => {
    expect(messageFor(409, 'phone_in_use').message).toBe(
      'This number already has an account.',
    );
  });
  it('passes through a plain sentence from the server', () => {
    expect(messageFor(400, 'Enter a valid phone number').message).toBe(
      'Enter a valid phone number',
    );
  });
});

describe('request and a 401', () => {
  const realFetch = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = realFetch;
    setUnauthorizedHandler(null);
  });

  const answer = (status: number, body: unknown) =>
    jest
      .fn()
      .mockResolvedValue({ ok: status < 400, status, json: async () => body });

  it('signs out the token that got the 401', async () => {
    const signOut = jest.fn();
    setUnauthorizedHandler(signOut);
    globalThis.fetch = answer(401, {
      detail: 'Could not validate credentials',
    }) as never;
    await expect(
      request('/rider/me', { token: 'tok-1' }),
    ).rejects.toMatchObject({ status: 401 });
    expect(signOut).toHaveBeenCalledWith('tok-1');
  });

  it('does not sign anybody out for a 401 on a request with no token (a wrong password)', async () => {
    const signOut = jest.fn();
    setUnauthorizedHandler(signOut);
    globalThis.fetch = answer(401, { detail: 'Invalid credentials' }) as never;
    await expect(
      request('/auth/login', { method: 'POST', body: {} }),
    ).rejects.toMatchObject({ status: 401 });
    expect(signOut).not.toHaveBeenCalled();
  });

  it('reports no connection as a network error the trip queue retries', async () => {
    globalThis.fetch = jest
      .fn()
      .mockRejectedValue(new TypeError('Network request failed')) as never;
    const error: ApiError = await request('/rider/me', { token: 't' }).then(
      () => {
        throw new Error('expected a failure');
      },
      (e: ApiError) => e,
    );
    expect(error).toBeInstanceOf(ApiError);
    expect(error.isNetwork).toBe(true);
  });
});

describe('request and a body that never arrives', () => {
  const realFetch = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = realFetch;
    jest.useRealTimers();
  });

  it('gives up after the timeout as a network error, never as an empty answer', async () => {
    jest.useFakeTimers();
    // Headers came; the body stalls until the request is aborted.
    globalThis.fetch = jest.fn((_url: string, init: { signal: AbortSignal }) =>
      Promise.resolve({
        ok: true,
        status: 200,
        json: () =>
          new Promise((_, reject) =>
            init.signal.addEventListener('abort', () =>
              reject(new Error('aborted')),
            ),
          ),
      }),
    ) as never;
    const pending = request('/rider/trip', { token: 'tok-1' });
    const outcome = expect(pending).rejects.toMatchObject({ status: 0 });
    await Promise.resolve();
    jest.advanceTimersByTime(16_000);
    await outcome;
  });

  it('stops listening to the caller signal once done', async () => {
    const caller = new AbortController();
    const remove = jest.spyOn(caller.signal, 'removeEventListener');
    globalThis.fetch = jest
      .fn()
      .mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ a: 1 }),
      }) as never;
    await expect(request('/x', { signal: caller.signal })).resolves.toEqual({
      a: 1,
    });
    expect(remove).toHaveBeenCalledWith('abort', expect.any(Function));
  });
});
