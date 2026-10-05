import { describe, expect, it } from "vitest";

import { canBuy, heldFor, inCartOf, isSoldOut, roomLeft, stockLeft, stockNote } from "./stock";

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

  it("says out of stock at zero", () => {
    expect(stockNote(dish(0))).toBe("Out of stock");
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

describe("marked out of stock by hand", () => {
  const marked = (stock_quantity: number | null) => ({
    stock_quantity,
    out_of_stock: true,
    is_available: true,
  });

  it("is out of stock whatever the count says", () => {
    expect(isSoldOut(marked(null))).toBe(true);
    expect(isSoldOut(marked(40))).toBe(true);
    expect(canBuy(marked(40))).toBe(false);
  });

  it("leaves no room and says so", () => {
    expect(roomLeft(marked(40), 0)).toBe(0);
    expect(stockNote(marked(40))).toBe("Out of stock");
  });
});

describe("a size with its own count", () => {
  const four = { id: "four", stock_quantity: 2 };
  const eight = { id: "eight", stock_quantity: null };
  const pav = { id: "pav", stock_quantity: 10, is_available: true, sizes: [four, eight] };

  it("is counted on its own number, not the dish's", () => {
    expect(stockLeft(pav, four)).toBe(2);
    expect(stockLeft(pav, eight)).toBe(10);
  });

  it("can be gone while the dish is not", () => {
    const gone = { id: "four", stock_quantity: 0 };
    const dish = { ...pav, sizes: [gone, eight] };
    expect(isSoldOut(dish, gone)).toBe(true);
    expect(isSoldOut(dish, eight)).toBe(false);
    expect(isSoldOut(dish)).toBe(false);
  });

  it("puts the whole dish out of stock when every size is gone", () => {
    const dish = {
      id: "pav",
      stock_quantity: null,
      is_available: true,
      sizes: [
        { id: "a", stock_quantity: 0 },
        { id: "b", stock_quantity: 0 },
      ],
    };
    expect(isSoldOut(dish)).toBe(true);
    expect(canBuy(dish)).toBe(false);
  });

  it("ignores a size the owner switched off when asking that", () => {
    const dish = {
      id: "pav",
      stock_quantity: null,
      is_available: true,
      sizes: [
        { id: "a", stock_quantity: 0 },
        { id: "b", stock_quantity: 5, is_active: false },
      ],
    };
    expect(isSoldOut(dish)).toBe(true);
  });

  it("counts what the cart holds against the right number", () => {
    const cart = [
      { itemId: "pav", sizeId: "four", quantity: 2 },
      { itemId: "pav", sizeId: "eight", quantity: 3 },
      { itemId: "other", quantity: 9 },
    ];
    // The counted size: its own two lines' worth.
    expect(heldFor(cart, pav, four)).toBe(2);
    expect(roomLeft(pav, heldFor(cart, pav, four), four)).toBe(0);
    // The dish's count: the uncounted size only. The pack of four is
    // somebody else's tray.
    expect(heldFor(cart, pav, eight)).toBe(3);
    expect(roomLeft(pav, heldFor(cart, pav, eight), eight)).toBe(7);
  });

  it("is still marked out by hand on every size", () => {
    const dish = { ...pav, out_of_stock: true };
    expect(stockLeft(dish, four)).toBe(0);
    expect(stockLeft(dish, eight)).toBe(0);
  });
});
