import { describe, expect, it } from "vitest";

import { menuPhase } from "./menu-phase";

const settled = {
  failed: false,
  restaurantPending: false,
  hasBranch: true,
  menuPending: false,
  shown: 12,
};

describe("menuPhase", () => {
  it("is ready when dishes have arrived", () => {
    expect(menuPhase(settled)).toBe("ready");
  });

  it("is loading, not empty, while the menu has not been asked for yet", () => {
    // A query that is disabled, paused or not yet mounted reports neither
    // "loading" nor "error". That is still not an empty menu.
    expect(menuPhase({ ...settled, menuPending: true, shown: 0 })).toBe("loading");
    expect(
      menuPhase({
        ...settled,
        restaurantPending: true,
        hasBranch: false,
        menuPending: true,
        shown: 0,
      }),
    ).toBe("loading");
  });

  it("says it failed even though nothing behind the failure ever settles", () => {
    expect(
      menuPhase({
        failed: true,
        restaurantPending: true,
        hasBranch: false,
        menuPending: true,
        shown: 0,
      }),
    ).toBe("failed");
  });

  it("is empty only once the answer is in and holds nothing", () => {
    expect(menuPhase({ ...settled, shown: 0 })).toBe("empty");
  });

  it("does not wait forever on a restaurant with no branch to ask about", () => {
    expect(menuPhase({ ...settled, hasBranch: false, menuPending: true, shown: 0 })).toBe("empty");
  });
});
