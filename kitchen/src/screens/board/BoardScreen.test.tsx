import { ApiError, NETWORK_ERROR_STATUS } from '@services/api';
import { advanceOrder, fetchOrder, fetchOrdersByStatus } from '@services/orders';
import { fetchRestaurant } from '@services/restaurants';
import { ordersChanged } from '@services/orderEvents';
import { playNewOrderAlert } from '@services/sound';
import { kitchenSession, order } from '@/test/fixtures';
import {
  allText,
  currentRoute,
  hasTestId,
  press,
  renderApp,
  settle,
  unmount,
  type Tree,
} from '@/test/renderApp';
import type { KitchenOrder, LiveStatus } from '@/types/app';
import ReactTestRenderer from 'react-test-renderer';

jest.mock('@services/orders', () => ({
  fetchOrdersByStatus: jest.fn(),
  fetchOrder: jest.fn(),
  advanceOrder: jest.fn(),
  fetchCompletedOrders: jest.fn(),
}));
jest.mock('@services/restaurants', () => ({ fetchRestaurant: jest.fn() }));
jest.mock('@services/sound', () => ({
  playNewOrderAlert: jest.fn(),
  prepareChime: jest.fn(),
}));

const mockedByStatus = fetchOrdersByStatus as jest.Mock;
const mockedAdvance = advanceOrder as jest.Mock;
const mockedFetchOrder = fetchOrder as jest.Mock;

// What the server holds, per column, newest first as the API sends it.
let board: Record<LiveStatus, KitchenOrder[]>;
const serve = () =>
  mockedByStatus.mockImplementation(async (_token: string, status: LiveStatus) => ({
    rows: board[status],
    total: board[status].length,
  }));

let tree: Tree | null = null;

beforeEach(() => {
  board = { PLACED: [], ACCEPTED: [], PREPARING: [], OUT_FOR_DELIVERY: [] };
  serve();
  (fetchRestaurant as jest.Mock).mockResolvedValue({
    id: 'r-1',
    name: 'Bangkok Bowl',
    locations: [{ id: 'l-1', branch_name: 'Downtown', is_open: true }],
  });
});

afterEach(async () => {
  if (tree) {
    await unmount(tree);
    tree = null;
  }
  jest.clearAllMocks();
});

