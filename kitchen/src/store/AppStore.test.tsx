import AsyncStorage from '@react-native-async-storage/async-storage';
import { request } from '@services/api';
import { fetchOrdersByStatus } from '@services/orders';
import { fetchRestaurant } from '@services/restaurants';
import { kitchenSession } from '@/test/fixtures';
import {
  currentRoute,
  hasTestId,
  renderApp,
  settle,
  unmount,
  type Tree,
} from '@/test/renderApp';
import ReactTestRenderer from 'react-test-renderer';

jest.mock('@services/orders', () => ({
  fetchOrdersByStatus: jest.fn(),
  fetchOrder: jest.fn(),
  advanceOrder: jest.fn(),
  fetchCompletedOrders: jest.fn(),
}));
jest.mock('@services/restaurants', () => ({ fetchRestaurant: jest.fn() }));
jest.mock('@services/sound', () => ({ playNewOrderAlert: jest.fn(), prepareChime: jest.fn() }));

let tree: Tree | null = null;
const realFetch = globalThis.fetch;

beforeEach(() => {
  (fetchOrdersByStatus as jest.Mock).mockResolvedValue({ rows: [], total: 0 });
  (fetchRestaurant as jest.Mock).mockResolvedValue({ id: 'r-1', name: 'Bangkok Bowl', locations: [] });
});

afterEach(async () => {
  if (tree) {
    await unmount(tree);
    tree = null;
  }
  globalThis.fetch = realFetch;
  jest.clearAllMocks();
});

const answer401 = () => {
  globalThis.fetch = jest.fn().mockResolvedValue({
    ok: false,
    status: 401,
    json: async () => ({ detail: 'Could not validate credentials' }),
  }) as unknown as typeof fetch;
};

test('a tablet with no saved session starts on sign-in', async () => {
  tree = await renderApp(null);
  expect(currentRoute()?.name).toBe('LoginScreen');
  expect(hasTestId(tree, 'login-expired')).toBe(false);
});

test('a 401 on the signed-in token ends the session and says why', async () => {
  tree = await renderApp(kitchenSession({ token: 'live-token' }));
  answer401();

  await ReactTestRenderer.act(async () => {
    await request('/orders', { token: 'live-token' }).catch(() => undefined);
  });
  await settle();

  expect(currentRoute()?.name).toBe('LoginScreen');
  expect(hasTestId(tree, 'login-expired')).toBe(true);
  expect(await AsyncStorage.getItem('kitchen.session')).toBeNull();
});

test('a 401 for a token from an earlier login signs nobody out', async () => {
  tree = await renderApp(kitchenSession({ token: 'live-token' }));
  answer401();

  await ReactTestRenderer.act(async () => {
    await request('/orders', { token: 'old-token' }).catch(() => undefined);
  });
  await settle();

  expect(currentRoute()?.name).toBe('BoardScreen');
});

test('a malformed saved session is dropped rather than trusted', async () => {
  tree = await renderApp(null, '{"token": 42}');
  expect(currentRoute()?.name).toBe('LoginScreen');
});
