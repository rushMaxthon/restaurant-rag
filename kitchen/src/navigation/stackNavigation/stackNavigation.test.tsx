import ReactTestRenderer from 'react-test-renderer';
import { fetchOrder, fetchOrdersByStatus } from '@services/orders';
import { fetchRestaurant } from '@services/restaurants';
import { navigationRef } from '@navigation/navigationService';
import { kitchenSession, order } from '@/test/fixtures';
import {
  currentRoute,
  hasTestId,
  press,
  renderApp,
  settle,
  unmount,
  type Tree,
} from '@/test/renderApp';

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
  expect(navigationRef.getRootState()?.routeNames).toEqual([
    'MainTabs',
    'OrderDetailScreen',
    'OrderHistoryScreen',
  ]);

  await ReactTestRenderer.act(async () => {
    navigationRef.navigate('OrderDetailScreen', { orderId: ticket.id });
  });
  await settle();
  expect(currentRoute()?.name).toBe('OrderDetailScreen');
  expect(currentRoute()?.params).toEqual({ orderId: ticket.id });

  await ReactTestRenderer.act(async () => navigationRef.goBack());
  expect(currentRoute()?.name).toBe('BoardScreen');
});

describe('the bottom tabs', () => {
  test('offer Home, Menu and Settings, opening on Home', async () => {
    tree = await renderApp(kitchenSession());
    expect(hasTestId(tree, 'tab-BoardScreen')).toBe(true);
    expect(hasTestId(tree, 'tab-MenuScreen')).toBe(true);
    expect(hasTestId(tree, 'tab-SettingsScreen')).toBe(true);
    expect(currentRoute()?.name).toBe('BoardScreen');
  });

  test('switching to Settings keeps the board mounted and polling', async () => {
    tree = await renderApp(kitchenSession());
    await press(tree, 'tab-SettingsScreen');

    expect(currentRoute()?.name).toBe('SettingsScreen');
    // The board's own header is still in the tree underneath.
    expect(hasTestId(tree, 'toggle-sound')).toBe(true);
    // Settings is a tab, not a pushed screen: nothing to go back to.
    expect(hasTestId(tree, 'header-back')).toBe(false);

    await press(tree, 'tab-BoardScreen');
    expect(currentRoute()?.name).toBe('BoardScreen');
  });

  test('the board header’s settings button switches to the Settings tab', async () => {
    tree = await renderApp(kitchenSession());
    await press(tree, 'open-settings');
    expect(currentRoute()?.name).toBe('SettingsScreen');
    expect(navigationRef.getRootState()?.routes.at(-1)?.name).toBe('MainTabs');
  });

  test('order details opens over the tabs and comes back to Home', async () => {
    const ticket = order({ id: 'tabs0000-0001' });
    (fetchOrder as jest.Mock).mockResolvedValue(ticket);
    tree = await renderApp(kitchenSession());

    await ReactTestRenderer.act(async () => {
      navigationRef.navigate('OrderDetailScreen', { orderId: ticket.id });
    });
    await settle();
    expect(navigationRef.getRootState()?.routes.at(-1)?.name).toBe('OrderDetailScreen');

    await press(tree, 'header-back');
    expect(currentRoute()?.name).toBe('BoardScreen');
  });
});
