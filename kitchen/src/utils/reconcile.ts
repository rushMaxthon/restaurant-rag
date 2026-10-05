import type { KitchenOrder } from '@/types/app';

// Whether a refetched order is the one already on screen. `updated_at` moves
// on every server-side change; without it (an old payload, a test fixture)
// the comparison falls back to the whole row.
const sameOrder = (a: KitchenOrder, b: KitchenOrder): boolean => {
  if (a.id !== b.id || a.status !== b.status || (a.completed_at ?? null) !== (b.completed_at ?? null)) {
    return false;
  }
  if (a.updated_at && b.updated_at) {
    return a.updated_at === b.updated_at;
  }
  return JSON.stringify(a) === JSON.stringify(b);
};

// A poll's rows with every unchanged order swapped for the object already on
// screen — and the previous ARRAY itself when nothing changed at all.
//
// This is what keeps a 6-second poll cheap. Fresh JSON is all new objects, so
// without it every poll re-rendered every ticket on the board even when the
// kitchen was idle; with it, an idle poll changes no state and renders nothing,
// and a busy one re-renders only the tickets that actually moved.
export const reuseUnchanged = (
  previous: readonly KitchenOrder[],
  next: readonly KitchenOrder[],
): KitchenOrder[] => {
  const known = new Map(previous.map(order => [order.id, order]));
  let changed = previous.length !== next.length;
  const merged = next.map((order, index) => {
    const existing = known.get(order.id);
    if (existing && sameOrder(existing, order)) {
      if (previous[index] !== existing) {
        changed = true;
      }
      return existing;
    }
    changed = true;
    return order;
  });
  return changed ? merged : (previous as KitchenOrder[]);
};
