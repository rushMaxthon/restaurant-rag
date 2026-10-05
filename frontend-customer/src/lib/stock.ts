/**
 * Whether a dish can be had, and how many, for every screen with a + button.
 *
 * The server is the rule (`backend/app/services/stock.py`): it refuses an
 * order for more than is left, and it decides who gets the last one. Nothing
 * here can oversell anything. What this is for is not making the customer
 * find that out at the very end — a stepper that stops at 3 and says why is
 * the same rule, told at the moment it is useful.
 *
 * Three ways a dish on the menu can be unavailable, and one way it can be
 * limited:
 *
 *  - `out_of_stock` — the owner marked it by hand. Nobody need be counting.
 *  - `stock_quantity: 0` — counted, and none left.
 *  - a SIZE with `stock_quantity: 0` — that size is gone; others may not be.
 *  - `stock_quantity: n` — n left, on the dish or on a size.
 *
 * `stock_quantity` is null when nothing is being counted, and absent
 * altogether from a server older than the feature. Both mean no ceiling.
 *
 * **Which count a line draws on.** A size that carries its own number is its
 * own count. A size that does not draws on the dish's, one per unit. So a cart
 * line is asked about with its size, and the answer names the right number —
 * the same split the server makes, or the two would disagree about a pack.
 */

type Counted = { stock_quantity?: number | null | undefined };
type Size = Counted & { id: string; is_active?: boolean };
type Dish = Counted & {
  id?: string;
  out_of_stock?: boolean | undefined;
  sizes?: Size[] | undefined;
};
type Sellable = Dish & { is_available: boolean };
type Line = { itemId: string; quantity: number; sizeId?: string | undefined };

/** At or under this many, the menu starts saying how many are left. */
const NEARLY_GONE = 5;

function own(counted: Counted | undefined): number | null {
  const left = counted?.stock_quantity;
  return typeof left === "number" ? left : null;
}

/** A size that keeps a count of its own, rather than drawing on the dish's. */
function isCountedSize(size: Counted | undefined): boolean {
  return own(size) !== null;
}

/**
 * How many are left of this dish — or of this size of it — or null for no
 * ceiling.
 *
 * Marked out of stock by hand is zero whatever any count says: the person
 * standing next to the tray outranks the number.
 */
export function stockLeft(item: Dish | undefined, size?: Size | undefined): number | null {
  if (!item) return null;
  if (item.out_of_stock) return 0;
  return isCountedSize(size) ? own(size) : own(item);
}

/**
 * Nothing of this to sell right now.
 *
 * Asked about a dish with no size named, a dish whose every size is gone is
 * out of stock too: there is nothing left on its page to choose.
 */
export function isSoldOut(item: Dish | undefined, size?: Size | undefined): boolean {
  if (stockLeft(item, size) === 0) return true;
  if (size || !item) return false;
  const sizes = (item.sizes ?? []).filter((each) => each.is_active !== false);
  return sizes.length > 0 && sizes.every((each) => stockLeft(item, each) === 0);
}

/** On sale right now: the owner has it switched on and there is one to sell. */
export function canBuy(item: Sellable | undefined, size?: Size | undefined): boolean {
  return Boolean(item?.is_available) && !isSoldOut(item, size);
}

/** Everything of one dish in the cart, across sizes and extras. */
export function inCartOf(cart: Line[], itemId: string): number {
  return cart.reduce((sum, line) => (line.itemId === itemId ? sum + line.quantity : sum), 0);
}

/**
 * How much of ONE count the cart already holds.
 *
 * For a size with its own count: the lines of that size. Otherwise the dish's
 * count, which is every line of the dish except those of a size that keeps
 * its own — they are somebody else's tray.
 */
export function heldFor(cart: Line[], item: Dish | undefined, size?: Size | undefined): number {
  const id = item?.id;
  if (!id) return 0;
  if (isCountedSize(size)) {
    return cart.reduce(
      (sum, line) => (line.itemId === id && line.sizeId === size?.id ? sum + line.quantity : sum),
      0,
    );
  }
  const ownCount = new Set((item?.sizes ?? []).filter(isCountedSize).map((each) => each.id));
  return cart.reduce(
    (sum, line) =>
      line.itemId === id && !(line.sizeId && ownCount.has(line.sizeId)) ? sum + line.quantity : sum,
    0,
  );
}

/**
 * How many more this cart could take. Null is no ceiling.
 *
 * Floored at zero: the count can fall behind a cart that has sat open while
 * somebody else bought, and "minus two left" is not something to hand a
 * stepper.
 */
export function roomLeft(
  item: Dish | undefined,
  held: number,
  size?: Size | undefined,
): number | null {
  const left = stockLeft(item, size);
  return left === null ? null : Math.max(0, left - held);
}

/**
 * The few words beside a price, or nothing while there is plenty.
 *
 * "That is all N we have" exists for one moment: the cart holds the last of
 * them and the + has just gone dead. A button that stops working without a
 * word reads as a broken page.
 */
export function stockNote(
  item: Dish | undefined,
  held = 0,
  size?: Size | undefined,
): string | null {
  if (isSoldOut(item, size)) return "Out of stock";
  const left = stockLeft(item, size);
  if (left === null) return null;
  if (held >= left) return `That is all ${left} we have`;
  return left <= NEARLY_GONE ? `Only ${left} left` : null;
}
