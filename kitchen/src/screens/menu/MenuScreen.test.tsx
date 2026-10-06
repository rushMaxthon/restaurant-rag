import ReactTestRenderer from 'react-test-renderer';
import { ApiError } from '@services/api';
import { fetchKitchenMenu, updateDishStock, updateSizeStock } from '@services/menu';
import { fetchOrdersByStatus } from '@services/orders';
import { fetchRestaurant } from '@services/restaurants';
import { kitchenSession } from '@/test/fixtures';
import {
  allText,
  byTestId,
  currentRoute,
  hasTestId,
  press,
  renderApp,
  settle,
  typeInto,
  unmount,
  type Tree,
} from '@/test/renderApp';
import type { KitchenMenuItem } from '@/types/app';

jest.mock('@services/menu', () => ({
  fetchKitchenMenu: jest.fn(),
  updateDishStock: jest.fn(),
  updateSizeStock: jest.fn(),
}));
jest.mock('@services/orders', () => ({
  fetchOrdersByStatus: jest.fn(),
  fetchOrder: jest.fn(),
  advanceOrder: jest.fn(),
  fetchCompletedOrders: jest.fn(),
}));
jest.mock('@services/restaurants', () => ({ fetchRestaurant: jest.fn() }));
jest.mock('@services/sound', () => ({ playNewOrderAlert: jest.fn(), prepareChime: jest.fn() }));

const dish = (overrides: Partial<KitchenMenuItem>): KitchenMenuItem => ({
  id: 'd',
  name: 'Dish',
  category: 'Mains',
  is_veg: true,
  restaurant_location_id: 'l-1',
  branch_name: 'Downtown',
  is_available: true,
  out_of_stock: false,
  stock_quantity: null,
  stock_daily_quantity: null,
  is_on_sale: true,
  sizes: [],
  updated_at: '1',
  ...overrides,
});

const curry = dish({ id: 'curry', name: 'Green Curry', stock_quantity: 5, stock_daily_quantity: 10 });
const soup = dish({ id: 'soup', name: 'Seasonal Soup', is_available: false, is_on_sale: false });
const rice = dish({ id: 'rice', name: 'Jasmine Rice', out_of_stock: true, stock_quantity: 0, is_on_sale: false });
const pizza = dish({
  id: 'pizza',
  name: 'Pizza',
  category: 'Pizza',
  sizes: [{ id: 'large', name: 'Large', stock_quantity: 2, stock_daily_quantity: null }],
});

const mockedFetch = fetchKitchenMenu as jest.Mock;
const mockedDish = updateDishStock as jest.Mock;
const mockedSize = updateSizeStock as jest.Mock;

let tree: Tree | null = null;

