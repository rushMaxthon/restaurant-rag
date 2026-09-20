/**
 * A budget worth offering a customer, read off the menu they are looking at.
 *
 * The home page's craving chips used to include a literal "Under $15", which
 * on a menu priced in rupees was wrong twice: the symbol, and the amount. It
 * also sent "Something good under $15" to the concierge, which would then
 * answer about money nobody charges.
 *
 * Converting fifteen dollars into rupees would not fix it — it invents a
 * figure this kitchen never chose. So the number comes from the menu: a round
 * amount that most of the dishes fall under, which is a true statement about
 * whatever menu it is given, in whatever currency that menu is priced in.
 */

/** Where to put the line: most of the menu, not nearly all of it. */
const SHARE_UNDER = 0.66;

/**
 * Rounded to something a person would say out loud. A chip reading "Under
 * ₹147" is arithmetic; "Under ₹150" is an offer.
 */
function stepFor(amount: number): number {
  if (amount >= 500) {
    return 100;
  }
  if (amount >= 100) {
    return 50;
  }
  return 5;
}

export function budgetChipAmount(prices: number[]): number | null {
  const sorted = prices.filter((price) => Number.isFinite(price) && price > 0).sort((a, b) => a - b);
  // Too few dishes to say anything general about the menu. The chip is then
  // left out entirely rather than shown with a number drawn from two prices.
  if (sorted.length < 4) {
    return null;
  }
  const at = sorted[Math.floor(sorted.length * SHARE_UNDER)] ?? 0;
  if (at <= 0) {
    return null;
  }
  const step = stepFor(at);
  return Math.ceil(at / step) * step;
}
