import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchKitchenMenu, updateDishStock, updateSizeStock } from '@services/menu';
import type { BoardScope, DishStockChange, KitchenMenuItem, SizeStockChange } from '@/types/app';
import { usePolling } from '@hooks/usePolling';

// How often the menu refreshes on its own. Slower than the board: stock moves
// with orders, but a cook looking at this screen is changing it themselves.
const MENU_POLL_MS = 30000;

interface MenuState {
  items: KitchenMenuItem[];
  loading: boolean;
  refreshing: boolean;
  error: string | null;
}

// Keep a dish's object when the server says nothing changed, so a poll does
// not redraw every row.
const reuse = (previous: KitchenMenuItem[], next: KitchenMenuItem[]): KitchenMenuItem[] => {
  const known = new Map(previous.map(item => [item.id, item]));
  let changed = previous.length !== next.length;
  const merged = next.map((item, index) => {
    const old = known.get(item.id);
    if (old && old.updated_at === item.updated_at) {
      if (previous[index] !== old) {
        changed = true;
      }
      return old;
    }
    changed = true;
    return item;
  });
  return changed ? merged : previous;
};

// The branch's menu and the stock changes a cook makes to it. Not optimistic,
// like advancing an order: the row shows its own pending state and then the
// server's answer, which may differ from what was asked — "back in stock" on
// a dish counted down to zero is still sold out, and the row must say so.
export function useKitchenMenu(token: string | null, scope: BoardScope) {
  const [state, setState] = useState<MenuState>({ items: [], loading: true, refreshing: false, error: null });
  const [pending, setPending] = useState<ReadonlySet<string>>(new Set());
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});
  const generation = useRef(0);
  const scopeKey = `${scope.restaurantId}:${scope.locationId}`;

  useEffect(() => {
    generation.current += 1;
    setState({ items: [], loading: true, refreshing: false, error: null });
  }, [scopeKey]);

  const load = useCallback(async () => {
    if (!token || !scope.restaurantId) {
      return;
    }
    const mine = ++generation.current;
    try {
      const items = await fetchKitchenMenu(token, scope);
      if (mine === generation.current) {
        setState(current => {
          const merged = reuse(current.items, items);
          if (merged === current.items && !current.loading && !current.error) {
            return current;
          }
          return { ...current, items: merged, loading: false, error: null };
        });
      }
    } catch (error) {
      if (mine === generation.current) {
        setState(current => ({
          ...current,
          loading: false,
          error: error instanceof Error ? error.message : 'Could not load the menu.',
        }));
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, scopeKey]);

  usePolling(load, MENU_POLL_MS, Boolean(token && scope.restaurantId));

  const refresh = useCallback(async () => {
    setState(current => ({ ...current, refreshing: true }));
    await load();
    setState(current => ({ ...current, refreshing: false }));
  }, [load]);

  const apply = useCallback(
    async (item: KitchenMenuItem, send: () => Promise<KitchenMenuItem>): Promise<boolean> => {
      setPending(current => new Set(current).add(item.id));
      setErrors(({ [item.id]: _cleared, ...rest }) => rest);
      try {
        const updated = await send();
        setState(current => ({
          ...current,
          items: current.items.map(existing => (existing.id === updated.id ? updated : existing)),
        }));
        return true;
      } catch (error) {
        // The server's own sentence: a 404 here means the dish left this
        // branch's menu, which a cook should be told as it is.
        setErrors(current => ({
          ...current,
          [item.id]: error instanceof Error ? error.message : 'That did not save.',
        }));
        return false;
      } finally {
        setPending(current => {
          const rest = new Set(current);
          rest.delete(item.id);
          return rest;
        });
      }
    },
    [],
  );

  const updateDish = useCallback(
    (item: KitchenMenuItem, change: DishStockChange) =>
      token ? apply(item, () => updateDishStock(token, item.id, change, scope)) : Promise.resolve(false),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [token, scopeKey, apply],
  );

  const updateSize = useCallback(
    (item: KitchenMenuItem, sizeId: string, change: SizeStockChange) =>
      token ? apply(item, () => updateSizeStock(token, item.id, sizeId, change, scope)) : Promise.resolve(false),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [token, scopeKey, apply],
  );

  return { ...state, pending, errors, refresh, retry: load, updateDish, updateSize };
}
