import { describe, expect, it } from "vitest";
import {
  activeOptions,
  activeSizes,
  requiresChoosing,
  selectionProblem,
  portionLabel,
  splitSummary,
  unitPriceFor,
  visibleGroups,
  canPickMore,
  selectionHint,
} from "./customization";
import type { CustomizationGroup, CustomizationOption, MenuItem, MenuSize } from "./bangkok-data";

/**
 * The rules for sized and customisable items, mirrored from the backend.
 *
 * `MENU_ITEM_CUSTOMIZATION_FLOW.md` is the authority and states the pricing
 * plainly:
 *
 *     no size selected -> menu_items.price
 *     selected size price
 *     + sum(selected option extra_price)
 *     = final line item price
 *
 * The customer app added the size to the base instead of replacing it, so a
 * $12 bowl with a $15 Large showed $27 through the cart and on the Pay button
 * while Stripe charged $15. It also rendered inactive sizes and options, and
 * showed size-scoped groups against every size.
 *
 * These are pure so the rules can be pinned without a browser, and so the one
 * place that decides them is the same place the screen and the cart both use.
 */

function option(over: Partial<CustomizationOption> = {}): CustomizationOption {
  return {
    id: over.id ?? "opt-1",
    name: over.name ?? "Extra peanuts",
    extra_price: over.extra_price ?? "1.50",
    is_countable: over.is_countable ?? false,
    is_active: over.is_active ?? true,
  };
}

function group(over: Partial<CustomizationGroup> = {}): CustomizationGroup {
  return {
    id: over.id ?? "grp-1",
    menu_item_size_id: over.menu_item_size_id ?? null,
    title: over.title ?? "Toppings",
    selection_type: over.selection_type ?? "MULTI",
    is_required: over.is_required ?? false,
    min_selection: over.min_selection ?? 0,
    max_selection: over.max_selection ?? 3,
    supports_halves: over.supports_halves ?? false,
    is_active: over.is_active ?? true,
    options: over.options ?? [option()],
  };
}

function size(over: Partial<MenuSize> = {}): MenuSize {
  return {
    id: over.id ?? "size-1",
    name: over.name ?? "Regular",
    price: over.price ?? "12.00",
    is_active: over.is_active ?? true,
    customization_groups: over.customization_groups ?? [],
  };
}

function item(over: Partial<MenuItem> = {}): MenuItem {
  return {
    id: "item-1",
    restaurant_id: "r-1",
    restaurant_location_id: "l-1",
    name: "Pad Thai",
    category: "Noodles",
    cuisine_type: "Thai",
    description: "",
    price: over.price ?? "12.00",
    is_veg: true,
    is_available: true,
    is_bestseller: false,
    image_url: null,
    rating: null,
    rating_count: 0,
    is_new: false,
    is_favorite: false,
    has_sizes: over.has_sizes ?? false,
    has_customizations: over.has_customizations ?? false,
    sizes: over.sizes ?? [],
    customization_groups: over.customization_groups ?? [],
  };
}

describe("unitPriceFor", () => {
  it("uses the item price when there is no size", () => {
    expect(unitPriceFor(item({ price: "12.00" }), undefined, [])).toBe(12);
  });

  it("REPLACES the base price with the size price, never adds to it", () => {
    // The bug: $12 base + $15 Large was shown as $27 and charged as $15.
    const large = size({ id: "lg", name: "Large", price: "15.00" });
    const sized = item({ price: "12.00", has_sizes: true, sizes: [size(), large] });
    expect(unitPriceFor(sized, large, [])).toBe(15);
  });

  it("adds the extra price of each selected option to the size price", () => {
    const large = size({ id: "lg", price: "15.00" });
    const peanuts = option({ id: "o1", extra_price: "1.50" });
    const prawns = option({ id: "o2", extra_price: "3.00" });
    const sized = item({
      has_sizes: true,
      sizes: [large],
      has_customizations: true,
      customization_groups: [group({ options: [peanuts, prawns] })],
    });
    expect(unitPriceFor(sized, large, ["o1", "o2"])).toBe(19.5);
  });

  it("ignores an option the customer cannot actually see", () => {
    // An inactive option must not be priced even if a stale id names it.
    const gone = option({ id: "gone", extra_price: "5.00", is_active: false });
    const sized = item({
      has_customizations: true,
      customization_groups: [group({ options: [option({ id: "o1" }), gone] })],
    });
    expect(unitPriceFor(sized, undefined, ["gone"])).toBe(12);
  });
});

