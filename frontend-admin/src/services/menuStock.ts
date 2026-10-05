/**
 * The "Stock left" box on a dish, as the server wants it.
 *
 * Empty is null - stop counting - and is deliberately NOT read as zero. An
 * owner who clears the box means "I do not count this dish"; turning that
 * into 0 would mark it sold out and take it off sale. The two are different
 * facts and the whole feature rests on keeping them apart.
 */
export function parseStock(value: string): number | null {
  const typed = value.trim();
  if (typed === "") return null;
  // Digits only: "12.5" loaves and "-3" loaves are both typing mistakes, and
  // parseInt would quietly make 12 and NaN of them.
  if (!/^\d+$/.test(typed)) {
    throw new Error("Stock left must be a whole number, or empty if you do not count this dish.");
  }
  return Number.parseInt(typed, 10);
}

/**
 * What to send about stock when a dish is saved: the new count, or nothing.
 *
 * Nothing, when the owner did not touch the box. The count is not the
 * editor's to keep - every order moves it. An editor opened at 10, left open
 * while three sold, and saved to fix a spelling would otherwise write 10 back
 * and put three loaves on the shelf that are already in somebody's bag. The
 * server keeps the stored count when the field is left out, so leaving it out
 * is how "I changed something else" is said.
 *
 * `loaded` is what the box held when the dish was opened, and null for a dish
 * that is being created - there is nothing stored to keep, so whatever is
 * typed is sent.
 */
export function stockChange(
  typed: string,
  loaded: string | null,
): { stock_quantity?: number | null } {
  // Parsed either way, so a box holding "ten" is refused even when untouched.
  const next = parseStock(typed);
  if (loaded !== null && typed.trim() === loaded.trim()) return {};
  return { stock_quantity: next };
}

/**
 * The same rule as `stockChange`, for any optional count on a dish or a size:
 * the daily refill amount, a size's own stock. Sent only when the box was
 * changed, under whatever name the server knows it by.
 */
export function countChange<Key extends string>(
  key: Key,
  typed: string,
  loaded: string | null,
): Partial<Record<Key, number | null>> {
  const next = parseStock(typed);
  if (loaded !== null && typed.trim() === loaded.trim()) return {};
  return { [key]: next } as Partial<Record<Key, number | null>>;
}

/** A count from the server, as the text an input holds. Null is an empty box. */
export function countText(value: number | null | undefined): string {
  return value == null ? "" : String(value);
}

/**
 * Whether a dish can be ordered, as one of three answers an owner acts on.
 *
 * "out" covers both ways of being out: marked by hand, or counted down to
 * zero. They need different fixes - untick a box, or type a number - but they
 * look the same to a customer and belong under one label in a list.
 */
export function stockState(item: {
  out_of_stock?: boolean;
  stock_quantity?: number | null;
}): "out" | "counted" | "uncounted" {
  if (item.out_of_stock || item.stock_quantity === 0) return "out";
  return item.stock_quantity == null ? "uncounted" : "counted";
}
