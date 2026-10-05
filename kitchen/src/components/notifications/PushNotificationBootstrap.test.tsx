import { Alert } from 'react-native';
import ReactTestRenderer from 'react-test-renderer';
import { deleteToken } from '@react-native-firebase/messaging';
import { login } from '@services/auth';
import { registerDevice, unregisterDevice } from '@services/devices';
import { fetchOrder, fetchOrdersByStatus } from '@services/orders';
import { fetchRestaurant } from '@services/restaurants';
import { openFromNotification } from '@services/pushNotifications';
import { resetNavigationServiceForTests } from '@navigation/navigationService';
import { kitchenSession, order } from '@/test/fixtures';
import {
  byTestId,
  currentRoute,
  press,
  renderApp,
  settle,
  typeInto,
  unmount,
  type Tree,
} from '@/test/renderApp';

jest.mock('@services/devices', () => ({
  registerDevice: jest.fn(async () => undefined),
  unregisterDevice: jest.fn(async () => undefined),
}));
jest.mock('@services/auth', () => ({ login: jest.fn() }));
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
  resetNavigationServiceForTests();
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

test('a session restored at launch registers this device for it', async () => {
  tree = await renderApp(kitchenSession({ token: 'restored' }), undefined, { push: true });
  await settle();
  expect(registerDevice).toHaveBeenCalledWith('restored', expect.objectContaining({ fcm_token: 'fcm-token-1' }));
});

test('signing out unregisters the device with the token that was signed in', async () => {
  const alert = jest.spyOn(Alert, 'alert');
  tree = await renderApp(kitchenSession({ token: 'outgoing' }), undefined, { push: true });
  await settle();
  await press(tree, 'open-settings');
  await press(tree, 'sign-out');
  const buttons = alert.mock.calls[0][2]!;
  await ReactTestRenderer.act(async () => buttons.find(b => b.style === 'destructive')!.onPress!());
  await settle();

  expect(currentRoute()?.name).toBe('LoginScreen');
  expect(unregisterDevice).toHaveBeenCalledWith('outgoing', expect.any(String));
  expect(deleteToken).toHaveBeenCalled();
  alert.mockRestore();
});

test('a notification tapped on a signed-out tablet opens the order after sign-in', async () => {
  const ticket = order({ id: 'push0000-0001' });
  (fetchOrder as jest.Mock).mockResolvedValue(ticket);
  (login as jest.Mock).mockResolvedValue({
    access_token: 'fresh',
    token_type: 'bearer',
    role: 'KITCHEN',
    restaurant_id: 'r-1',
    restaurant_location_id: null,
    user: { id: 'u-1', full_name: 'Cook', email: 'cook@example.com', role: 'KITCHEN' },
  });
  tree = await renderApp(null, undefined, { push: true });

  openFromNotification({ order_id: ticket.id });
  await settle();
  expect(currentRoute()?.name).toBe('LoginScreen');

  await typeInto(tree, 'login-email', 'cook@example.com');
  await typeInto(tree, 'login-password', 'password123');
  await ReactTestRenderer.act(async () => byTestId(tree!, 'login-submit').props.onPress());
  await settle();

  expect(currentRoute()?.name).toBe('OrderDetailScreen');
  expect(currentRoute()?.params).toEqual({ orderId: ticket.id });
  expect(registerDevice).toHaveBeenCalledWith('fresh', expect.anything());
});