describe("activeSizes", () => {
  it("hides a size the owner switched off", () => {
    const on = size({ id: "on" });
    const off = size({ id: "off", is_active: false });
    expect(activeSizes(item({ sizes: [on, off] })).map((s) => s.id)).toEqual(["on"]);
  });
});

describe("activeOptions", () => {
  it("hides an option the owner switched off", () => {
    const on = option({ id: "on" });
    const off = option({ id: "off", is_active: false });
    expect(activeOptions(group({ options: [on, off] })).map((o) => o.id)).toEqual(["on"]);
  });
});

describe("visibleGroups", () => {
  it("shows item-level groups and hides inactive ones", () => {
    const shown = group({ id: "a" });
    const hidden = group({ id: "b", is_active: false });
    expect(
      visibleGroups(item({ customization_groups: [shown, hidden] }), undefined).map((g) => g.id),
    ).toEqual(["a"]);
  });

  it("does not show a size's group against every size", () => {
    // The duplicate-groups report. A group scoped to Large must not appear
    // while Regular is selected, and must not appear twice when it is.
    const largeOnly = group({ id: "large-only", menu_item_size_id: "lg" });
    const regular = size({ id: "reg" });
    const large = size({ id: "lg", customization_groups: [largeOnly] });
    const sized = item({
      has_sizes: true,
      sizes: [regular, large],
      customization_groups: [group({ id: "shared" }), largeOnly],
    });

    expect(visibleGroups(sized, regular).map((g) => g.id)).toEqual(["shared"]);
    expect(visibleGroups(sized, large).map((g) => g.id)).toEqual(["shared", "large-only"]);
  });

  it("never lists the same group twice", () => {
    const scoped = group({ id: "dup", menu_item_size_id: "lg" });
    const large = size({ id: "lg", customization_groups: [scoped, scoped] });
    const sized = item({ has_sizes: true, sizes: [large], customization_groups: [scoped] });
    expect(visibleGroups(sized, large).map((g) => g.id)).toEqual(["dup"]);
  });
});

describe("requiresChoosing", () => {
  it("treats a minimum of one as required, whatever the flag says", () => {
    // Reported: a group marked Not Required with min_selection = 1 behaved as
    // required. It does — the minimum is the thing the server enforces — so the
    // screen must label it that way instead of letting it look optional.
    expect(requiresChoosing(group({ is_required: false, min_selection: 1 }))).toBe(true);
    expect(requiresChoosing(group({ is_required: true, min_selection: 0 }))).toBe(true);
    expect(requiresChoosing(group({ is_required: false, min_selection: 0 }))).toBe(false);
  });
});

