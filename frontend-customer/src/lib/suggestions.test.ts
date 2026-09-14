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
    );

    expect(mined).toContain("Often ordered");
    expect(guess).toContain("Most people");
    // The whole point of `basis`: these must not read alike.
    expect(mined).not.toEqual(guess);
  });

  it("names the saving on a combo upgrade", () => {
    const copy = suggestionCopy(
      { kind: "up_sell", basis: "combo_upgrade", saving: "4.00" },
      "Curry Feast",
    );

    expect(copy).toContain("4.00");
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
