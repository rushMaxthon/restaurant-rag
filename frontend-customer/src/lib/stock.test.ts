import { describe, expect, it } from "vitest";

import { canBuy, inCartOf, isSoldOut, roomLeft, stockLeft, stockNote } from "./stock";

const dish = (stock_quantity: number | null | undefined, is_available = true) => ({
  stock_quantity,
  is_available,
});

describe("stockLeft", () => {
  it("is nothing for a dish nobody counts", () => {
    expect(stockLeft(dish(null))).toBeNull();
    // A server older than the feature sends no field at all. Still unlimited.
    expect(stockLeft(dish(undefined))).toBeNull();
  });

  it("is the count, and zero is a count", () => {
    expect(stockLeft(dish(7))).toBe(7);
    expect(stockLeft(dish(0))).toBe(0);
  });
});

describe("isSoldOut and canBuy", () => {
  it("is sold out at zero and only at zero", () => {
    expect(isSoldOut(dish(0))).toBe(true);
    expect(isSoldOut(dish(1))).toBe(false);
    expect(isSoldOut(dish(null))).toBe(false);
  });

  it("cannot be bought when sold out, or when the owner switched it off", () => {
    expect(canBuy(dish(3))).toBe(true);
    expect(canBuy(dish(null))).toBe(true);
    expect(canBuy(dish(0))).toBe(false);
    expect(canBuy(dish(3, false))).toBe(false);
  });
});

describe("roomLeft", () => {
  it("has no ceiling for a dish nobody counts", () => {
    expect(roomLeft(dish(null), 50)).toBeNull();
  });

  it("is what is left after what the cart already holds", () => {
    expect(roomLeft(dish(5), 0)).toBe(5);
    expect(roomLeft(dish(5), 3)).toBe(2);
    expect(roomLeft(dish(5), 5)).toBe(0);
  });

  it("never goes below zero when the count fell behind the cart", () => {
    // Somebody else bought three while this cart sat open.
    expect(roomLeft(dish(2), 5)).toBe(0);
  });
});

describe("stockNote", () => {
  it("says nothing while there is plenty", () => {
    expect(stockNote(dish(null))).toBeNull();
    expect(stockNote(dish(40))).toBeNull();
  });

  it("says how many when it is nearly gone", () => {
    expect(stockNote(dish(5))).toBe("Only 5 left");
    expect(stockNote(dish(1))).toBe("Only 1 left");
  });

  it("says sold out at zero", () => {
    expect(stockNote(dish(0))).toBe("Sold out");
  });

  it("says the cart holds the last of them, so a dead + button explains itself", () => {
    expect(stockNote(dish(3), 3)).toBe("That is all 3 we have");
    expect(stockNote(dish(40), 40)).toBe("That is all 40 we have");
  });
});

describe("inCartOf", () => {
  it("adds up every line of the dish, whatever its size or extras", () => {
    const cart = [
      { itemId: "a", quantity: 2 },
      { itemId: "b", quantity: 1 },
      { itemId: "a", quantity: 3 },
    ];
    expect(inCartOf(cart, "a")).toBe(5);
    expect(inCartOf(cart, "c")).toBe(0);
  });
});
