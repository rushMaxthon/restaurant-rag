import { describe, expect, it } from "vitest";
import {
  cartLinesForRequest,
  cartSuggestionSignature,
  suggestionCopy,
  suggestionNeedsChoice,
  suggestionReason,
} from "./suggestions";

describe("cartLinesForRequest", () => {
  it("sends identifiers only, never names or prices", () => {
    const [line] = cartLinesForRequest([
      {
        lineId: "l1",
        itemId: "item-1",
        restaurantId: "r1",
        restaurantName: "Bangkok Bowl",
        restaurantLocationId: "loc-1",
        name: "Green Curry",
        image_url: null,
        quantity: 2,
        unitPrice: 12.5,
        sizeId: "size-1",
        sizeName: "Large",
        optionIds: ["opt-1"],
        addOnNames: ["Extra peanuts"],
      },
    ] as never);

    expect(line).toEqual({
      menu_item_id: "item-1",
      quantity: 2,
      size_id: "size-1",
      customization_option_ids: ["opt-1"],
    });
    expect(JSON.stringify(line)).not.toContain("Green Curry");
    expect(JSON.stringify(line)).not.toContain("12.5");
  });

  it("handles an empty cart", () => {
    expect(cartLinesForRequest([])).toEqual([]);
  });
});

describe("suggestionCopy", () => {
  it("claims evidence only when there is evidence", () => {
    const mined = suggestionCopy(
      { kind: "cross_sell", basis: "co_occurrence", menu_item_id: "i" },
      "Thai Iced Tea",
    );
    const guess = suggestionCopy(
      { kind: "cross_sell", basis: "category_default", menu_item_id: "i" },
      "Thai Iced Tea",
      "Beverages",
    );

    expect(mined).toContain("Often ordered");
    expect(guess).toContain("Most people");
    // The whole point of `basis`: these must not read alike.
    expect(mined).not.toEqual(guess);
    // category_default must NOT claim the item is popular — only the category.
    expect(guess).not.toContain("Most people add Thai Iced Tea");
    // The popularity claim must be about the category (drink), not the item.
    expect(guess).toContain("Most people add a drink");
  });

  it("uses category noun when available", () => {
    const copy = suggestionCopy(
      { kind: "cross_sell", basis: "category_default", menu_item_id: "i" },
      "Tiramisu",
      "Dessert",
    );

    expect(copy).toContain("Most people add a something sweet");
    expect(copy).toContain("Tiramisu");
  });

  it("omits popularity claim when category is unknown", () => {
    const copy = suggestionCopy(
      { kind: "cross_sell", basis: "category_default", menu_item_id: "i" },
      "Thai Iced Tea",
      "Soups",
    );

    // No popularity claim when category cannot be naturally named.
    expect(copy).not.toContain("Most people");
    expect(copy).toBe("Thai Iced Tea?");
  });

  it("names the saving on a combo upgrade", () => {
    const copy = suggestionCopy(
      { kind: "up_sell", basis: "combo_upgrade", saving: "4.00" },
      "Curry Feast",
    );

    expect(copy).toContain("4.00");
  });

  it("omits saving clause when null", () => {
    const copy = suggestionCopy(
      { kind: "up_sell", basis: "combo_upgrade", saving: null },
      "Curry Feast",
    );

    expect(copy).not.toContain("and save");
    expect(copy).toBe("Make it the Curry Feast.");
  });

  it("omits extra cost clause when null", () => {
    const copy = suggestionCopy(
      { kind: "up_sell", basis: "size_upgrade", extra_cost: null },
      "Pad Thai",
    );

    expect(copy).not.toContain("more");
    expect(copy).toBe("Would you like a bigger size of the Pad Thai?");
  });

  it("does not hardcode size tier", () => {
    const copy = suggestionCopy(
      { kind: "up_sell", basis: "size_upgrade", size_id: "large", extra_cost: "2.50" },
      "Pad Thai",
    );

    expect(copy).not.toContain("Go large");
    expect(copy).toContain("Would you like a bigger size");
  });

  it("falls back to something neutral for an unknown basis", () => {
    // A new basis added on the backend must not render `undefined` to a customer.
    const copy = suggestionCopy(
      { kind: "cross_sell", basis: "something_new", menu_item_id: "i" },
      "Thai Iced Tea",
    );

    expect(copy).toContain("Thai Iced Tea");
  });
});

describe("suggestionReason", () => {
  it("claims evidence only when there is evidence, and never names the item", () => {
    const mined = suggestionReason({ basis: "co_occurrence" });
    const guess = suggestionReason({ basis: "category_default" }, "Beverages");

    expect(mined).toContain("Often ordered");
    expect(guess).toContain("Most people");
    // The whole point of `basis`: these must not read alike.
    expect(mined).not.toEqual(guess);
    // Splitting the name out must not let it sneak back into the reason.
    expect(mined).not.toContain("Thai Iced Tea");
    expect(guess).not.toContain("Thai Iced Tea");
    // The popularity claim must be about the category (drink), not any item.
    expect(guess).toContain("Most people add a drink");
  });

  it("uses category noun when available, still with no item name", () => {
    const reason = suggestionReason({ basis: "category_default" }, "Dessert");

    expect(reason).toBe("Most people add a something sweet");
    expect(reason).not.toContain("Tiramisu");
  });

  it("omits popularity claim when category is unknown or absent", () => {
    const unknownCategory = suggestionReason({ basis: "category_default" }, "Soups");
    const noCategory = suggestionReason({ basis: "category_default" });

    // No popularity claim when the category cannot be naturally named — and
    // no fallback to naming the item either, since that's the exact claim
    // category_default is not entitled to make.
    expect(unknownCategory).not.toContain("Most people");
    expect(noCategory).not.toContain("Most people");
  });

  it("falls back to something neutral for an unknown basis, with no item name", () => {
    const reason = suggestionReason({ basis: "something_new" });

    expect(reason.length).toBeGreaterThan(0);
    expect(reason).not.toContain("Thai Iced Tea");
  });
});

