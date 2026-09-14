import { describe, expect, it } from "vitest";
import { cartLinesForRequest, suggestionCopy } from "./suggestions";

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
