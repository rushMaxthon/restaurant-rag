/**
 * How many of a dish are left, for every screen that shows a + button.
 *
 * The server is the rule (`backend/app/services/stock.py`): it refuses an
 * order for more than is left, and it decides who gets the last one. Nothing
 * here can oversell anything. What this is for is not making the customer
 * find that out at the very end — a stepper that stops at 3 and says why is
 * the same rule, told at the moment it is useful.
 *
 * `stock_quantity` is null when the restaurant does not count the dish, and
 * absent altogether from a server older than the feature. Both mean no
 * ceiling. Zero is a real count and means sold out.
 *
 * One count per dish, shared by its sizes — a pack of four and a pack of
 * eight draw on the same number — so everything here is asked per dish, never
 * per cart line.
 */

type Counted = { stock_quantity?: number | null | undefined };
type Sellable = Counted & { is_available: boolean };

/** At or under this many, the menu starts saying how many are left. */
const NEARLY_GONE = 5;

/** The count, or null when the dish is not counted. */
export function stockLeft(item: Counted | undefined): number | null {
  const left = item?.stock_quantity;
  return typeof left === "number" ? left : null;
}

export function isSoldOut(item: Counted | undefined): boolean {
  return stockLeft(item) === 0;
}

/** On sale right now: the owner has it switched on and there is one to sell. */
export function canBuy(item: Sellable | undefined): boolean {
  return Boolean(item?.is_available) && !isSoldOut(item);
}

/**
 * How many more this cart could take. Null is no ceiling.
 *
 * Floored at zero: the count can fall behind a cart that has sat open while
 * somebody else bought, and "minus two left" is not something to hand a
 * stepper.
 */
export function roomLeft(item: Counted | undefined, inCart: number): number | null {
  const left = stockLeft(item);
  return left === null ? null : Math.max(0, left - inCart);
}

/**
 * The few words beside a price, or nothing while there is plenty.
 *
 * "That is all N we have" exists for one moment: the cart holds the last of
 * them and the + has just gone dead. A button that stops working without a
 * word reads as a broken page.
 */
export function stockNote(item: Counted | undefined, inCart = 0): string | null {
  const left = stockLeft(item);
  if (left === null) return null;
  if (left === 0) return "Sold out";
  if (inCart >= left) return `That is all ${left} we have`;
  return left <= NEARLY_GONE ? `Only ${left} left` : null;
}

/** Everything of one dish in the cart, across sizes and extras. */
export function inCartOf(cart: { itemId: string; quantity: number }[], itemId: string): number {
  return cart.reduce((sum, line) => (line.itemId === itemId ? sum + line.quantity : sum), 0);
}
