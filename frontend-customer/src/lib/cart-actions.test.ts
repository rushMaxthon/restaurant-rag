import { describe, expect, it } from "vitest";

// The checkout hand-off, added with the "add more or check out?" flow.
import { planCartActions } from "./cart-actions";
import { applyCartActionsToCart } from "./bangkok-store";
import type { CartAction } from "./api";
import type { CartLine } from "./bangkok-store";
import type { CustomizationGroup, MenuItem } from "./bangkok-data";

/**
 * The client's half of the ordering agent contract: it receives identifiers
 * only (no name, no price) and must re-resolve every one of them against the
 * branch menu already on screen before it will touch the cart. These tests
 * are the cases that matter most: an id the server invented or that belongs
 * to another branch must never reach the cart, a "proposed" action must never
 * mutate anything on its own, and a drifted response shape (a missing status,
 * an "applied" clear) must read as "do nothing" rather than "do it anyway".
 */

const SPICE_GROUP: CustomizationGroup = {
  id: "group-spice",
  title: "Spice level",
  selection_type: "SINGLE",
  is_required: false,
  min_selection: 0,
  max_selection: 1,
  is_active: true,
  options: [
    { id: "opt-mild", name: "Mild", extra_price: "0", is_countable: false, is_active: true },
    { id: "opt-hot", name: "Hot", extra_price: "1.00", is_countable: false, is_active: true },
  ],
};

function makeItem(overrides: Partial<MenuItem> = {}): MenuItem {
  return {
    id: "item-pad-thai",
    restaurant_id: "restaurant-bangkok",
    restaurant_location_id: "loc-1",
    name: "Pad Thai",
    category: "Noodles",
    cuisine_type: "Thai",
    description: "",
    price: "12.00",
    is_veg: false,
    is_available: true,
    is_bestseller: false,
    image_url: null,
    rating: null,
    rating_count: 0,
    is_new: false,
    is_favorite: false,
    has_sizes: false,
    has_customizations: true,
    sizes: [],
    customization_groups: [SPICE_GROUP],
    ...overrides,
  };
}

const MENU: MenuItem[] = [makeItem()];

function makeAction(overrides: Partial<CartAction> = {}): CartAction {
  return {
    kind: "add",
    status: "applied",
    reason: "named",
    menu_item_id: "item-pad-thai",
    menu_item_size_id: null,
    selected_option_ids: [],
    quantity: 1,
    ...overrides,
  };
}

describe("planCartActions", () => {
  it("applies a named add and it appears in the cart", () => {
    const action = makeAction();
    const { next, dropped, proposals } = planCartActions([action], [], MENU);
    expect(dropped).toEqual([]);
    expect(proposals).toEqual([]);
    expect(next).toHaveLength(1);
    expect(next[0]).toMatchObject({ itemId: "item-pad-thai", quantity: 1, unitPrice: 12 });
  });

  it("drops an action whose menu_item_id isn't on this branch's menu", () => {
    const action = makeAction({ menu_item_id: "item-from-another-branch" });
    const { next, dropped } = planCartActions([action], [], MENU);
    expect(next).toEqual([]);
    expect(dropped).toEqual([action]);
  });

  it("drops an action whose option id isn't on the resolved item", () => {
    const action = makeAction({ selected_option_ids: ["opt-does-not-exist"] });
    const { next, dropped } = planCartActions([action], [], MENU);
    expect(next).toEqual([]);
    expect(dropped).toEqual([action]);
  });

  it("leaves a proposed action untouched — it never changes the cart", () => {
    const action = makeAction({ status: "proposed" });
    const { next, dropped, proposals } = planCartActions([action], [], MENU);
    expect(next).toEqual([]);
    expect(dropped).toEqual([]);
    expect(proposals).toEqual([action]);
  });

  it("treats a missing or null status as NOT applied", () => {
    const missing = { ...makeAction() } as CartAction;
    // @ts-expect-error simulating a drifted wire shape
    delete missing.status;
    const nullStatus = { ...makeAction(), status: null } as unknown as CartAction;

    const resultMissing = planCartActions([missing], [], MENU);
    expect(resultMissing.next).toEqual([]);
    expect(resultMissing.proposals).toEqual([]);
    expect(resultMissing.dropped).toEqual([missing]);

    const resultNull = planCartActions([nullStatus], [], MENU);
    expect(resultNull.next).toEqual([]);
    expect(resultNull.proposals).toEqual([]);
    expect(resultNull.dropped).toEqual([nullStatus]);
  });

  it("set_quantity sets the final quantity, not a delta", () => {
    const existing: CartLine = {
      lineId: "item-pad-thai--",
      itemId: "item-pad-thai",
      restaurantId: "restaurant-bangkok",
      restaurantName: undefined,
      restaurantLocationId: "loc-1",
      name: "Pad Thai",
      image_url: null,
      quantity: 3,
      unitPrice: 12,
      sizeId: undefined,
      sizeName: undefined,
      optionIds: [],
      addOnNames: [],
    };
    const action = makeAction({ kind: "set_quantity", quantity: 5 });
    const { next } = planCartActions([action], [existing], MENU);
    expect(next).toHaveLength(1);
    expect(next[0]?.quantity).toBe(5);
  });

  it("an applied clear is dropped — the server only ever proposes it", () => {
    const action = makeAction({ kind: "clear", status: "applied", menu_item_id: null });
    const cart: CartLine[] = [
      {
        lineId: "item-pad-thai--",
        itemId: "item-pad-thai",
        restaurantId: "restaurant-bangkok",
        restaurantName: undefined,
        restaurantLocationId: "loc-1",
        name: "Pad Thai",
        image_url: null,
        quantity: 1,
        unitPrice: 12,
        sizeId: undefined,
        sizeName: undefined,
        optionIds: [],
        addOnNames: [],
      },
    ];
    const { next, dropped } = planCartActions([action], cart, MENU);
    expect(next).toEqual(cart);
    expect(dropped).toEqual([action]);
  });
});

describe("applyCartActionsToCart (store-level idempotency)", () => {
  it("applies the same turn id only once", () => {
    const action = makeAction();
    const first = applyCartActionsToCart([], "turn-1", null, [action], MENU);
    expect(first.applied).toBe(true);
    expect(first.cart).toHaveLength(1);

    const second = applyCartActionsToCart(first.cart, "turn-1", "turn-1", [action], MENU);
    expect(second.applied).toBe(false);
    // Same cart, not a second Pad Thai line.
    expect(second.cart).toBe(first.cart);
    expect(second.cart).toHaveLength(1);
  });
});

describe("the checkout hand-off", () => {
  const checkout = (status: "applied" | "proposed"): CartAction => ({
    kind: "checkout", status, reason: "named", menu_item_id: null, menu_item_size_id: null, selected_option_ids: [], quantity: null,
  });

  it("proposed goes to proposals and changes nothing", () => {
    const result = planCartActions([checkout("proposed")], [], []);
    expect(result.proposals).toHaveLength(1);
    expect(result.next).toEqual([]);
  });

  it("applied is a drifted shape and is dropped", () => {
    const result = planCartActions([checkout("applied")], [], []);
    expect(result.dropped).toHaveLength(1);
    expect(result.proposals).toHaveLength(0);
  });
});

