/**
 * A sort is only offered when the data can honour it.
 *
 * The menu offered "Top rated" whatever it held. Not one of this
 * restaurant's 136 dishes has a rating, so choosing it compared 0 against 0
 * for every pair and reordered nothing — a control that promises an ordering
 * the data cannot provide, which is the same class of thing as a section
 * headed "Most loved" over dishes nobody has loved.
 *
 * The rule lives here rather than in the component so it can be stated once
 * and checked without rendering: offer the rating sort when something is
 * rated, and not otherwise.
 */

import { describe, expect, it } from "vitest";

import { sortsFor, type SortOption } from "./menu-sorts";

const ALL: SortOption[] = [
  { value: "recommended", label: "Recommended" },
  { value: "price-asc", label: "Price: low to high" },
  { value: "price-desc", label: "Price: high to low" },
  { value: "rating", label: "Top rated" },
];

const values = (options: SortOption[]) => options.map((option) => option.value);

describe("sortsFor", () => {
  it("drops the rating sort when nothing is rated", () => {
    expect(values(sortsFor(ALL, [{ rating: null }, { rating: 0 }]))).not.toContain("rating");
  });

  it("keeps it as soon as one dish is rated", () => {
    expect(values(sortsFor(ALL, [{ rating: null }, { rating: 4.5 }]))).toContain("rating");
  });

  it("treats the string the API sends as a number", () => {
    // Decimal columns arrive as strings over JSON.
    expect(values(sortsFor(ALL, [{ rating: "4.2" }]))).toContain("rating");
    expect(values(sortsFor(ALL, [{ rating: "0" }]))).not.toContain("rating");
  });

  it("drops it for an empty menu rather than offering it hopefully", () => {
    expect(values(sortsFor(ALL, []))).not.toContain("rating");
  });

  it("never drops a sort the data always supports", () => {
    // Price and the default are answerable by every menu, so they survive
    // whatever else is missing.
    expect(values(sortsFor(ALL, []))).toEqual(["recommended", "price-asc", "price-desc"]);
  });
});
