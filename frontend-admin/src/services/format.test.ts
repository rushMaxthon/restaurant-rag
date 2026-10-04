/**
 * A chart's day label, written for a person.
 *
 * The marketing charts printed what the API sent: "2026-09-21" under every
 * bar and along every axis, where the dashboard beside them says "Sep 21".
 * Seven ISO dates in a row are seven things to decode.
 */

import { describe, expect, it } from "vitest";

import { shortDay } from "./format";

describe("shortDay", () => {
  it("writes an ISO date as a day and a month", () => {
    expect(shortDay("2026-09-21")).toBe("21 Sep");
    expect(shortDay("2026-10-04")).toBe("4 Oct");
  });

  it("does not let the viewer's timezone move the day", () => {
    // `new Date("2026-01-01")` is midnight UTC, which is still 31 December in
    // any timezone west of Greenwich. The label is the calendar day as sent.
    expect(shortDay("2026-01-01")).toBe("1 Jan");
    expect(shortDay("2026-12-31")).toBe("31 Dec");
  });

  it("leaves anything that is not an ISO date alone", () => {
    expect(shortDay("Sep 21")).toBe("Sep 21");
    expect(shortDay("Week 3")).toBe("Week 3");
    expect(shortDay("")).toBe("");
    expect(shortDay("2026-13-40")).toBe("2026-13-40");
  });
});