describe("selectionProblem", () => {
  const peanuts = option({ id: "o1" });
  const prawns = option({ id: "o2" });

  it("is null when nothing is wrong", () => {
    const simple = item();
    expect(selectionProblem(simple, undefined, {})).toBeNull();
  });

  it("asks for a size when the item has them", () => {
    const sized = item({ has_sizes: true, sizes: [size()] });
    expect(selectionProblem(sized, undefined, {})).toMatch(/size/i);
  });

  it("names the group that still needs a choice", () => {
    const required = group({ title: "Spice level", is_required: true, min_selection: 1 });
    const sized = item({ has_customizations: true, customization_groups: [required] });
    expect(selectionProblem(sized, undefined, {})).toContain("Spice level");
  });

  it("counts a minimum above one", () => {
    const two = group({ title: "Sides", min_selection: 2, options: [peanuts, prawns] });
    const sized = item({ has_customizations: true, customization_groups: [two] });
    expect(selectionProblem(sized, undefined, { "grp-1": ["o1"] })).toContain("Sides");
    expect(selectionProblem(sized, undefined, { "grp-1": ["o1", "o2"] })).toBeNull();
  });

  it("refuses a minimum no number of options could satisfy, instead of blaming the customer", () => {
    // Reported: min_selection can exceed the options available, which makes the
    // item impossible to order. The screen cannot fix the data, but it must not
    // pretend the customer has failed to choose enough.
    const impossible = group({ title: "Sauces", min_selection: 3, options: [peanuts] });
    const sized = item({ has_customizations: true, customization_groups: [impossible] });
    const problem = selectionProblem(sized, undefined, { "grp-1": ["o1"] });
    expect(problem).toMatch(/Sauces/);
    expect(problem).toMatch(/cannot be ordered|unavailable/i);
  });

  it("stops a customer exceeding the maximum", () => {
    const one = group({ title: "Spice", max_selection: 1, options: [peanuts, prawns] });
    const sized = item({ has_customizations: true, customization_groups: [one] });
    expect(selectionProblem(sized, undefined, { "grp-1": ["o1", "o2"] })).toContain("Spice");
  });

  it("ignores a group that belongs to a different size", () => {
    const largeOnly = group({
      id: "lg-grp",
      title: "Large extras",
      menu_item_size_id: "lg",
      min_selection: 1,
    });
    const regular = size({ id: "reg" });
    const large = size({ id: "lg", customization_groups: [largeOnly] });
    const sized = item({
      has_sizes: true,
      sizes: [regular, large],
      customization_groups: [largeOnly],
    });
    // Regular is selected, so Large's required group must not block the order.
    expect(selectionProblem(sized, regular, {})).toBeNull();
    expect(selectionProblem(sized, large, {})).toContain("Large extras");
  });
});

describe("halves", () => {
  /**
   * Half-and-half: pepperoni one side, mushroom the other.
   *
   * Driven entirely by the group's `supports_halves` flag, which the owner sets
   * in admin — there is no separate "half pizza" item. Pricing mirrors the
   * server: a half costs half the option's extra price, rounded the same way.
   */
  const pepperoni = option({ id: "pep", name: "Pepperoni", extra_price: "3.00" });
  const mushroom = option({ id: "mush", name: "Mushroom", extra_price: "2.50" });
  const olives = option({ id: "oli", name: "Olives", extra_price: "1.25" });

  const pizza = item({
    price: "12.00",
    has_customizations: true,
    customization_groups: [
      group({
        id: "toppings",
        title: "Toppings",
        supports_halves: true,
        options: [pepperoni, mushroom, olives],
      }),
    ],
  });

  it("charges full price for a whole topping", () => {
    expect(unitPriceFor(pizza, undefined, ["pep"])).toBe(15);
  });

  it("charges half for half", () => {
    expect(unitPriceFor(pizza, undefined, ["pep"], { pep: "LEFT" })).toBe(13.5);
  });

  it("prices two different halves independently", () => {
    const price = unitPriceFor(pizza, undefined, ["pep", "mush"], {
      pep: "LEFT",
      mush: "RIGHT",
    });
    // 12 + 3/2 + 2.50/2
    expect(price).toBe(14.75);
  });

  it("rounds a half the way the server does", () => {
    // 1.25 / 2 is 0.625, which must land on 0.63 to match the server.
    expect(unitPriceFor(pizza, undefined, ["oli"], { oli: "RIGHT" })).toBe(12.63);
  });

  it("ignores a portion on a group that cannot be split", () => {
    // The flag is the authority. A stale portion on an ordinary group must not
    // quietly halve the price of a topping the kitchen will apply in full.
    const plain = item({
      price: "12.00",
      has_customizations: true,
      customization_groups: [group({ id: "g", options: [pepperoni] })],
    });
    expect(unitPriceFor(plain, undefined, ["pep"], { pep: "LEFT" })).toBe(15);
  });
});

