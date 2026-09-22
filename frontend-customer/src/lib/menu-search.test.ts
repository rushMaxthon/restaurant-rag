/**
 * Searching the menu must not be able to break the menu.
 *
 * Reported from the running app: typing anything into the search box left the
 * customer on an empty page. The console had it —
 *
 *     TypeError: Cannot read properties of null (reading 'toLowerCase')
 *       at menu-grid.tsx  →  Array.filter  →  MenuGrid
 *
 * — because the predicate read `item.description.toLowerCase()` while 720 of
 * that restaurant's 816 rows have no description. The type said `string`, so
 * the compiler never asked; the column has been nullable the whole time.
 *
 * The type is honest now, which is the real fix. These are the guard on the
 * behaviour: a null anywhere is a miss, never a throw.
 */

import { describe, expect, it } from "vitest";

import { matchesQuery } from "./menu-search";

type Searchable = Parameters<typeof matchesQuery>[0];

const dish = (over: Partial<Searchable> = {}): Searchable => ({
  name: "Khaman Dhokla",
  description: "Steamed and soft, served with chutney.",
  category: "Khaman",
  ...over,
});

describe("matchesQuery", () => {
  it("does not throw when a dish has no description", () => {
    // The reported crash, stated as the thing it must never do again.
    expect(() => matchesQuery(dish({ description: null }), "dhokla")).not.toThrow();
  });

  it("still finds a dish with no description by its name", () => {
    expect(matchesQuery(dish({ description: null }), "khaman")).toBe(true);
  });

  it("survives every text field being null at once", () => {
    const empty = { name: null, description: null, category: null } as unknown as Searchable;
    expect(() => matchesQuery(empty, "dhokla")).not.toThrow();
    expect(matchesQuery(empty, "dhokla")).toBe(false);
  });

  it("matches the name", () => {
    expect(matchesQuery(dish(), "khaman")).toBe(true);
  });

  it("matches the description, which is the point of searching it", () => {
    // "something with peanuts" is in the description or nowhere.
    expect(matchesQuery(dish({ description: "Tossed with peanuts" }), "peanuts")).toBe(true);
  });

  it("matches the category", () => {
    expect(matchesQuery(dish({ category: "Farsan" }), "farsan")).toBe(true);
  });

  it("ignores case on both sides", () => {
    expect(matchesQuery(dish({ name: "KHAMAN DHOKLA" }), "khaman")).toBe(true);
    expect(matchesQuery(dish(), "KHAMAN")).toBe(true);
  });

  it("ignores the spaces around what was typed", () => {
    expect(matchesQuery(dish(), "  dhokla  ")).toBe(true);
  });

  it("keeps everything when nothing has been typed", () => {
    // An empty box is not a filter, and a blank one is not either.
    expect(matchesQuery(dish({ name: null, description: null, category: null } as never), "")).toBe(
      true,
    );
    expect(matchesQuery(dish(), "   ")).toBe(true);
  });

  it("says no when nothing matches, rather than everything", () => {
    expect(matchesQuery(dish(), "biryani")).toBe(false);
  });
});
