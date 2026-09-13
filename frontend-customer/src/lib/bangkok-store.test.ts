import { describe, expect, it } from "vitest";
import { cartConflictsWith } from "./bangkok-store";

/**
 * One order, one kitchen.
 *
 * The concierge answers across the whole marketplace, so it will happily
 * recommend Luigi's Margherita Pizza inside an app branded Bangkok Bowl. The
 * dish page opened fine — it fetches by id — but checkout sent the app's own
 * restaurant, and the order came back:
 *
 *   400  One or more menu items were not found for this restaurant
 *
 * after the customer had done all the work. The cart scope rule was right; the
 * app simply never checked it, so this is the check.
 */

const BANGKOK = "restaurant-bangkok";
const LUIGIS = "restaurant-luigis";

const line = (restaurantId: string) => ({ restaurantId });

describe("cartConflictsWith", () => {
  it("lets anything into an empty cart", () => {
    expect(cartConflictsWith([], LUIGIS)).toBe(false);
  });

  it("lets a dish from the same restaurant in", () => {
    expect(cartConflictsWith([line(BANGKOK)], BANGKOK)).toBe(false);
  });

  it("catches the dish from another kitchen", () => {
    // The exact case: a Luigi's pizza reached from chat, added to a Bangkok
    // Bowl cart, rejected at checkout.
    expect(cartConflictsWith([line(BANGKOK)], LUIGIS)).toBe(true);
  });

  it("judges by the first line, since the cart can only ever hold one kitchen", () => {
    expect(cartConflictsWith([line(LUIGIS), line(LUIGIS)], LUIGIS)).toBe(false);
    expect(cartConflictsWith([line(LUIGIS), line(LUIGIS)], BANGKOK)).toBe(true);
  });

  it("does not block on a line that never recorded its restaurant", () => {
    // Lines saved before the field existed are still in people's localStorage.
    // Treating a missing id as a conflict would strand those carts entirely.
    expect(cartConflictsWith([line("")], BANGKOK)).toBe(false);
  });
});
