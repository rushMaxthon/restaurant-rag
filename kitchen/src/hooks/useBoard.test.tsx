import React from 'react';
import ReactTestRenderer from 'react-test-renderer';
import { fetchOrdersByStatus } from '@services/orders';
import { ordersChanged } from '@services/orderEvents';
import { order } from '@/test/fixtures';
import { settle } from '@/test/renderApp';
import type { LiveStatus } from '@/types/app';
import { useBoard, type BoardColumns } from './useBoard';

jest.mock('@services/orders', () => ({ fetchOrdersByStatus: jest.fn() }));

const mockedByStatus = fetchOrdersByStatus as jest.Mock;
const scope = { restaurantId: 'r-1', locationId: null };

// Records what the board handed its screen on every render.
let snapshots: BoardColumns[] = [];
const Probe = () => {
  const board = useBoard('token', scope, 60000);
  snapshots.push(board.columns);
  return null;
};

const server: Record<LiveStatus, ReturnType<typeof order>[]> = {
  PLACED: [],
  ACCEPTED: [],
  PREPARING: [],
  OUT_FOR_DELIVERY: [],
};

let tree: ReactTestRenderer.ReactTestRenderer;

beforeEach(async () => {
  snapshots = [];
  server.PLACED = [order({ id: 'a', updated_at: '1' })];
  server.PREPARING = [order({ id: 'b', status: 'PREPARING', updated_at: '1' })];
  // Fresh objects on every call, exactly as JSON off the wire would be.
  mockedByStatus.mockImplementation(async (_t: string, status: LiveStatus) => ({
    rows: server[status].map(row => ({ ...row })),
    total: server[status].length,
  }));
  await ReactTestRenderer.act(async () => {
    tree = ReactTestRenderer.create(<Probe />);
  });
  await settle();
});

afterEach(async () => {
  await ReactTestRenderer.act(async () => tree.unmount());
});

// React may render the hook's own component once more before bailing out of
// an unchanged state update — documented behaviour, and cheap. What matters
// is that the board it hands down keeps its identity, so every memoised
// ticket, tab and header below skips.
test('an idle poll hands the screen the very same board', async () => {
  const before = snapshots.at(-1)!;
  const renders = snapshots.length;

  await ReactTestRenderer.act(async () => ordersChanged());
  await settle();

  expect(mockedByStatus.mock.calls.length).toBeGreaterThan(4);
  expect(snapshots.length - renders).toBeLessThanOrEqual(1);
  for (const snapshot of snapshots.slice(renders)) {
    expect(snapshot).toBe(before);
  }
});

test('a real change re-renders, keeping the untouched columns and orders as they were', async () => {
  const before = snapshots.at(-1)!;
  server.PLACED = [{ ...server.PLACED[0], status: 'ACCEPTED', updated_at: '2' }];
  server.ACCEPTED = server.PLACED;
  server.PLACED = [];

  await ReactTestRenderer.act(async () => ordersChanged());
  await settle();

  const after = snapshots.at(-1)!;
  expect(after).not.toBe(before);
  expect(after.PLACED.orders).toEqual([]);
  expect(after.ACCEPTED.orders[0].id).toBe('a');
  // Cooking did not change: same column object, same order object.
  expect(after.PREPARING).toBe(before.PREPARING);
  expect(after.PREPARING.orders[0]).toBe(before.PREPARING.orders[0]);
});
