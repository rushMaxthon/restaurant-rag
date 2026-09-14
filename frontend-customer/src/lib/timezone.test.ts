import { describe, expect, it } from "vitest";
import { formatInZone, nowInZone, zonedParts, zonedTimeToUtc, zoneOffsetMs } from "./timezone";

/**
 * Reading and writing wall-clock times in the restaurant's zone, not the
 * device's.
 *
 * The customer app built every slot with `date.setHours(...)`, which uses the
 * DEVICE's zone. On a machine in the same zone as the branch that is invisible,
 * which is why it survived. For a customer in Toronto reading a branch in
 * Ahmedabad it turned the branch's 7pm window into their own 7pm and sent an
 * instant nine and a half hours out, which the server then refused.
 *
 * Zones are pinned by name and the assertions are on absolute instants, so
 * these do not depend on where the machine running them happens to be.
 */

const KOLKATA = "Asia/Kolkata"; // +05:30 all year, no DST
const TORONTO = "America/Toronto"; // -04:00 in summer, -05:00 in winter

describe("zoneOffsetMs", () => {
  it("reads a fixed offset", () => {
    const summer = new Date("2026-07-01T12:00:00Z");
    expect(zoneOffsetMs(summer, KOLKATA)).toBe(5.5 * 60 * 60 * 1000);
  });

  it("follows daylight saving rather than assuming one offset", () => {
    // The whole reason for an IANA name instead of a stored number.
    const summer = new Date("2026-07-01T12:00:00Z");
    const winter = new Date("2026-01-15T12:00:00Z");
    expect(zoneOffsetMs(summer, TORONTO)).toBe(-4 * 60 * 60 * 1000);
    expect(zoneOffsetMs(winter, TORONTO)).toBe(-5 * 60 * 60 * 1000);
  });
});

describe("zonedTimeToUtc", () => {
  it("turns a branch wall clock into the instant it actually names", () => {
    // 7pm in Ahmedabad is 13:30 UTC, whatever the device thinks 7pm is.
    const instant = zonedTimeToUtc(
      { year: 2026, month: 9, day: 14, hour: 19, minute: 0 },
      KOLKATA,
    );
    expect(instant.toISOString()).toBe("2026-09-14T13:30:00.000Z");
  });

  it("gives a different instant for the same clock in another zone", () => {
    const inToronto = zonedTimeToUtc(
      { year: 2026, month: 9, day: 14, hour: 19, minute: 0 },
      TORONTO,
    );
    expect(inToronto.toISOString()).toBe("2026-09-14T23:00:00.000Z");
  });

  it("handles a winter date in a zone that observes DST", () => {
    const instant = zonedTimeToUtc(
      { year: 2026, month: 1, day: 15, hour: 19, minute: 0 },
      TORONTO,
    );
    expect(instant.toISOString()).toBe("2026-01-16T00:00:00.000Z");
  });

  it("round-trips with zonedParts", () => {
    const parts = { year: 2026, month: 9, day: 14, hour: 21, minute: 30 };
    const back = zonedParts(zonedTimeToUtc(parts, TORONTO), TORONTO);
    expect(back.year).toBe(2026);
    expect(back.month).toBe(9);
    expect(back.day).toBe(14);
    expect(back.hour).toBe(21);
    expect(back.minute).toBe(30);
  });
});

describe("zonedParts", () => {
  it("reads the wall clock a zone shows for an instant", () => {
    const instant = new Date("2026-09-14T13:30:00Z");
    const kolkata = zonedParts(instant, KOLKATA);
    expect(kolkata.hour).toBe(19);
    expect(kolkata.minute).toBe(0);
    expect(kolkata.day).toBe(14);

    // The same instant, a different clock.
    const toronto = zonedParts(instant, TORONTO);
    expect(toronto.hour).toBe(9);
    expect(toronto.minute).toBe(30);
  });

  it("reports the weekday in that zone, which can differ from the device's", () => {
    // 20:00 UTC on a Monday is already Tuesday in Kolkata.
    const instant = new Date("2026-09-14T20:00:00Z");
    expect(zonedParts(instant, KOLKATA).weekday).toBe("TUESDAY");
    expect(zonedParts(instant, TORONTO).weekday).toBe("MONDAY");
  });
});

describe("formatInZone", () => {
  it("prints the branch's clock, not the device's", () => {
    const instant = new Date("2026-09-14T13:30:00Z");
    expect(formatInZone(instant, KOLKATA, { hour: "numeric", minute: "2-digit" })).toContain("7:00");
    expect(formatInZone(instant, TORONTO, { hour: "numeric", minute: "2-digit" })).toContain("9:30");
  });

  it("falls back to the device zone when given nothing", () => {
    // An undefined zone must not throw; the app still works before the config
    // that carries the zone has loaded.
    const instant = new Date("2026-09-14T13:30:00Z");
    expect(() => formatInZone(instant, undefined, { hour: "numeric" })).not.toThrow();
  });
});

describe("nowInZone", () => {
  it("is the same instant, read on the branch's clock", () => {
    const instant = new Date("2026-09-14T13:30:00Z");
    const parts = nowInZone(KOLKATA, instant);
    expect(parts.hour).toBe(19);
    expect(parts.day).toBe(14);
  });
});
