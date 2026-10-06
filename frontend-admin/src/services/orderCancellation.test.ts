import { describe, expect, it } from "vitest";

import { CANCEL_REASONS, cancelFormError, cancellationSummary, refundLine } from "./orderCancellation";

describe("cancel reasons", () => {
  it("offers the five staff reasons, in plain words", () => {
    expect(CANCEL_REASONS.map((reason) => reason.value)).toEqual([
      "OUT_OF_STOCK",
      "KITCHEN_UNAVAILABLE",
      "CUSTOMER_REQUEST",
      "DUPLICATE_OR_TEST",
      "OTHER_BY_STAFF",
    ]);
    for (const reason of CANCEL_REASONS) expect(reason.label).toBeTruthy();
  });
});

describe("cancelFormError", () => {
  it("needs a reason", () => {
    expect(cancelFormError(null, "")).toBe("Choose why the order is being cancelled.");
  });

  it("needs a note when the reason is Other", () => {
    expect(cancelFormError("OTHER_BY_STAFF", "   ")).toBe("Say why in the note.");
    expect(cancelFormError("OTHER_BY_STAFF", "Wrong branch")).toBeNull();
  });

  it("is happy with any other reason and no note", () => {
    expect(cancelFormError("OUT_OF_STOCK", "")).toBeNull();
  });
});

describe("refundLine", () => {
  it("says nothing when nothing was owed back", () => {
    expect(refundLine({ refund_status: null, refund_error: null })).toBeNull();
  });

  it("says where the refund stands, with the gateway's words when it failed", () => {
    expect(refundLine({ refund_status: "PENDING", refund_error: null })?.tone).toBe("pending");
    expect(refundLine({ refund_status: "REFUNDED", refund_error: null })?.text).toMatch(/refunded in full/i);
    const failed = refundLine({ refund_status: "FAILED", refund_error: "insufficient balance" });
    expect(failed?.tone).toBe("failed");
    expect(failed?.text).toContain("insufficient balance");
  });
});

describe("cancellationSummary", () => {
  it("names the reason, who, and the note", () => {
    expect(
      cancellationSummary({
        cancellation_reason: "OUT_OF_STOCK",
        cancelled_by: "OWNER",
        cancellation_note: "Paneer finished",
      }),
    ).toBe("Item out of stock · cancelled by the owner · “Paneer finished”");
  });

  it("explains an automatic cancellation", () => {
    expect(
      cancellationSummary({ cancellation_reason: "PAYMENT_NOT_COMPLETED", cancelled_by: "SYSTEM", cancellation_note: null }),
    ).toBe("Payment was never completed · cancelled automatically");
  });
});
