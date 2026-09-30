/**
 * Marketing consent on mobile, as a contract.
 *
 * The screen this backs used to be a lie: "Promotions" was local `useState`
 * with nothing behind it, so a customer could switch it off, believe they had
 * opted out, and keep receiving campaigns. These pin the parts that make it
 * true:
 *
 * * it is its own endpoint, never folded into `/preferences/me` — that payload
 *   replaces every column it is given, so a screen that never showed the toggle
 *   could otherwise rewrite a legal record;
 * * opting out sends `false` explicitly rather than omitting the field;
 * * a null `marketing_opt_in_changed_at` survives the round trip, because
 *   "never asked" is a different fact from an explicit opt-in and every
 *   existing account is in that state.
 */

import type {MarketingConsent} from '@/types/app';

const mockGet = jest.fn();
const mockPut = jest.fn();

jest.mock('@services/requestCache', () => ({
  cachedRequest: (_key: string, _ttl: unknown, run: () => unknown) => run(),
  invalidateRequestCache: jest.fn(),
  tokenScope: () => 'scope',
  TTL: {NONE: 0, SHORT: 0, MEDIUM: 0, LONG: 0},
}));

jest.mock('axios', () => ({
  __esModule: true,
  default: {
    create: () => ({
      get: mockGet,
      put: mockPut,
      post: jest.fn(),
      delete: jest.fn(),
      defaults: {headers: {common: {}}},
      interceptors: {
        request: {use: jest.fn()},
        response: {use: jest.fn()},
      },
    }),
    isAxiosError: () => false,
  },
}));

const TOKEN = 'test-token';

function consent(over: Partial<MarketingConsent> = {}): MarketingConsent {
  return {marketing_opt_in: true, marketing_opt_in_changed_at: null, ...over};
}

describe('marketing consent client', () => {
  beforeEach(() => {
    jest.resetModules();
    mockGet.mockReset();
    mockPut.mockReset();
  });

  it('reads from its own route with the caller token', async () => {
    mockGet.mockResolvedValue({data: consent()});
    const {api} = require('@services/api');

    const result = await api.getMarketingConsent(TOKEN);

    expect(mockGet).toHaveBeenCalledWith('/profile/marketing-preferences', {
      headers: expect.objectContaining({Authorization: `Bearer ${TOKEN}`}),
    });
    expect(result.marketing_opt_in).toBe(true);
    // "Never asked" must survive: the screen shows it differently from a date.
    expect(result.marketing_opt_in_changed_at).toBeNull();
  });

  it('opts out by sending false, not by omitting the field', async () => {
    mockPut.mockResolvedValue({
      data: consent({marketing_opt_in: false, marketing_opt_in_changed_at: '2026-09-19T10:00:00Z'}),
    });
    const {api} = require('@services/api');

    const result = await api.updateMarketingConsent(TOKEN, false);

    expect(mockPut).toHaveBeenCalledWith(
      '/profile/marketing-preferences',
      {marketing_opt_in: false},
      expect.objectContaining({
        headers: expect.objectContaining({Authorization: `Bearer ${TOKEN}`}),
      }),
    );
    expect(result.marketing_opt_in).toBe(false);
    expect(result.marketing_opt_in_changed_at).toBe('2026-09-19T10:00:00Z');
  });

  it('opts back in the same way', async () => {
    mockPut.mockResolvedValue({data: consent({marketing_opt_in: true})});
    const {api} = require('@services/api');

    await api.updateMarketingConsent(TOKEN, true);

    expect(mockPut).toHaveBeenCalledWith(
      '/profile/marketing-preferences',
      {marketing_opt_in: true},
      expect.anything(),
    );
  });

  it('never writes consent through the preferences endpoint', async () => {
    mockPut.mockResolvedValue({data: consent({marketing_opt_in: false})});
    const {api} = require('@services/api');

    await api.updateMarketingConsent(TOKEN, false);

    const paths = mockPut.mock.calls.map(call => call[0]);
    expect(paths).toEqual(['/profile/marketing-preferences']);
    expect(paths).not.toContain('/preferences/me');
  });

  it('returns the server answer, not the value that was sent', async () => {
    // If the server refuses and returns the old value, the switch must show it.
    mockPut.mockResolvedValue({data: consent({marketing_opt_in: true})});
    const {api} = require('@services/api');

    const result = await api.updateMarketingConsent(TOKEN, false);

    expect(result.marketing_opt_in).toBe(true);
  });
});
