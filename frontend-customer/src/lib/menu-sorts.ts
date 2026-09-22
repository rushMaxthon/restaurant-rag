/**
 * Which sorts a menu can honestly offer.
 *
 * "Top rated" was in the list whatever the menu held, and not one of this
 * restaurant's 136 dishes has a rating — so choosing it compared 0 against 0
 * for every pair and reordered nothing. A control that promises an ordering
 * the data cannot provide is worse than one fewer control.
 *
 * Here rather than inside the component so the rule is stated once and can be
 * checked without rendering anything.
 */

export type SortOption = { value: string; label: string };

/** A dish, as far as this decision is concerned. */
type Rated = { rating?: string | number | null };

export function sortsFor(all: SortOption[], items: readonly Rated[]): SortOption[] {
  const anythingRated = items.some((item) => Number(item.rating ?? 0) > 0);
  return anythingRated ? [...all] : all.filter((option) => option.value !== "rating");
}
