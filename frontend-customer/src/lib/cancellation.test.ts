import { describe, expect, it } from "vitest";

import { cancellationMessage } from "./cancellation";

describe("cancellationMessage", () => {
  it("tells the customer the restaurant cancelled it, and why", () => {
    const message = cancellationMessage({
      cancellation_reason: "OUT_OF_STOCK",
      cancellation_note: "Paneer finished",
      refund_status: "PENDING",
    });
    expect(message.reason).toBe(
      "The restaurant cancelled your order: an item ran out. “Paneer finished”",
    );
    expect(message.money).toMatch(/refund is on its way/i);
  });

  it("says when the money is back", () => {
    expect(
      cancellationMessage({ cancellation_reason: "CUSTOMER_REQUEST", refund_status: "REFUNDED" })
        .money,
    ).toMatch(/refunded in full/i);
  });

  it("never shows a customer the gateway's error", () => {
    const money = cancellationMessage({
      cancellation_reason: "OUT_OF_STOCK",
      refund_status: "FAILED",
    }).money;
    expect(money).toMatch(/restaurant is sorting out your refund/i);
  });

  it("says nothing was charged when nothing was", () => {
    expect(
      cancellationMessage({ cancellation_reason: "KITCHEN_UNAVAILABLE", refund_status: null })
        .money,
    ).toBe("Nothing was charged for this order.");
  });

  it("explains an unpaid order closed by itself", () => {
    const message = cancellationMessage({
      cancellation_reason: "PAYMENT_NOT_COMPLETED",
      refund_status: null,
    });
    expect(message.reason).toBe("The payment wasn't completed, so the order was closed.");
  });
});
