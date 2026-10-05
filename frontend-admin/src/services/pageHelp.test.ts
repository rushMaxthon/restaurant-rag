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

  it("tells an owner the commission is not theirs to change", () => {
    expect(pageHelp("location-detail", "OWNER").action).toMatch(/commission/i);
    expect(pageHelp("location-detail", "ADMIN").action).toMatch(/commission/i);
  });

  it("falls back to the owner's words for a role with no copy of its own", () => {
    expect(pageHelp("orders", "KITCHEN")).toEqual(pageHelp("orders", "OWNER"));
  });
});
