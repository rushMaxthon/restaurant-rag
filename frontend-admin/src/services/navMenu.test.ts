import { Store } from "lucide-react";
import { describe, expect, it } from "vitest";

import { navFor, type NavGroup, type NavItem } from "../routes";
import { bestMatch, filterNav, isGroupOpen, matchScore } from "./navMenu";

const item = (label: string, keywords: string[] = []): NavItem => ({
  path: `/${label.toLowerCase().replace(/\s+/g, "-")}`,
  label,
  icon: Store,
  keywords,
});

const groups: NavGroup[] = [
  { section: "Orders", label: "Orders", items: [item("Live orders"), item("Orders")] },
  {
    section: "Menu & offers",
    label: "Menu & offers",
    items: [item("Menu items", ["stock", "dishes"]), item("Offers")],
  },
  { section: "Restaurant", label: "Restaurants", items: [item("Storefront content")] },
];

describe("searching the sidebar", () => {
  it("finds a page by a word in its name", () => {
    const found = filterNav(groups, "menu");
    expect(found.flatMap((group) => group.items.map((each) => each.label))).toEqual(["Menu items"]);
  });

  it("finds a page by what it is for, not only what it is called", () => {
    expect(bestMatch(groups, "stock")?.label).toBe("Menu items");
  });

  it("puts a name that starts with the search above one that merely contains it", () => {
    expect(matchScore(item("Orders"), "or")).toBeGreaterThan(matchScore(item("Storefront content"), "or"));
    expect(bestMatch(groups, "or")?.label).toBe("Orders");
  });

  it("drops groups with nothing left in them", () => {
    expect(filterNav(groups, "storefront").map((group) => group.section)).toEqual(["Restaurant"]);
  });

  it("shows everything for an empty search, and nothing for nonsense", () => {
    expect(filterNav(groups, "  ")).toBe(groups);
    expect(filterNav(groups, "zzz")).toEqual([]);
    expect(bestMatch(groups, "zzz")).toBeNull();
  });
});

describe("folding groups away", () => {
  const closed = new Set(["Orders", "Restaurant"] as const);

  it("keeps a group closed when the person closed it", () => {
    expect(isGroupOpen("Orders", { closed, activeSection: null, searching: false })).toBe(false);
  });

  it("never hides the group holding the current page", () => {
    expect(isGroupOpen("Orders", { closed, activeSection: "Orders", searching: false })).toBe(true);
  });

  it("opens everything while searching", () => {
    expect(isGroupOpen("Restaurant", { closed, activeSection: null, searching: true })).toBe(true);
  });

  it("starts open for anybody who never chose", () => {
    expect(isGroupOpen("Platform", { closed: new Set(), activeSection: null, searching: false })).toBe(true);
  });
});

describe("the groups themselves", () => {
  it("keeps every group short enough to read at a glance", () => {
    for (const role of ["ADMIN", "OWNER"] as const) {
      for (const group of navFor(role)) {
        expect(group.items.length, `${role} ${group.label}`).toBeLessThanOrEqual(5);
      }
    }
  });

  it("names the owner's restaurant group for their one restaurant", () => {
    const labels = (role: "ADMIN" | "OWNER") => navFor(role).map((group) => group.label);
    expect(labels("OWNER")).toContain("My restaurant");
    expect(labels("ADMIN")).toContain("Restaurants");
  });
});
