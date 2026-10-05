import { Alert } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import ReactTestRenderer from 'react-test-renderer';
import { fetchOrdersByStatus } from '@services/orders';
import { fetchRestaurant } from '@services/restaurants';
import { kitchenSession } from '@/test/fixtures';
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

const mockedByStatus = fetchOrdersByStatus as jest.Mock;
let tree: Tree | null = null;

beforeEach(() => {
  mockedByStatus.mockResolvedValue({ rows: [], total: 0 });
  (fetchRestaurant as jest.Mock).mockResolvedValue({
    id: 'r-1',
    name: 'Bangkok Bowl',
    locations: [
      { id: 'l-1', branch_name: 'Downtown', is_open: true },
      { id: 'l-2', branch_name: 'Airport', is_open: false },
    ],
  });
});

afterEach(async () => {
  if (tree) {
    await unmount(tree);
    tree = null;
  }
  jest.restoreAllMocks();
  jest.clearAllMocks();
});

test('an unpinned account picks a branch, and the board follows it', async () => {
  tree = await renderApp(kitchenSession());
  await press(tree, 'open-settings');
  expect(hasTestId(tree, 'branch-all')).toBe(true);

  await press(tree, 'branch-l-2');

  expect(await AsyncStorage.getItem('kitchen.branchId')).toBe('l-2');
  const lastScope = mockedByStatus.mock.calls.at(-1)[2];
  expect(lastScope).toMatchObject({ restaurantId: 'r-1', locationId: 'l-2' });
});

test('a pinned kitchen account is never offered another branch', async () => {
  tree = await renderApp(kitchenSession({ restaurantLocationId: 'l-1' }));
  await press(tree, 'open-settings');
  expect(hasTestId(tree, 'branch-all')).toBe(false);
  expect(mockedByStatus.mock.calls[0][2]).toMatchObject({ restaurantId: 'r-1', locationId: 'l-1' });
});

test('the sound preference survives a restart', async () => {
  tree = await renderApp(kitchenSession());
  await press(tree, 'open-settings');
  const toggle = tree.root.findAll(node => node.props.testID === 'sound-switch')[0];
  await ReactTestRenderer.act(async () => toggle.props.onValueChange(false));
  expect(await AsyncStorage.getItem('kitchen.soundOn')).toBe('off');
});

test('signing out asks first, then forgets the session', async () => {
  const alert = jest.spyOn(Alert, 'alert');
  tree = await renderApp(kitchenSession());
  await press(tree, 'open-settings');
  await press(tree, 'sign-out');

  const buttons = alert.mock.calls[0][2]!;
  await ReactTestRenderer.act(async () => buttons.find(b => b.style === 'destructive')!.onPress!());
  await settle();

  expect(currentRoute()?.name).toBe('LoginScreen');
  expect(await AsyncStorage.getItem('kitchen.session')).toBeNull();
});
