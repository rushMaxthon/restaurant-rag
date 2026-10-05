import ReactTestRenderer from 'react-test-renderer';
import { fetchOrder, fetchOrdersByStatus } from '@services/orders';
import { fetchRestaurant } from '@services/restaurants';
import { navigationRef } from '@navigation/navigationService';
import { kitchenSession, order } from '@/test/fixtures';
import { currentRoute, renderApp, settle, unmount, type Tree } from '@/test/renderApp';

jest.mock('@services/orders', () => ({
  fetchOrdersByStatus: jest.fn(),
  fetchOrder: jest.fn(),
  advanceOrder: jest.fn(),
  fetchCompletedOrders: jest.fn(),
}));
jest.mock('@services/restaurants', () => ({ fetchRestaurant: jest.fn() }));
jest.mock('@services/sound', () => ({ playNewOrderAlert: jest.fn(), prepareChime: jest.fn() }));

let tree: Tree | null = null;

beforeEach(() => {
  (fetchOrdersByStatus as jest.Mock).mockResolvedValue({ rows: [], total: 0 });
  (fetchRestaurant as jest.Mock).mockResolvedValue({ id: 'r-1', name: 'Bangkok Bowl', locations: [] });
});

afterEach(async () => {
  if (tree) {
    await unmount(tree);
    tree = null;
  }
  jest.clearAllMocks();
});

test('a signed-out tablet only has the login screen', async () => {
  tree = await renderApp(null);
  expect(currentRoute()?.name).toBe('LoginScreen');
  expect(navigationRef.getRootState()?.routeNames).toEqual(['LoginScreen']);
});

test('a signed-in tablet opens on the board and can push and pop', async () => {
  const ticket = order({ id: 'stack000-0042' });
  (fetchOrder as jest.Mock).mockResolvedValue(ticket);
  tree = await renderApp(kitchenSession());
  expect(currentRoute()?.name).toBe('BoardScreen');
  expect(navigationRef.getRootState()?.routeNames).not.toContain('LoginScreen');

  await ReactTestRenderer.act(async () => {
    navigationRef.navigate('OrderDetailScreen', { orderId: ticket.id });
  });
  await settle();
  expect(currentRoute()?.name).toBe('OrderDetailScreen');
  expect(currentRoute()?.params).toEqual({ orderId: ticket.id });

  await ReactTestRenderer.act(async () => navigationRef.goBack());
  expect(currentRoute()?.name).toBe('BoardScreen');
});
