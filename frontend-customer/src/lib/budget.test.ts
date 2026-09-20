/**
 * The craving chip that names a price says a true thing about this menu.
 *
 * It used to read "Under $15" — a literal, on storefronts priced in rupees,
 * dirhams and pounds. The number is now read off the menu, so these are the
 * questions that decides: is it actually most of the menu, is it a figure a
 * person would say, and does it stay quiet when there is not enough menu to
 * generalise from.
 */

import { describe, expect, it } from "vitest";

import { budgetChipAmount } from "./budget";

describe("budgetChipAmount", () => {
  it("is quiet when there are too few dishes to generalise", () => {
    // Three prices cannot describe a menu. No chip is better than a number
    // drawn from almost nothing.
    expect(budgetChipAmount([100, 150, 200])).toBeNull();
  });

  it("is quiet for an empty menu", () => {
    expect(budgetChipAmount([])).toBeNull();
  });

  it("covers most of the menu without covering all of it", () => {
    const prices = [80, 90, 100, 120, 145, 150, 180, 210, 260, 400];
    const budget = budgetChipAmount(prices)!;
    const under = prices.filter((p) => p <= budget).length;
    expect(under / prices.length).toBeGreaterThanOrEqual(0.6);
    expect(under).toBeLessThan(prices.length);
  });

  it("rounds to a figure someone would say out loud", () => {
    // 147 is arithmetic; 150 is an offer.
    expect(budgetChipAmount([100, 120, 140, 147, 160])).toBe(150);
  });

  it("uses a coarser step once the menu is expensive", () => {
    const budget = budgetChipAmount([400, 500, 600, 640, 900])!;
    expect(budget % 100).toBe(0);
  });

  it("uses a fine step on a cheap menu, so the chip is not the whole menu", () => {
    // Rounding 22 up to the nearest 50 would be "Under 50" on a menu whose
    // dearest dish is 30 — true, and useless.
    const budget = budgetChipAmount([10, 15, 18, 22, 30])!;
    expect(budget).toBeLessThan(30);
  });

  it("ignores prices that are zero, negative or not numbers", () => {
    // A row with no price set must not drag the figure down.
    const withJunk = budgetChipAmount([0, -5, Number.NaN, 100, 120, 140, 147, 160]);
    expect(withJunk).toBe(budgetChipAmount([100, 120, 140, 147, 160]));
  });

  it("does not care what order the menu arrives in", () => {
    const shuffled = [400, 80, 210, 100, 145, 90, 260, 120, 180, 150];
    const sorted = [...shuffled].sort((a, b) => a - b);
    expect(budgetChipAmount(shuffled)).toBe(budgetChipAmount(sorted));
  });
});
