import ReactTestRenderer from 'react-test-renderer';
import { fetchCompletedOrders, fetchOrder, fetchOrdersByStatus } from '@services/orders';
import { fetchRestaurant } from '@services/restaurants';
import { kitchenSession, order } from '@/test/fixtures';
import {
  allText,
  currentRoute,
  hasTestId,
  press,
  renderApp,
  settle,
  typeInto,
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

const mockedCompleted = fetchCompletedOrders as jest.Mock;

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

const openHistory = async () => {
  tree = await renderApp(kitchenSession());
  await press(tree, 'open-history');
  expect(currentRoute()?.name).toBe('OrderHistoryScreen');
  return tree;
};

test('opens on today, from local midnight', async () => {
  mockedCompleted.mockResolvedValue({ rows: [], total: 0 });
  const screen = await openHistory();
  expect(hasTestId(screen, 'history-empty-today')).toBe(true);
  const query = mockedCompleted.mock.calls[0][1];
  expect(query.completedFrom).toEqual(expect.any(String));
  expect(query.search).toBeUndefined();
});

test('a search looks through all dates and says when nothing matches', async () => {
  mockedCompleted.mockResolvedValue({ rows: [], total: 0 });
  const screen = await openHistory();

  await typeInto(screen, 'history-search', '#ab12');
  await ReactTestRenderer.act(async () => {
    await new Promise<void>(resolve => setTimeout(() => resolve(), 350));
  });
  await settle();

  const query = mockedCompleted.mock.calls.at(-1)[1];
  expect(query.search).toBe('ab12');
  expect(query.completedFrom).toBeUndefined();
  expect(hasTestId(screen, 'history-empty-search')).toBe(true);
});

test('a completed order opens read-only, with its completion time kept', async () => {
  const done = order({
    id: 'c0ffee00-done',
    status: 'DELIVERED',
    completed_at: '2026-10-03T13:10:00.000Z',
  });
  mockedCompleted.mockResolvedValue({ rows: [done], total: 1 });
  // GET /orders/{id} never fills completed_at.
  (fetchOrder as jest.Mock).mockResolvedValue({ ...done, completed_at: null });
  const screen = await openHistory();
  expect(allText(screen)).toMatch(/Showing 1 of 1/);

  await press(screen, `history-row-${done.id}`);

  expect(currentRoute()?.name).toBe('OrderDetailScreen');
  expect(hasTestId(screen, 'detail-advance')).toBe(false);
  expect(allText(screen)).toMatch(/Nothing left to do/);
  expect(allText(screen)).not.toMatch(/Time not recorded/);
});
