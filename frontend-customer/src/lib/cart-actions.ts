import type { MenuItem, MenuSize } from "@/lib/bangkok-data";
import type { CartLine } from "@/lib/bangkok-store";
import type { CartAction } from "@/lib/api";
import { activeOptions, unitPriceFor, visibleGroups } from "@/lib/customization";

/**
 * Turns the ordering agent's `cart_actions` into a new cart, pure and
 * side-effect free so the rules can be tested without React or the store.
 *
 * The server never sends names or prices — only ids — so every action is
 * re-resolved against the branch menu already loaded on the client. An id
 * that does not resolve (wrong branch, item pulled since the agent looked,
 * a stale size/option) is never silently ignored: it is reported back in
 * `dropped` so the caller can tell the customer something was left out,
 * mirroring "the LLM never invents data" — the client never invents a menu
 * item either.
 *
 * `status` gates everything: only "applied" changes the cart. A `status`
 * that is missing, null, or anything other than the two known values is
 * treated as NOT applied — a drifted response shape must never be read as
 * permission to mutate a real order. `clear` is a special case of that same
 * rule: the server only ever proposes it (it is a `reason: "destructive"`
 * action by construction), so an "applied" clear is itself a drifted shape
 * and is dropped rather than trusted.
 */
export type PlanCartActionsResult = {
  next: CartLine[];
  dropped: CartAction[];
  proposals: CartAction[];
};

function findMenuItem(menu: MenuItem[], id: string | null): MenuItem | undefined {
  return id ? menu.find((item) => item.id === id) : undefined;
}

/** undefined = no size requested; null = a size was requested but isn't on the item. */
function findSize(item: MenuItem, sizeId: string | null): MenuSize | undefined | null {
  if (!sizeId) return undefined;
  return item.sizes.find((size) => size.id === sizeId) ?? null;
}

function optionsExistOnItem(
  item: MenuItem,
  size: MenuSize | undefined,
  optionIds: string[],
): boolean {
  const valid = new Set(
    visibleGroups(item, size).flatMap((group) => activeOptions(group).map((o) => o.id)),
  );
  return optionIds.every((id) => valid.has(id));
}

/**
 * Resolves what an add/remove/set_quantity action targets against the loaded
 * menu, or null when any part of it (item, size, or an option) isn't on this
 * branch's menu.
 */
function resolveTarget(
  action: CartAction,
  menu: MenuItem[],
): { item: MenuItem; size: MenuSize | undefined } | null {
  const item = findMenuItem(menu, action.menu_item_id);
  if (!item) return null;
  const size = findSize(item, action.menu_item_size_id);
  if (size === null) return null;
  if (!optionsExistOnItem(item, size, action.selected_option_ids)) return null;
  return { item, size };
}

/**
 * Mirrors `addItem`'s signature scheme in bangkok-store.tsx exactly, so a
 * chat-added line merges with an identical hand-added one instead of the two
 * sitting side by side as "different" lines. The agent never sends portions
 * (half/whole), so every option it names sits on the whole item — the same
 * default `addItem` uses when a caller omits `optionPortions`.
 */
function lineSignature(itemId: string, sizeId: string | undefined, optionIds: string[]): string {
  return `${itemId}-${sizeId ?? ""}-${optionIds
    .slice()
    .sort()
    .map((id) => `${id}:WHOLE`)
    .join("-")}`;
}

function applyAdd(
  cart: CartLine[],
  action: CartAction,
  item: MenuItem,
  size: MenuSize | undefined,
): CartLine[] {
  const optionIds = action.selected_option_ids;
  const names = visibleGroups(item, size)
    .flatMap((group) => activeOptions(group))
    .filter((option) => optionIds.includes(option.id))
    .map((option) => option.name);
  const unitPrice = unitPriceFor(item, size, optionIds);
  const signature = lineSignature(item.id, size?.id, optionIds);
  const addQty = action.quantity && action.quantity > 0 ? action.quantity : 1;

  const existingIndex = cart.findIndex((line) => line.lineId === signature);
  if (existingIndex !== -1) {
    return cart.map((line, i) =>
      i === existingIndex ? { ...line, quantity: line.quantity + addQty } : line,
    );
  }
  const newLine: CartLine = {
    lineId: signature,
    itemId: item.id,
    restaurantId: item.restaurant_id,
    restaurantName: undefined,
    restaurantLocationId: item.restaurant_location_id,
    name: item.name,
    image_url: item.image_url,
    quantity: addQty,
    unitPrice,
    sizeId: size?.id,
    sizeName: size?.name,
    optionIds,
    addOnNames: names,
    optionPortions: {},
  };
  return [...cart, newLine];
}

// Only ever applied when the server found exactly one match, so every line
// for this item is the right thing to drop — there is nothing left to
// disambiguate by size or options.
function applyRemove(cart: CartLine[], action: CartAction): CartLine[] {
  return cart.filter((line) => line.itemId !== action.menu_item_id);
}

function applySetQuantity(
  cart: CartLine[],
  action: CartAction,
  item: MenuItem,
  size: MenuSize | undefined,
): CartLine[] {
  // Nothing to set a line to; leave the cart untouched rather than guess.
  if (action.quantity == null) return cart;
  const signature = lineSignature(item.id, size?.id, action.selected_option_ids);
  const index = cart.findIndex((line) => line.lineId === signature);
  if (index === -1) return cart;
  if (action.quantity <= 0) return cart.filter((_, i) => i !== index);
  const finalQuantity = action.quantity;
  return cart.map((line, i) => (i === index ? { ...line, quantity: finalQuantity } : line));
}

export function planCartActions(
  actions: CartAction[],
  cart: CartLine[],
  menu: MenuItem[],
): PlanCartActionsResult {
  let next = cart;
  const dropped: CartAction[] = [];
  const proposals: CartAction[] = [];

  for (const action of actions) {
    // A checkout hand-off is not a cart change: proposed, the screen shows a
    // "Go to checkout" card; applied would be a drifted shape, dropped.
    if (action.kind === "checkout") {
      if (action.status === "proposed") proposals.push(action);
      else dropped.push(action);
      continue;
    }
    if (action.kind === "clear") {
      // See the module docstring: an "applied" clear is a drifted shape,
      // never a real instruction, so it is dropped rather than trusted.
      if (action.status === "proposed") proposals.push(action);
      else dropped.push(action);
      continue;
    }

    const target = resolveTarget(action, menu);
    if (!target) {
      dropped.push(action);
      continue;
    }

    if (action.status === "proposed") {
      proposals.push(action);
      continue;
    }
    if (action.status !== "applied") {
      // Missing/null/unrecognized status: never apply on a drifted shape.
      dropped.push(action);
      continue;
    }

    if (action.kind === "add") {
      next = applyAdd(next, action, target.item, target.size);
    } else if (action.kind === "remove") {
      next = applyRemove(next, action);
    } else if (action.kind === "set_quantity") {
      next = applySetQuantity(next, action, target.item, target.size);
    }
  }

  return { next, dropped, proposals };
}
