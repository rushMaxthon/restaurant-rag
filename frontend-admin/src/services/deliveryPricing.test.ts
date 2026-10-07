import { describe, expect, it } from "vitest";

import {
  addSlab,
  draftFrom,
  pricingFormError,
  removeSlab,
  slabRangeLabel,
  toPayload,
  withGst,
  type PricingDraft,
} from "./deliveryPricing";

/**
 * The admin's Delivery pricing page. The server holds the real rules
 * (`slabs.validate_update`); these repeat them so the form can say what is
 * wrong before anything is sent, and are tested because a wrong slab is a
 * price every customer on the platform pays at once.
 */

const SAVED = {
  slabs: [
    { up_to_km: 2, fee: "68.00" },
    { up_to_km: 5, fee: "78.00" },
    { up_to_km: null, fee: "100.00" },
  ],
  max_distance_km: 10,
  gst_percent: "18.00",
  saved: false,
  updated_at: null,
  updated_by_name: null,
};

const draft = (): PricingDraft => draftFrom(SAVED);

describe("the agreed list", () => {
  it("is valid as it comes from the server", () => {
    expect(pricingFormError(draft())).toBeNull();
  });

  it("reads as distance ranges ending at the delivery limit", () => {
    const d = draft();
    expect(slabRangeLabel(d, 0)).toBe("Up to 2 km");
    expect(slabRangeLabel(d, 1)).toBe("2 – 5 km");
    expect(slabRangeLabel(d, 2)).toBe("5 – 10 km");
  });

  it("goes back to the server with the last slab open-ended", () => {
    expect(toPayload(draft())).toEqual({
      slabs: [
        { up_to_km: 2, fee: "68.00" },
        { up_to_km: 5, fee: "78.00" },
        { up_to_km: null, fee: "100.00" },
      ],
      max_distance_km: 10,
      gst_percent: "18.00",
    });
  });
});

describe("what the customer pays", () => {
  it("adds GST and rounds to the paisa", () => {
    expect(withGst("68", "18")).toBe(80.24);
    expect(withGst("78", "18")).toBe(92.04);
    expect(withGst("100", "18")).toBe(118);
  });

  it("is null while a field is not a number", () => {
    expect(withGst("", "18")).toBeNull();
    expect(withGst("68", "abc")).toBeNull();
  });
});

describe("what cannot be saved", () => {
  const withSlabs = (slabs: PricingDraft["slabs"]): PricingDraft => ({ ...draft(), slabs });

  it("a slab that does not go further than the one before", () => {
    const d = withSlabs([
      { upToKm: "5", fee: "78" },
      { upToKm: "2", fee: "68" },
      { upToKm: "", fee: "100" },
    ]);
    expect(pricingFormError(d)).toMatch(/further than the one before/);
  });

  it("a slab past the delivery limit", () => {
    expect(pricingFormError({ ...draft(), maxDistanceKm: "4" })).toMatch(/past the 4 km/);
  });

  it("a missing or negative fee", () => {
    expect(pricingFormError(withSlabs([{ upToKm: "", fee: "" }]))).toMatch(/fee/i);
    expect(pricingFormError(withSlabs([{ upToKm: "", fee: "-5" }]))).toMatch(/negative/);
  });

  it("a missing distance on a slab that is not the last", () => {
    const d = withSlabs([
      { upToKm: "", fee: "68" },
      { upToKm: "", fee: "100" },
    ]);
    expect(pricingFormError(d)).toMatch(/distance/i);
  });

  it("GST outside 0-28%", () => {
    expect(pricingFormError({ ...draft(), gstPercent: "40" })).toMatch(/28%/);
  });

  it("no delivery limit", () => {
    expect(pricingFormError({ ...draft(), maxDistanceKm: "0" })).toMatch(/how far/i);
  });
});

describe("adding and removing slabs", () => {
  it("a new slab goes before the open-ended last one, a kilometre further", () => {
    const d = addSlab(draft());
    expect(d.slabs.map((slab) => slab.upToKm)).toEqual(["2", "5", "6", ""]);
    expect(d.slabs[2].fee).toBe("100.00");
  });

  it("removing the last slab makes the one before it the open end", () => {
    const d = removeSlab(draft(), 2);
    expect(toPayload(d).slabs).toEqual([
      { up_to_km: 2, fee: "68.00" },
      { up_to_km: null, fee: "78.00" },
    ]);
  });

  it("the only slab cannot be removed", () => {
    const one = removeSlab(removeSlab(draft(), 0), 0);
    expect(removeSlab(one, 0).slabs).toHaveLength(1);
  });
});