describe("splitSummary", () => {
  const pepperoni = option({ id: "pep", name: "Pepperoni" });
  const mushroom = option({ id: "mush", name: "Mushroom" });
  const pizza = item({
    has_customizations: true,
    customization_groups: [
      group({ id: "t", supports_halves: true, options: [pepperoni, mushroom] }),
    ],
  });

  it("reads the pizza back as two halves", () => {
    const summary = splitSummary(pizza, undefined, ["pep", "mush"], {
      pep: "LEFT",
      mush: "RIGHT",
    });
    expect(summary).toEqual({ left: ["Pepperoni"], right: ["Mushroom"], whole: [] });
  });

  it("keeps a whole topping out of both halves", () => {
    const summary = splitSummary(pizza, undefined, ["pep", "mush"], { pep: "LEFT" });
    expect(summary).toEqual({ left: ["Pepperoni"], right: [], whole: ["Mushroom"] });
  });

  it("is empty when nothing is chosen", () => {
    expect(splitSummary(pizza, undefined, [], {})).toEqual({ left: [], right: [], whole: [] });
  });
});

describe("portionLabel", () => {
  it("names a half the way a customer would say it", () => {
    expect(portionLabel("LEFT")).toBe("Left half");
    expect(portionLabel("RIGHT")).toBe("Right half");
    expect(portionLabel("WHOLE")).toBe("Whole");
  });
});

describe("selectionHint", () => {
  /**
   * The rules an owner sets have to reach the customer as words.
   *
   * Before this the badge said "Choose 2" and the line under it said "Choose
   * up to 4" — two different sentences about one rule, in two places, and
   * neither of them said both numbers.
   */
  const group = (over: Partial<ReturnType<typeof base>> = {}) => ({ ...base(), ...over });
  function base() {
    return {
      id: "g",
      title: "Toppings",
      selection_type: "MULTI" as "SINGLE" | "MULTI",
      is_required: false,
      min_selection: 0,
      max_selection: 0,
      supports_halves: false,
      is_active: true,
      options: [],
    };
  }

  it("says one for a single choice, whatever the numbers claim", () => {
    // A SINGLE group is one option by definition; its stored max is noise.
    expect(selectionHint(group({ selection_type: "SINGLE", max_selection: 4 }))).toBe("Choose 1");
  });

  it("gives both numbers when both are set", () => {
    expect(selectionHint(group({ min_selection: 2, max_selection: 4 }))).toBe("Choose 2 to 4");
  });

  it("says exactly when they are the same", () => {
    expect(selectionHint(group({ min_selection: 3, max_selection: 3 }))).toBe("Choose exactly 3");
  });

  it("says only the one that is set", () => {
    expect(selectionHint(group({ min_selection: 0, max_selection: 4 }))).toBe("Choose up to 4");
    expect(selectionHint(group({ min_selection: 2, max_selection: 0 }))).toBe("Choose at least 2");
  });

  it("says anything goes when nothing is set", () => {
    expect(selectionHint(group())).toBe("Choose any");
  });
});

describe("canPickMore", () => {
  const group = (max: number, type: "SINGLE" | "MULTI" = "MULTI") => ({
    id: "g",
    title: "Toppings",
    selection_type: type as "SINGLE" | "MULTI",
    is_required: false,
    min_selection: 0,
    max_selection: max,
    supports_halves: false,
    is_active: true,
    options: [],
  });

  it("stops at the ceiling the owner set", () => {
    expect(canPickMore(group(3), 2)).toBe(true);
    expect(canPickMore(group(3), 3)).toBe(false);
  });

  it("has no ceiling when none was set", () => {
    expect(canPickMore(group(0), 99)).toBe(true);
  });

  it("never blocks a single choice, which replaces rather than adds", () => {
    // Tapping a second option in a SINGLE group swaps it; if the ceiling
    // applied, the first pick would lock the group forever.
    expect(canPickMore(group(1, "SINGLE"), 1)).toBe(true);
  });
});