test('a saved session opens straight onto the board, named for its restaurant', async () => {
  const ticket = order({ id: 'feedc0de-1111' });
  board.PLACED = [ticket];
  tree = await renderApp(kitchenSession());

  expect(currentRoute()?.name).toBe('BoardScreen');
  const text = allText(tree);
  expect(text).toMatch(/Bangkok Bowl/);
  expect(text).toMatch(/#FEEDC0DE/);
  expect(text).toMatch(/Accept/);
  // Asked within the live window, one call per column.
  expect(mockedByStatus).toHaveBeenCalledTimes(4);
  expect(mockedByStatus.mock.calls[0][3]).toEqual(expect.any(String));
});

test('an empty stage reads as calm, not broken', async () => {
  tree = await renderApp(kitchenSession());
  expect(hasTestId(tree, 'empty-PLACED')).toBe(true);
  expect(allText(tree)).toMatch(/You’re all caught up/);
});

test('advancing sends the single next status and refetches the board', async () => {
  const ticket = order({ id: 'abc12345-advance' });
  board.PLACED = [ticket];
  mockedAdvance.mockImplementation(async () => {
    board = { ...board, PLACED: [], ACCEPTED: [{ ...ticket, status: 'ACCEPTED' }] };
    return { ...ticket, status: 'ACCEPTED' };
  });
  tree = await renderApp(kitchenSession());
  const callsBefore = mockedByStatus.mock.calls.length;

  await press(tree, `advance-${ticket.id}`);

  expect(mockedAdvance).toHaveBeenCalledWith(
    'token-1',
    ticket.id,
    'ACCEPTED',
    expect.objectContaining({ restaurantId: 'r-1' }),
  );
  expect(mockedByStatus.mock.calls.length).toBeGreaterThan(callsBefore);
  expect(hasTestId(tree, 'empty-PLACED')).toBe(true);
});

test('a refused advance shows the server’s own reason on the ticket', async () => {
  const ticket = order({ id: 'abc12345-refuse' });
  board.PLACED = [ticket];
  mockedAdvance.mockRejectedValue(new ApiError('Payment has not settled yet.', 409));
  tree = await renderApp(kitchenSession());

  await press(tree, `advance-${ticket.id}`);

  expect(allText(tree)).toMatch(/Payment has not settled yet\./);
});

test('the first load is silent; an order arriving later is announced', async () => {
  board.PLACED = [order()];
  tree = await renderApp(kitchenSession());
  expect(playNewOrderAlert).not.toHaveBeenCalled();

  board.PLACED = [order(), ...board.PLACED];
  await ReactTestRenderer.act(async () => ordersChanged());
  await settle();

  expect(playNewOrderAlert).toHaveBeenCalledTimes(1);
});

test('a muted board highlights new orders without sound', async () => {
  tree = await renderApp(kitchenSession());
  await press(tree, 'toggle-sound');
  board.PLACED = [order()];
  await ReactTestRenderer.act(async () => ordersChanged());
  await settle();
  expect(playNewOrderAlert).not.toHaveBeenCalled();
});

test('when nothing can be reached, the board says so instead of looking quiet', async () => {
  mockedByStatus.mockRejectedValue(new ApiError('Could not reach the server.', NETWORK_ERROR_STATUS));
  tree = await renderApp(kitchenSession());
  expect(hasTestId(tree, 'board-down')).toBe(true);
  expect(allText(tree)).toMatch(/The board isn’t updating/);
});

test('one failing stage keeps the others working and marks the board stale', async () => {
  board.PREPARING = [order({ id: 'cafe0001-cook', status: 'PREPARING' })];
  mockedByStatus.mockImplementation(async (_token: string, status: LiveStatus) => {
    if (status === 'PLACED') {
      throw new ApiError('boom', 500);
    }
    return { rows: board[status], total: board[status].length };
  });
  tree = await renderApp(kitchenSession());
  expect(hasTestId(tree, 'board-down')).toBe(false);
  expect(allText(tree)).toMatch(/Not updating/);
  expect(allText(tree)).toMatch(/Couldn’t load this stage/);
});

test('an overflowing column says how many tickets it is not showing', async () => {
  board.PLACED = [order()];
  mockedByStatus.mockImplementation(async (_token: string, status: LiveStatus) => ({
    rows: board[status],
    total: status === 'PLACED' ? 61 : board[status].length,
  }));
  tree = await renderApp(kitchenSession());
  expect(allText(tree)).toMatch(/60 more tickets are waiting/);
});

test('an admin without a restaurant is told why there is no board', async () => {
  tree = await renderApp(
    kitchenSession({
      restaurantId: null,
      user: { id: 'a', fullName: 'Admin', email: 'admin@example.com', role: 'ADMIN' },
    }),
  );
  expect(hasTestId(tree, 'no-restaurant')).toBe(true);
  expect(mockedByStatus).not.toHaveBeenCalled();
});

test('tapping a ticket opens the order; the last step there returns to the board', async () => {
  const ticket = order({ id: 'deadbeef-detail', status: 'OUT_FOR_DELIVERY', fulfillment_type: 'PICKUP' });
  board.OUT_FOR_DELIVERY = [ticket];
  mockedFetchOrder.mockResolvedValue(ticket);
  mockedAdvance.mockResolvedValue({ ...ticket, status: 'DELIVERED' });
  tree = await renderApp(kitchenSession());

  await press(tree, 'stage-OUT_FOR_DELIVERY');
  const card = tree.root.findAll(
    node => node.props.accessibilityRole === 'button' && /Open details/.test(node.props.accessibilityLabel ?? ''),
  )[0];
  await ReactTestRenderer.act(async () => card.props.onPress());
  await settle();

  expect(currentRoute()?.name).toBe('OrderDetailScreen');
  expect(allText(tree)).toMatch(/Collected/);

  await press(tree, 'detail-advance');
  expect(mockedAdvance).toHaveBeenCalledWith('token-1', ticket.id, 'DELIVERED', expect.anything());
  expect(currentRoute()?.name).toBe('BoardScreen');
});

describe('on a landscape tablet', () => {
  const { Dimensions } = jest.requireActual('react-native');
  const phone = Dimensions.get('window');

  beforeEach(() => {
    Dimensions.set({ window: { ...phone, width: 1280, height: 800 } });
  });
  // Inner afterEach runs before the outer unmount, so the board is still
  // mounted and re-renders on the resize.
  afterEach(async () => {
    await ReactTestRenderer.act(async () => {
      Dimensions.set({ window: phone });
    });
  });

  test('all four stages sit side by side, with no stage tabs', async () => {
    board.PREPARING = [order({ id: 'b0a4d000-wide', status: 'PREPARING' })];
    tree = await renderApp(kitchenSession());

    expect(hasTestId(tree, 'stage-PLACED')).toBe(false);
    for (const empty of ['empty-PLACED', 'empty-ACCEPTED', 'empty-OUT_FOR_DELIVERY']) {
      expect(hasTestId(tree, empty)).toBe(true);
    }
    expect(hasTestId(tree, 'ticket-b0a4d000-wide')).toBe(true);
    expect(allText(tree)).toMatch(/Median wait/);
  });
});