beforeEach(() => {
  mockedFetch.mockResolvedValue([curry, soup, rice, pizza]);
  // The server answers with the dish as it now is.
  mockedDish.mockImplementation(async (_t: string, id: string, change: object) => {
    const base = [curry, soup, rice, pizza].find(item => item.id === id)!;
    return { ...base, ...change, updated_at: '2' };
  });
  mockedSize.mockImplementation(async (_t: string, id: string) => ({
    ...[curry, soup, rice, pizza].find(item => item.id === id)!,
    updated_at: '2',
  }));
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

const openMenu = async () => {
  tree = await renderApp(kitchenSession({ restaurantLocationId: 'l-1' }));
  await press(tree, 'tab-MenuScreen');
  expect(currentRoute()?.name).toBe('MenuScreen');
  return tree;
};

test('lists the branch’s dishes with what a customer can do with each', async () => {
  const screen = await openMenu();
  expect(mockedFetch).toHaveBeenCalledWith('token-1', expect.objectContaining({ restaurantId: 'r-1', locationId: 'l-1' }));
  const text = allText(screen);
  expect(text).toMatch(/5 left/);
  expect(text).toMatch(/10 each morning/);
  expect(text).toMatch(/Hidden by owner/);
  expect(text).toMatch(/Out of stock/);
  expect(text).toMatch(/Large: 2 left/);
  expect(text).toMatch(/In stock · 5 left/);
  expect(byTestId(screen, 'menu-stat-out').props.accessibilityLabel).toBe('1 Out of stock');
  expect(byTestId(screen, 'menu-stat-hidden').props.accessibilityLabel).toBe('1 Hidden');
  expect(text).toMatch(/Mark out/);
  expect(text).toMatch(/Restock/);
});

test('marking a dish out of stock sends only that, and shows the server’s answer', async () => {
  const screen = await openMenu();
  await press(screen, 'menu-toggle-curry');
  expect(mockedDish).toHaveBeenCalledWith('token-1', 'curry', { out_of_stock: true }, expect.anything());
  expect(byTestId(screen, 'menu-stat-out').props.accessibilityLabel).toBe('2 Out of stock');
});

const openEditorFor = async (screen: Tree, label: string) => {
  const row = screen.root.findAll(node => node.props.accessibilityLabel === label && node.props.onPress)[0];
  await ReactTestRenderer.act(async () => row.props.onPress());
};

test('quick adjust in the editor nudges the count by one, saved at once', async () => {
  const screen = await openMenu();
  await openEditorFor(screen, 'Green Curry, 5 left. Edit stock.');
  await press(screen, 'menu-plus-curry');
  expect(mockedDish).toHaveBeenCalledWith('token-1', 'curry', { stock_quantity: 6 }, expect.anything());
  await press(screen, 'menu-minus-curry');
  expect(mockedDish).toHaveBeenLastCalledWith('token-1', 'curry', { stock_quantity: 5 }, expect.anything());
});

test('back in stock at zero asks for a count instead of pretending', async () => {
  const screen = await openMenu();
  await press(screen, 'menu-toggle-rice');
  expect(mockedDish).not.toHaveBeenCalled();
  expect(hasTestId(screen, 'stock-editor-save')).toBe(true);
});

test('the editor sends only the boxes that changed — empty stops counting', async () => {
  const screen = await openMenu();
  const row = screen.root.findAll(
    node => node.props.accessibilityLabel === 'Green Curry, 5 left. Edit stock.' && node.props.onPress,
  )[0];
  await ReactTestRenderer.act(async () => row.props.onPress());

  await typeInto(screen, 'stock-editor-count', '');
  await typeInto(screen, 'stock-editor-daily', '12');
  await press(screen, 'stock-editor-save');

  expect(mockedDish).toHaveBeenCalledWith(
    'token-1',
    'curry',
    { stock_quantity: null, stock_daily_quantity: 12 },
    expect.anything(),
  );
  expect(hasTestId(screen, 'stock-editor-save')).toBe(false);
});

test('a size keeps its own count', async () => {
  const screen = await openMenu();
  const row = screen.root.findAll(node => node.props.accessibilityLabel === 'Pizza, In stock. Edit stock.' && node.props.onPress)[0];
  await ReactTestRenderer.act(async () => row.props.onPress());
  await typeInto(screen, 'stock-editor-size-count-large', '0');
  await press(screen, 'stock-editor-save');
  expect(mockedDish).not.toHaveBeenCalled();
  expect(mockedSize).toHaveBeenCalledWith('token-1', 'pizza', 'large', { stock_quantity: 0 }, expect.anything());
});

test('a mistyped count is caught before anything is sent', async () => {
  const screen = await openMenu();
  const row = screen.root.findAll(
    node => node.props.accessibilityLabel === 'Green Curry, 5 left. Edit stock.' && node.props.onPress,
  )[0];
  await ReactTestRenderer.act(async () => row.props.onPress());
  await typeInto(screen, 'stock-editor-count', '1.5');
  await press(screen, 'stock-editor-save');
  expect(mockedDish).not.toHaveBeenCalled();
  expect(allText(screen)).toMatch(/whole number/);
});

test('a refusal from the server is shown on the dish', async () => {
  mockedDish.mockRejectedValueOnce(new ApiError('Menu item not found', 404));
  const screen = await openMenu();
  await press(screen, 'menu-toggle-curry');
  expect(allText(screen)).toMatch(/Menu item not found/);
});

test('filters narrow the list', async () => {
  const screen = await openMenu();
  await press(screen, 'menu-filter-HIDDEN');
  expect(hasTestId(screen, 'menu-row-soup')).toBe(true);
  expect(hasTestId(screen, 'menu-row-curry')).toBe(false);
  await typeInto(screen, 'menu-search', 'zzz');
  await settle();
  expect(hasTestId(screen, 'menu-no-match')).toBe(true);
});

test('an empty menu says who adds dishes', async () => {
  mockedFetch.mockResolvedValue([]);
  const screen = await openMenu();
  expect(byTestId(screen, 'menu-empty')).toBeDefined();
});

test('a section folds away and comes back', async () => {
  const screen = await openMenu();
  expect(hasTestId(screen, 'menu-row-pizza')).toBe(true);
  await press(screen, 'menu-section-Pizza');
  expect(hasTestId(screen, 'menu-row-pizza')).toBe(false);
  expect(allText(screen)).toMatch(/1 item/);
  await press(screen, 'menu-section-Pizza');
  expect(hasTestId(screen, 'menu-row-pizza')).toBe(true);
});

test('the branch button is offered only to an account that can pick a branch', async () => {
  const pinned = await openMenu();
  expect(hasTestId(pinned, 'menu-branch')).toBe(false);
  await unmount(pinned);
  tree = await renderApp(kitchenSession({ restaurantLocationId: null }));
  await press(tree, 'tab-MenuScreen');
  await press(tree, 'menu-branch');
  expect(currentRoute()?.name).toBe('SettingsScreen');
});
