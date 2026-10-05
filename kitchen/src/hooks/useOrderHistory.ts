import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchCompletedOrders } from '@services/orders';
import type { BoardScope, KitchenOrder } from '@/types/app';
import { HISTORY_PAGE_SIZE, localDayKey, startOfToday } from '@utils/history';
import { usePolling } from '@hooks/usePolling';

export interface HistoryState {
  rows: KitchenOrder[];
  total: number;
  loading: boolean;
  loadingMore: boolean;
  refreshing: boolean;
  error: string | null;
}

// Finished orders, newest completion first. Today's from local midnight with
// no search; ALL history with one — the question behind a search is usually
// "this customer's receipt from yesterday", and a search that only saw today
// would deny an order that exists.
//
// It polls at the board's rate: with realtime off (the default), an order
// completed on ANOTHER tablet reaches this one only by poll.
export function useOrderHistory(
  token: string | null,
  scope: BoardScope,
  search: string | null,
  pollIntervalMs: number,
) {
  const [state, setState] = useState<HistoryState>({
    rows: [],
    total: 0,
    loading: true,
    loadingMore: false,
    refreshing: false,
    error: null,
  });
  const generation = useRef(0);
  const loadedCount = useRef(HISTORY_PAGE_SIZE);
  const queryKey = `${scope.restaurantId}:${scope.locationId}:${search ?? ''}:${
    search ? 'all' : localDayKey()
  }`;

  const query = useCallback(
    (limit: number, offset: number) =>
      fetchCompletedOrders(token ?? '', {
        scope,
        completedFrom: search ? undefined : startOfToday(),
        search: search ?? undefined,
        limit,
        offset,
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [token, queryKey],
  );

  // A new search or branch starts over from the first page.
  useEffect(() => {
    generation.current += 1;
    loadedCount.current = HISTORY_PAGE_SIZE;
    setState(current => ({ ...current, rows: [], total: 0, loading: true, error: null }));
  }, [queryKey]);

  // Reload everything loaded so far in one request, so a poll keeps a list
  // the cook has scrolled down intact instead of snapping it back to page 1.
  const reload = useCallback(async () => {
    if (!token) {
      return;
    }
    const mine = ++generation.current;
    try {
      const page = await query(loadedCount.current, 0);
      if (mine === generation.current) {
        setState(current => ({
          ...current,
          rows: page.rows,
          total: page.total,
          loading: false,
          error: null,
        }));
      }
    } catch (error) {
      if (mine === generation.current) {
        setState(current => ({
          ...current,
          loading: false,
          error: error instanceof Error ? error.message : 'Could not load completed orders.',
        }));
      }
    }
  }, [token, query]);

  usePolling(reload, pollIntervalMs, Boolean(token));

  const refresh = useCallback(async () => {
    setState(current => ({ ...current, refreshing: true }));
    await reload();
    setState(current => ({ ...current, refreshing: false }));
  }, [reload]);

  const loadMore = useCallback(async () => {
    if (!token || state.loading || state.loadingMore || state.rows.length >= state.total) {
      return;
    }
    const mine = generation.current;
    setState(current => ({ ...current, loadingMore: true }));
    try {
      const page = await query(HISTORY_PAGE_SIZE, state.rows.length);
      if (mine === generation.current) {
        loadedCount.current = state.rows.length + page.rows.length;
        setState(current => {
          // A poll may have shifted rows meanwhile; never list one twice.
          const known = new Set(current.rows.map(row => row.id));
          return {
            ...current,
            rows: [...current.rows, ...page.rows.filter(row => !known.has(row.id))],
            total: page.total,
            loadingMore: false,
          };
        });
      }
    } catch {
      setState(current => ({ ...current, loadingMore: false }));
    }
  }, [token, query, state.loading, state.loadingMore, state.rows.length, state.total]);

  return { ...state, refresh, loadMore, retry: reload };
}
