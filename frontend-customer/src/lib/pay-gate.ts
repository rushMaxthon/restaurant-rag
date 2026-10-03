/**
 * Why the Pay button is disabled, in words the customer can act on.
 *
 * A disabled button with no explanation is a dead end, and this one had three
 * ways of becoming one. The worst was a branch with no usable payment method:
 * `canSubmit` asked whether STRIPE was available, which was the same question
 * back when card was the only way to pay and silently stopped being it — so a
 * restaurant settling through Razorpay alone showed a complete checkout with
 * both Pay buttons dead and nothing on screen to say why. The gate was fixed;
 * the silence was not.
 *
 * The cart screen already had the right pattern: its button says "Closed right
 * now" or "Minimum ₹150 to order" instead of a greyed-out "Continue". This is
 * that, for checkout, in one function — because there are TWO Pay buttons (the
 * sticky summary on desktop, the fixed bar on a phone) and they must not
 * disagree about whether an order can be placed or about why it cannot.
 *
 * Progress is deliberately NOT a reason here. "Preparing your order…" is the
 * button already doing its job, not a problem to explain, so the caller keeps
 * that separate — see `payButtonLabel`.
 */

export type PayBlock = {
  /** Short enough to replace the button's own label. */
  label: string;
  /**
   * Whether `label` should take the button over, rather than only appear
   * beside it.
   *
   * False for anything the customer is one tap from clearing. Two reasons,
   * and the second is the important one:
   *
   * - renaming the primary action for a momentary state is louder than the
   *   state deserves, and
   * - the button's accessible name is how the e2e suite finds it. `PAY_BUTTON`
   *   in `e2e/helpers.ts` matches /^Pay (now|currency)/ and five specs use it.
   *   Changing the name for every block broke
   *   `order-flow.spec.ts:246`, which checks that choosing "Schedule for
   *   later" without a time disables Pay — a test about a real bug (the
   *   payload used to fall back to ASAP, so someone who asked for later was
   *   charged for now).
   */
  replacesLabel: boolean;
  /**
   * The sentence underneath, when the label cannot carry the whole answer.
   *
   * Null where the label says everything — a second line repeating it is
   * noise, and on a phone it pushes the button off the screen.
   */
  detail: string | null;
};

export type PayGateInput = {
  cartCount: number;
  /** How many methods this BRANCH can actually settle. Not the deployment's. */
  payableMethodCount: number;
  /** True when the customer chose "Schedule for later". */
  scheduling: boolean;
  /** Whether a time was picked. Only meaningful while `scheduling`. */
  hasSlot: boolean;
  /** False until the delivery fee is known, which needs a located address. */
  deliveryKnown: boolean;
};

/**
 * The first thing standing between this customer and a placed order.
 *
 * Ordered by what they should do next, not by how the checks happen to be
 * written: an empty cart is answered on another screen, a branch that cannot
 * take money is not their problem to fix, a missing time is one tap away, and
 * an address is the longest thing to type so it comes last.
 */
export function payBlock(input: PayGateInput): PayBlock | null {
  if (input.cartCount <= 0) {
    return {
      label: "Your cart is empty",
      replacesLabel: true,
      detail: "Add something from the menu and it will appear here.",
    };
  }

  if (input.payableMethodCount <= 0) {
    // Nothing the customer can do, so this says so rather than implying they
    // have missed a step. It is also the case that used to be silent.
    return {
      // Takes the button over, because offering to take a payment that cannot
      // be taken is the same promise the gateway sheets were making while
      // their SDKs had not loaded.
      label: "Payment unavailable",
      replacesLabel: true,
      detail:
        "This branch cannot take payments online just now. Your cart is saved — please try again shortly, or call the restaurant to order.",
    };
  }

  if (input.scheduling && !input.hasSlot) {
    return {
      label: "Choose a time first",
      // The button keeps saying "Pay …" — see `replacesLabel`.
      replacesLabel: false,
      // No detail, because the schedule step ALREADY says "Pick a time to
      // continue." right beside the chips, which is better placement than the
      // bottom of a summary panel: it is next to the control that fixes it.
      // The label above still earns its place on a phone, where the fixed Pay
      // bar is visible long after that message has scrolled away.
      detail: null,
    };
  }

  if (!input.deliveryKnown) {
    // Kept as the long-standing wording, because it is already on screen and
    // reads as an instruction rather than a refusal.
    // Long-standing wording and long-standing placement: it has always taken
    // the button over, reads as an instruction rather than a refusal, and
    // `order-flow.spec.ts` accounts for it by name.
    return { label: "Add your address to continue", replacesLabel: true, detail: null };
  }

  return null;
}

/**
 * What the Pay button says, in every state it has.
 *
 * One function so the two buttons cannot drift — which is the same reason the
 * gate itself is one function. `priceLabel` is passed in rather than computed:
 * the amount is formatted in the tenant's own currency by `useMoney`, and the
 * phone bar deliberately shows "Pay now" instead because the total is already
 * beside it on that layout.
 */
export function payButtonLabel(options: {
  block: PayBlock | null;
  submitting: boolean;
  /** True once the gateway is being opened rather than the order prepared. */
  openingPayment: boolean;
  /** "Pay ₹157.50", or null to use the short form. */
  priceLabel: string | null;
}): string {
  // Progress beats everything: once the order is going out, why it could not
  // have gone out a moment ago is no longer the useful thing to say.
  if (options.submitting) {
    return options.openingPayment ? "Opening payment…" : "Preparing your order…";
  }
  if (options.block?.replacesLabel) return options.block.label;
  return options.priceLabel ?? "Pay now";
}
