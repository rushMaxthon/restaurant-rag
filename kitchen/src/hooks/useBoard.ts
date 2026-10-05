import { useCallback, useEffect, useRef, useState } from 'react';
import { BOARD_COLUMNS } from '@/data/boardColumns';
import { fetchOrdersByStatus } from '@services/orders';
import type { BoardScope, KitchenOrder, LiveStatus } from '@/types/app';
import { hiddenCount, inServiceOrder, liveWindowStart } from '@utils/board';
import { reuseUnchanged } from '@utils/reconcile';
import { usePolling } from '@hooks/usePolling';

export interface ColumnState {
  orders: KitchenOrder[];
  // Matching this column but beyond the page the server returned.
  hidden: number;
  // Nothing loaded yet — the only time a skeleton is right.
  loading: boolean;
  failed: boolean;
}

export type BoardColumns = Record<LiveStatus, ColumnState>;

const emptyColumn = (): ColumnState => ({ orders: [], hidden: 0, loading: true, failed: false });

const initialColumns = (): BoardColumns => ({
  PLACED: emptyColumn(),
  ACCEPTED: emptyColumn(),
  PREPARING: emptyColumn(),
  OUT_FOR_DELIVERY: emptyColumn(),
});

// The live board: four columns fetched together, each kept independently.
// A column that fails keeps its last good tickets and is marked failed, so a
// broken "New" never blanks a working "Cooking" — a kitchen that can still
// work three columns is still a kitchen that can work.
export function useBoard(token: string | null, scope: BoardScope, pollIntervalMs: number) {
  const [columns, setColumns] = useState<BoardColumns>(initialColumns);
  const [refreshing, setRefreshing] = useState(false);
  const generation = useRef(0);
  const scopeKey = `${scope.restaurantId ?? 'any'}:${scope.locationId ?? 'any'}`;

  // A different branch is a different board: start from skeletons, never
  // from the previous branch's tickets.
  useEffect(() => {
    generation.current += 1;
    setColumns(initialColumns());
  }, [scopeKey]);

  const load = useCallback(async () => {
    if (!token) {
      return;
    }
    const mine = ++generation.current;
    // Computed per fetch, so the window advances with the poll rather than
    // staying pinned to whenever the board was opened.
    const dueFrom = liveWindowStart();
    const results = await Promise.allSettled(
      BOARD_COLUMNS.map(column => fetchOrdersByStatus(token, column.status, scope, dueFrom)),
    );
    // A newer load (or a branch switch) started meanwhile; this one is stale.
    if (mine !== generation.current) {
      return;
    }
    // Unchanged orders, columns and the board itself keep their identity, so
    // an idle poll sets no new state and renders nothing.
    setColumns(current => {
      let changed = false;
      const next = { ...current };
      BOARD_COLUMNS.forEach((column, index) => {
        const result = results[index];
        const before = current[column.status];
        let after: ColumnState;
        if (result.status === 'fulfilled') {
          const orders = reuseUnchanged(before.orders, inServiceOrder(result.value.rows));
          const hidden = hiddenCount(result.value.total, result.value.rows.length);
          after =
            orders === before.orders && hidden === before.hidden && !before.loading && !before.failed
              ? before
              : { orders, hidden, loading: false, failed: false };
        } else {
          after = before.failed && !before.loading ? before : { ...before, loading: false, failed: true };
        }
        if (after !== before) {
          changed = true;
          next[column.status] = after;
        }
      });
      return changed ? next : current;
    });
    // `scope` is captured through scopeKey; listing the object would refetch
    // on every render that rebuilt it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, scopeKey]);

  usePolling(load, pollIntervalMs, Boolean(token && scope.restaurantId));

  // Pull-to-refresh: shows the spinner until this load lands.
  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await load();
    } finally {
      setRefreshing(false);
    }
  }, [load]);

  const statuses = BOARD_COLUMNS.map(column => columns[column.status]);
  return {
    columns,
    refresh,
    refreshing,
    // Still waiting on a first answer for at least one column.
    loading: statuses.some(column => column.loading),
    // At least one column's last load failed — the header says "Not updating".
    stale: statuses.some(column => column.failed),
    // Every column failed and there is nothing to show: the full fault screen.
    down:
      statuses.every(column => column.failed) &&
      statuses.every(column => column.orders.length === 0),
  };
}
