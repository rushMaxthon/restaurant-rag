import { describe, expect, it } from "vitest";
import { formatMoney, orderCode, scheduledFor } from "./bangkok-data";

/**
 * Money, in one place.
 *
 * Every price the customer sees goes through `formatMoney`, which is why it is
 * worth pinning: the app has already moved currency twice — rupees to US
 * dollars, then to Canadian dollars — and the symbol is not the only thing that
 * changes. Grouping does too. Lakh grouping renders 125000 as "1,25,000", which
 * next to a "$" reads as a completely different number.
 */
describe("formatMoney", () => {
  it("shows a dollar sign and two decimals", () => {
    expect(formatMoney(14.64)).toBe("$14.64");
    expect(formatMoney(3.6)).toBe("$3.60");
  });

  it("keeps the cents on a whole amount, because a price is not a count", () => {
    expect(formatMoney(16)).toBe("$16.00");
  });

  it("groups thousands in threes, not lakhs", () => {
    expect(formatMoney(125000)).toBe("$125,000.00");
  });

  it("accepts the string the API actually sends", () => {
    // Decimal columns arrive as strings over JSON; passing one straight through
    // must not produce "$NaN".
    expect(formatMoney("48.91")).toBe("$48.91");
  });

  it("renders zero as a price rather than blank", () => {
    expect(formatMoney(0)).toBe("$0.00");
  });
});

describe("orderCode", () => {
  it("shortens a uuid into something a customer can read back on the phone", () => {
    expect(orderCode({ id: "6373b312-6d34-4c3f-8742-0b27b6336061" })).toBe("#6373B312");
  });
});

describe("scheduledFor", () => {
  const order = (overrides: Record<string, unknown>) =>
    ({ schedule_type: "SCHEDULED", ...overrides }) as Parameters<typeof scheduledFor>[0];

  it("says nothing about an ASAP order", () => {
    // Rendering "scheduled for" over something being cooked right now is worse
    // than rendering nothing.
    expect(scheduledFor(order({ schedule_type: "ASAP", scheduled_at: null }))).toBeNull();
    expect(scheduledFor(order({ scheduled_at: null }))).toBeNull();
  });

  it("names today and tomorrow rather than a date", () => {
    const today = new Date();
    today.setHours(19, 0, 0, 0);
    expect(scheduledFor(order({ scheduled_at: today.toISOString() }))).toMatch(/^Today at /);

    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    tomorrow.setHours(19, 0, 0, 0);
    expect(scheduledFor(order({ scheduled_at: tomorrow.toISOString() }))).toMatch(/^Tomorrow at /);
  });

  it("falls back to a weekday and date further out", () => {
    const later = new Date();
    later.setDate(later.getDate() + 4);
    later.setHours(12, 30, 0, 0);
    const text = scheduledFor(order({ scheduled_at: later.toISOString() }));
    expect(text).not.toMatch(/Today|Tomorrow/);
    expect(text).toMatch(/ at /);
  });

  it("reads the stored UTC instant in local time", () => {
    // The API returns Z-suffixed UTC. A 19:00 local booking must read back as
    // 7 in the evening, not whatever that instant is in UTC.
    const evening = new Date();
    evening.setDate(evening.getDate() + 1);
    evening.setHours(19, 0, 0, 0);
    expect(scheduledFor(order({ scheduled_at: evening.toISOString() }))).toContain("7:00");
  });

  it("ignores a value it cannot parse instead of printing Invalid Date", () => {
    expect(scheduledFor(order({ scheduled_at: "not-a-date" }))).toBeNull();
  });
});
