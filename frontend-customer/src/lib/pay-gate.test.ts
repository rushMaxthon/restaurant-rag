import { describe, expect, it } from "vitest";

import { payBlock, payButtonLabel, type PayGateInput } from "./pay-gate";

/**
 * A disabled Pay button always says why.
 *
 * Asked for on 2026-10-03: "if the button is disable then we need to show user
 * what's the issue why it's disable right". The checkout had three ways to be
 * dead and silent, and one of them had already happened in production: a
 * branch settling through Razorpay alone showed a complete checkout with both
 * Pay buttons greyed out, because the gate asked whether STRIPE was available.
 * That gate was fixed earlier; nothing was ever added to explain the state to
 * the customer while it lasted.
 *
 * The rule lives here rather than in the component because there are TWO Pay
 * buttons — the sticky summary and the phone bar — and a rule written in a
 * component is a rule the other copy cannot read.
 */

const READY: PayGateInput = {
  cartCount: 3,
  payableMethodCount: 1,
  scheduling: false,
  hasSlot: false,
  deliveryKnown: true,
};

describe("payBlock", () => {
  it("is null when the order can be placed", () => {
    expect(payBlock(READY)).toBeNull();
  });

  it("never returns a block without words in it", () => {
    // The whole point. A truthy block with an empty label would render a
    // button that is disabled and blank, which is the bug with extra steps.
    const inputs: PayGateInput[] = [
      { ...READY, cartCount: 0 },
      { ...READY, payableMethodCount: 0 },
      { ...READY, scheduling: true, hasSlot: false },
      { ...READY, deliveryKnown: false },
    ];
    for (const input of inputs) {
      const block = payBlock(input);
      expect(block, JSON.stringify(input)).not.toBeNull();
      expect(block!.label.trim().length, JSON.stringify(input)).toBeGreaterThan(0);
    }
  });

  it("explains a branch that cannot take money, and does not blame the customer", () => {
    const block = payBlock({ ...READY, payableMethodCount: 0 });
    expect(block?.label).toBe("Payment unavailable");
    // There is nothing for them to fix here, so the detail has to offer a way
    // round rather than an instruction they cannot follow.
    expect(block?.detail).toMatch(/try again|call the restaurant/i);
    expect(block?.detail).toMatch(/cart is saved/i);
  });

  it("asks for a time when one is being scheduled and none is picked", () => {
    const block = payBlock({ ...READY, scheduling: true, hasSlot: false });
    expect(block?.label).toBe("Choose a time first");
    // Beside the button, not instead of it.
    expect(block?.replacesLabel).toBe(false);
    // And no detail: the schedule step already says "Pick a time to continue."
    // next to the chips, which is where somebody looking for a time is
    // looking. Repeating it under the total would be noise on desktop.
    expect(block?.detail).toBeNull();
  });

  it("only takes the button over when pressing it could never work", () => {
    // The distinction `replacesLabel` exists for. A missing time clears with
    // one tap; a branch that cannot take money does not.
    expect(payBlock({ ...READY, payableMethodCount: 0 })?.replacesLabel).toBe(true);
    expect(payBlock({ ...READY, cartCount: 0 })?.replacesLabel).toBe(true);
    expect(payBlock({ ...READY, scheduling: true, hasSlot: false })?.replacesLabel).toBe(false);
  });

  it("does not ask for a time when the order is for now", () => {
    // `hasSlot` is meaningless unless `scheduling`, and reading it anyway
    // would block every ASAP order.
    expect(payBlock({ ...READY, scheduling: false, hasSlot: false })).toBeNull();
  });

  it("asks for an address last, because it is the longest thing to type", () => {
    // With two problems at once, the quicker one is named first — being told
    // to type an address and THEN that there is no time picked is two
    // round trips for one order.
    const both = payBlock({ ...READY, scheduling: true, hasSlot: false, deliveryKnown: false });
    expect(both?.label).toBe("Choose a time first");
  });

  it("names the empty cart before anything else", () => {
    // Everything else is unanswerable without items, and the answer is on
    // another screen.
    const everything = payBlock({
      cartCount: 0,
      payableMethodCount: 0,
      scheduling: true,
      hasSlot: false,
      deliveryKnown: false,
    });
    expect(everything?.label).toBe("Your cart is empty");
  });

  it("treats a negative count like an empty one", () => {
    // Defensive rather than expected: `<= 0` is used so a count that somehow
    // goes negative blocks rather than letting an empty order through.
    expect(payBlock({ ...READY, cartCount: -1 })?.label).toBe("Your cart is empty");
    expect(payBlock({ ...READY, payableMethodCount: -1 })?.label).toBe("Payment unavailable");
  });
});

