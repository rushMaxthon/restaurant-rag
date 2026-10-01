import { describe, expect, it } from "vitest";

import type { MenuItem } from "@/lib/bangkok-data";
import { activeSection, buildSections, countItems, sectionSlug } from "@/lib/menu-sections";

function dish(name: string, category: string, extra: Partial<MenuItem> = {}): MenuItem {
  return {
    id: name,
    restaurant_id: "r",
    restaurant_location_id: "l",
    name,
    category,
    cuisine_type: "Gujarati",
    description: null,
    price: "100",
    is_veg: true,
    is_available: true,
    is_bestseller: false,
    image_url: null,
    rating: null,
    rating_count: 0,
    is_new: false,
    is_favorite: false,
    has_sizes: false,
    has_customizations: false,
    sizes: [],
    customization_groups: [],
    ...extra,
  } as MenuItem;
}

describe("sections follow the kitchen's own order", () => {
  it("keeps categories in the order they first appear, not alphabetical", () => {
    // Alphabetical would be tidier and would put Desserts above Mains on
    // every menu on the platform.
    const sections = buildSections([
      dish("Samosa", "Starters"),
      dish("Thali", "Mains"),
      dish("Jalebi", "Desserts"),
      dish("Kachori", "Starters"),
    ]);
    expect(sections.map((s) => s.category)).toEqual(["Starters", "Mains", "Desserts"]);
    expect(sections[0]!.items.map((i) => i.name)).toEqual(["Samosa", "Kachori"]);
  });

  it("does not reorder the array the query handed it", () => {
    // `items` is TanStack Query's cached array. Sorting a bucket in place
    // would reorder data other screens read from the same cache.
    const items = [dish("B", "Starters"), dish("A", "Starters")];
    const snapshot = items.map((i) => i.name);
    buildSections(items, { compare: (a, b) => a.name.localeCompare(b.name) });
    expect(items.map((i) => i.name)).toEqual(snapshot);
  });

  it("sorts within a section when asked, leaving section order alone", () => {
    const sections = buildSections(
      [dish("Thali", "Mains"), dish("Samosa", "Starters"), dish("Dhokla", "Starters")],
      { compare: (a, b) => a.name.localeCompare(b.name) },
    );
    expect(sections.map((s) => s.category)).toEqual(["Mains", "Starters"]);
    expect(sections[1]!.items.map((i) => i.name)).toEqual(["Dhokla", "Samosa"]);
  });
});

describe("filters subtract, and empty sections disappear", () => {
  it("drops a section the search emptied rather than showing a bare heading", () => {
    // Nineteen headings with nothing under them, and the three results
    // somewhere in the middle, was the alternative.
    const sections = buildSections(
      [dish("Paneer Tikka", "Starters"), dish("Jalebi", "Desserts")],
      { query: "paneer" },
    );
    expect(sections).toHaveLength(1);
    expect(sections[0]!.category).toBe("Starters");
  });

  it("applies the veg filter before grouping", () => {
    const sections = buildSections(
      [dish("Chicken Tikka", "Starters", { is_veg: false }), dish("Thali", "Mains")],
      { vegOnly: true },
    );
    expect(sections.map((s) => s.category)).toEqual(["Mains"]);
  });

  it("returns nothing at all when nothing matches", () => {
    const sections = buildSections([dish("Thali", "Mains")], { query: "sushi" });
    expect(sections).toEqual([]);
    expect(countItems(sections)).toBe(0);
  });

  it("counts what is actually on screen", () => {
    const sections = buildSections([
      dish("A", "Starters"),
      dish("B", "Starters"),
      dish("C", "Mains"),
    ]);
    expect(countItems(sections)).toBe(3);
  });
});

describe("slugs are stable and unique", () => {
  it("turns a category name into a usable DOM id", () => {
    expect(sectionSlug("Farsan & Snacks")).toBe("menu-farsan-snacks");
    expect(sectionSlug("  Mains  ")).toBe("menu-mains");
  });

  it("survives a category with nothing sluggable in it", () => {
    // An empty id would make `#` the link target, which scrolls to the top of
    // the page — looking exactly like a broken chip.
    expect(sectionSlug("***")).toBe("menu-section");
  });

  it("separates two categories that would slugify the same", () => {
    // The real failure: "Thali / Combo" and "Thali & Combo" both reduce to
    // `menu-thali-combo`, and a duplicate id means the rail scrolls to
    // whichever heading the browser found first — so one chip does nothing.
    const sections = buildSections([
      dish("A", "Thali / Combo"),
      dish("B", "Thali & Combo"),
    ]);
    expect(sections.map((s) => s.slug)).toEqual(["menu-thali-combo", "menu-thali-combo-2"]);
  });
});

describe("the rail follows the section that has passed under the chrome", () => {
  const sections = buildSections([
    dish("A", "Starters"),
    dish("B", "Mains"),
    dish("C", "Desserts"),
  ]);
  const LINE = 136;

  it("names the last section whose top is above the line", () => {
    // Starters scrolled well past, Mains just under the chrome, Desserts
    // still below the fold. Mains is what fills the screen.
    expect(activeSection(sections, [-900, 40, 1200], LINE)).toBe("menu-mains");
  });

  it("holds the current section while it fills the whole viewport", () => {
    // The case that broke the observer version: deep inside a long section,
    // no heading is anywhere near the band.
    expect(activeSection(sections, [-4000, -2200, 3000], LINE)).toBe("menu-mains");
  });

  it("cannot skip a section however far the page moved between frames", () => {
    // A flick that travels 3000px in one frame still lands on the right
    // answer, because this does not depend on catching anything in flight.
    expect(activeSection(sections, [-6000, -4000, -1500], LINE)).toBe("menu-desserts");
  });

  it("names nothing at the top of the page, rather than guessing the first", () => {
    expect(activeSection(sections, [400, 1400, 2400], LINE)).toBeNull();
  });

  it("counts a section sitting exactly on the line as the current one", () => {
    expect(activeSection(sections, [LINE, 900, 1900], LINE)).toBe("menu-starters");
  });

  it("survives a section whose element could not be measured", () => {
    // `Infinity` is what the caller passes for a node that is not in the DOM
    // — mid-render, or a section React has not committed yet.
    expect(activeSection(sections, [-900, Number.POSITIVE_INFINITY, -100], LINE)).toBe(
      "menu-starters",
    );
  });

  it("has no answer for an empty menu", () => {
    expect(activeSection([], [], LINE)).toBeNull();
  });
});