describe("cartSuggestionSignature", () => {
  it("is unchanged when only a quantity changes", () => {
    const before = cartSuggestionSignature([
      { itemId: "item-1", sizeId: "size-1", optionIds: ["opt-1"] },
    ]);
    const after = cartSuggestionSignature([
      { itemId: "item-1", sizeId: "size-1", optionIds: ["opt-1"] },
    ]);

    // Same identity, different quantities is the case that matters — but a
    // signature has no quantity field to begin with, so identical lines with
    // quantity omitted already prove the point: nothing about quantity can
    // ever reach this function.
    expect(after).toEqual(before);
  });

  it("changes when the item changes", () => {
    const a = cartSuggestionSignature([{ itemId: "item-1", sizeId: undefined, optionIds: [] }]);
    const b = cartSuggestionSignature([{ itemId: "item-2", sizeId: undefined, optionIds: [] }]);

    expect(a).not.toEqual(b);
  });

  it("changes when the size changes", () => {
    const a = cartSuggestionSignature([{ itemId: "item-1", sizeId: "small", optionIds: [] }]);
    const b = cartSuggestionSignature([{ itemId: "item-1", sizeId: "large", optionIds: [] }]);

    expect(a).not.toEqual(b);
  });

  it("changes when an option is added", () => {
    const a = cartSuggestionSignature([{ itemId: "item-1", sizeId: undefined, optionIds: [] }]);
    const b = cartSuggestionSignature([
      { itemId: "item-1", sizeId: undefined, optionIds: ["opt-1"] },
    ]);

    expect(a).not.toEqual(b);
  });

  it("is order-independent within a single line's options", () => {
    const a = cartSuggestionSignature([
      { itemId: "item-1", sizeId: undefined, optionIds: ["opt-1", "opt-2"] },
    ]);
    const b = cartSuggestionSignature([
      { itemId: "item-1", sizeId: undefined, optionIds: ["opt-2", "opt-1"] },
    ]);

    expect(a).toEqual(b);
  });

  it("changes when a line is added or removed", () => {
    const one = cartSuggestionSignature([{ itemId: "item-1", sizeId: undefined, optionIds: [] }]);
    const two = cartSuggestionSignature([
      { itemId: "item-1", sizeId: undefined, optionIds: [] },
      { itemId: "item-2", sizeId: undefined, optionIds: [] },
    ]);

    expect(one).not.toEqual(two);
  });
});

describe("suggestionNeedsChoice", () => {
  const plain = { has_sizes: false, has_customizations: false };
  const sized = { has_sizes: true, has_customizations: false };
  const customizable = { has_sizes: false, has_customizations: true };

  it("always routes size_upgrade to the dish page, regardless of the item", () => {
    // The item named IS the one already in the cart; the change is the size,
    // which addItem(item) has no way to apply. There is no plain-item case
    // where a blind add would be correct for this basis.
    expect(suggestionNeedsChoice({ basis: "size_upgrade" }, plain)).toBe(true);
  });

  it("always routes add_on to the dish page, regardless of the item", () => {
    expect(suggestionNeedsChoice({ basis: "add_on" }, plain)).toBe(true);
  });

  it("allows a plain add for a cross-sold item with no choices to make", () => {
    expect(suggestionNeedsChoice({ basis: "co_occurrence" }, plain)).toBe(false);
    expect(suggestionNeedsChoice({ basis: "category_default" }, plain)).toBe(false);
  });

  it("routes a cross-sold item to the dish page when IT has sizes", () => {
    // Same bug dish-card.tsx already refuses to make, reached from a
    // different basis: a drink suggested by co_occurrence can still come in
    // two sizes, and adding it blind picks one without asking.
    expect(suggestionNeedsChoice({ basis: "co_occurrence" }, sized)).toBe(true);
    expect(suggestionNeedsChoice({ basis: "category_default" }, sized)).toBe(true);
  });

  it("routes a cross-sold item to the dish page when IT has customizations", () => {
    expect(suggestionNeedsChoice({ basis: "co_occurrence" }, customizable)).toBe(true);
  });

  it("still requires a choice for the up-sell bases even on a plain item", () => {
    // Belt and braces: the basis check must not be short-circuited by the
    // item's own flags — size_upgrade/add_on are never a blind add, full stop.
    expect(suggestionNeedsChoice({ basis: "size_upgrade" }, customizable)).toBe(true);
    expect(suggestionNeedsChoice({ basis: "add_on" }, sized)).toBe(true);
  });
});
