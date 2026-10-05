import ReactTestRenderer from 'react-test-renderer';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { ApiError, NETWORK_ERROR_STATUS } from '@services/api';
import { login } from '@services/auth';
import { fetchOrdersByStatus } from '@services/orders';
import { fetchRestaurant } from '@services/restaurants';
import type { AuthResponse } from '@/types/app';
import {
  allText,
  byTestId,
  currentRoute,
  hasTestId,
  renderApp,
  settle,
  typeInto,
  unmount,
  type Tree,
} from '@/test/renderApp';

jest.mock('@services/auth', () => ({ login: jest.fn() }));
jest.mock('@services/orders', () => ({
  fetchOrdersByStatus: jest.fn(),
  fetchOrder: jest.fn(),
  advanceOrder: jest.fn(),
  fetchCompletedOrders: jest.fn(),
}));
jest.mock('@services/restaurants', () => ({ fetchRestaurant: jest.fn() }));
jest.mock('@services/sound', () => ({ playNewOrderAlert: jest.fn(), prepareChime: jest.fn() }));

const mockedLogin = login as jest.Mock;
let tree: Tree | null = null;

const authResponse = (role: AuthResponse['role']): AuthResponse => ({
  access_token: 'token',
  token_type: 'bearer',
  role,
  restaurant_id: 'r-1',
  restaurant_location_id: null,
  user: { id: 'u-1', full_name: 'Line Cook', email: 'cook@example.com', role },
});

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

const signIn = async (screen: Tree, email: string, password: string) => {
  await typeInto(screen, 'login-email', email);
  await typeInto(screen, 'login-password', password);
  await ReactTestRenderer.act(async () => {
    byTestId(screen, 'login-submit').props.onPress();
  });
  await settle();
};

test('an empty form is refused without calling the server', async () => {
  tree = await renderApp(null);
  await ReactTestRenderer.act(async () => byTestId(tree!, 'login-submit').props.onPress());
  expect(mockedLogin).not.toHaveBeenCalled();
  expect(allText(tree)).toMatch(/Enter the email/);
  expect(allText(tree)).toMatch(/Enter the password/);
});

test('a correct kitchen login lands on the board and is remembered', async () => {
  mockedLogin.mockResolvedValue(authResponse('KITCHEN'));
  tree = await renderApp(null);
  await signIn(tree, '  cook@example.com ', 'password123');

  expect(mockedLogin).toHaveBeenCalledWith('cook@example.com', 'password123');
  expect(currentRoute()?.name).toBe('BoardScreen');
  expect(JSON.parse((await AsyncStorage.getItem('kitchen.session'))!).token).toBe('token');
});

test('a wrong password stays on login and says so', async () => {
  mockedLogin.mockRejectedValue(new ApiError('Invalid', 401));
  tree = await renderApp(null);
  await signIn(tree, 'cook@example.com', 'wrongpassword');

  expect(currentRoute()?.name).toBe('LoginScreen');
  expect(hasTestId(tree, 'login-error')).toBe(true);
  expect(allText(tree)).toMatch(/incorrect/);
});

test('a customer account is turned away even with the right password', async () => {
  mockedLogin.mockResolvedValue(authResponse('CUSTOMER'));
  tree = await renderApp(null);
  await signIn(tree, 'customer1@example.com', 'password123');

  expect(currentRoute()?.name).toBe('LoginScreen');
  expect(allText(tree)).toMatch(/cannot open the kitchen board/);
});

test('an unreachable server is not reported as a wrong password', async () => {
  mockedLogin.mockRejectedValue(new ApiError('down', NETWORK_ERROR_STATUS));
  tree = await renderApp(null);
  await signIn(tree, 'cook@example.com', 'password123');

  expect(allText(tree)).toMatch(/Cannot reach the server/);
  expect(allText(tree)).not.toMatch(/incorrect/);
});
