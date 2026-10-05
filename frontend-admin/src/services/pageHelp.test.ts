import { describe, expect, it } from "vitest";

import { PAGE_HELP, pageHelp, type PageHelpId } from "./pageHelp";

const IDS = Object.keys(PAGE_HELP) as PageHelpId[];

describe("pageHelp", () => {
  it("answers all three questions for both roles on every page", () => {
    expect(IDS.length).toBeGreaterThanOrEqual(25);
    for (const id of IDS) {
      for (const role of ["ADMIN", "OWNER"] as const) {
        const help = pageHelp(id, role);
        expect(help.title.length, id).toBeGreaterThan(2);
        for (const text of [help.what, help.who, help.action]) {
          expect(text.length, `${id} ${role}`).toBeGreaterThan(20);
          // It is read in a small popover. Past this it is a manual, not a tip.
          expect(text.length, `${id} ${role}`).toBeLessThanOrEqual(240);
          expect(text.endsWith("."), `${id} ${role}: ${text}`).toBe(true);
        }
      }
    }
  });

  it("speaks to an owner about their own restaurant and to an admin about all of them", () => {
    expect(pageHelp("orders", "OWNER").what).toMatch(/your restaurant/i);
    expect(pageHelp("orders", "ADMIN").what).toMatch(/every restaurant/i);
  });

  it("mentions the commission to the platform admin and to nobody else", () => {
    expect(pageHelp("location-detail", "ADMIN").action).toMatch(/commission/i);
    expect(pageHelp("menu-item-editor", "ADMIN").action).toMatch(/commission/i);
    // The rate is the platform's own figure. An owner's help text naming it
    // would tell them what the hidden tile no longer does.
    // Except the Commission page itself, which an owner cannot open: the
    // route is admin-only and the endpoint refuses them.
    for (const id of IDS.filter((page) => page !== "commission")) {
      const help = pageHelp(id, "OWNER");
      expect(`${help.what} ${help.who} ${help.action}`, id).not.toMatch(/commission/i);
    }
  });

  it("falls back to the owner's words for a role with no copy of its own", () => {
    expect(pageHelp("orders", "KITCHEN")).toEqual(pageHelp("orders", "OWNER"));
  });
});