describe("payButtonLabel", () => {
  it("shows the price when nothing is in the way", () => {
    expect(
      payButtonLabel({
        block: null,
        submitting: false,
        openingPayment: false,
        priceLabel: "Pay ₹157.50",
      }),
    ).toBe("Pay ₹157.50");
  });

  it("falls back to the short form where there is no room for a price", () => {
    // The phone bar shows the total beside the button, so repeating it there
    // would be the same number twice in one row.
    expect(
      payButtonLabel({ block: null, submitting: false, openingPayment: false, priceLabel: null }),
    ).toBe("Pay now");
  });

  it("keeps saying the price for a block the customer is about to clear", () => {
    // A missing time does NOT rename the button. The reason appears beside it
    // instead — see `replacesLabel`, and `order-flow.spec.ts:246`, which finds
    // this button by its name.
    expect(
      payButtonLabel({
        block: { label: "Choose a time first", replacesLabel: false, detail: null },
        submitting: false,
        openingPayment: false,
        priceLabel: "Pay ₹157.50",
      }),
    ).toBe("Pay ₹157.50");
  });

  it("says why instead of a price when the button cannot work at all", () => {
    expect(
      payButtonLabel({
        block: { label: "Payment unavailable", replacesLabel: true, detail: null },
        submitting: false,
        openingPayment: false,
        priceLabel: "Pay ₹157.50",
      }),
    ).toBe("Payment unavailable");
  });

  it("lets progress beat the reason", () => {
    // Once the order is on its way out, why it could not have gone a moment
    // ago is no longer the useful thing to read — and the block may still be
    // momentarily true while the request is in flight.
    expect(
      payButtonLabel({
        block: { label: "Choose a time first", replacesLabel: false, detail: null },
        submitting: true,
        openingPayment: false,
        priceLabel: null,
      }),
    ).toBe("Preparing your order…");
  });

  it("distinguishes preparing the order from opening the gateway", () => {
    // Two different waits with two different lengths. "Preparing" covers the
    // order call; "Opening payment" covers Stripe's iframe or Razorpay's
    // window, which is the slower and more alarming of the two to sit in
    // front of unlabelled.
    expect(
      payButtonLabel({ block: null, submitting: true, openingPayment: true, priceLabel: null }),
    ).toBe("Opening payment…");
  });
});

describe("an address further than the restaurant delivers", () => {
  // Under slab pricing (2026-10-07) the server REFUSES a delivery past the
  // branch's limit, and the quote says so with a fee of 0.00. Leaving Pay live
  // would let a customer press it and be refused after typing everything.
  const tooFar: PayGateInput = { ...READY, outOfRange: { distanceKm: 12.5, limitKm: 10 } };

  it("blocks Pay and says how far, and how far they deliver", () => {
    const block = payBlock(tooFar);
    expect(block?.label).toBe("Too far to deliver");
    expect(block?.replacesLabel).toBe(true);
    expect(block?.detail).toContain("12.5 km");
    expect(block?.detail).toContain("10 km");
  });

  it("is not a block once the address is in range", () => {
    expect(payBlock({ ...READY, outOfRange: null })).toBeNull();
  });

  it("an unknown address is still the first thing to fix", () => {
    expect(payBlock({ ...tooFar, deliveryKnown: false })?.label).toBe(
      "Add your address to continue",
    );
  });
});
