/**
 * Which restaurant a tenant-scoped screen reads, when an admin has two places
 * to say so.
 *
 * The sidebar switcher and the page's own picker were independent. An admin
 * who chose Bangkok Bowl in the sidebar opened Marketing and was shown Famous
 * Chinese Cuisine — "No campaigns yet", for a restaurant with twenty-three —
 * and a campaign link opened from there answered `restaurant_id is required`.
 * Both read as the feature being empty or broken, in front of a client.
 */

import { describe, expect, it } from "vitest";

import { scopedRestaurant } from "./scopeRule";

describe("scopedRestaurant", () => {
  it("follows the sidebar when it names a restaurant", () => {
    expect(scopedRestaurant("bangkok", "famous-chinese")).toBe("bangkok");
  });

  it("follows the sidebar even before the page has picked anything", () => {
    // The deep link: no remembered pick in this browser, sidebar already set.
    expect(scopedRestaurant("bangkok", "")).toBe("bangkok");
  });

  it("falls back to the page's own pick when the sidebar says All restaurants", () => {
    // These screens cannot show "all": the API requires one restaurant from
    // an admin. So the page keeps its own answer rather than going blank.
    expect(scopedRestaurant(null, "famous-chinese")).toBe("famous-chinese");
  });

  it("is empty, and so not ready, when neither has an answer", () => {
    expect(scopedRestaurant(null, "")).toBe("");
  });
});
