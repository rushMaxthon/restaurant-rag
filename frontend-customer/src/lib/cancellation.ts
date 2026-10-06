/**
 * What a customer reads on a cancelled order: why, and where their money is.
 *
 * Until 2026-10-06 every cancellation was automatic (an unpaid checkout
 * closed), and the page said so. Now the restaurant can cancel an order it
 * cannot make, so the reason it chose is shown in a customer's words - and
 * the refund in plain terms. A refund the gateway refused is the
 * restaurant's to fix, so its error is never shown here.
 */

export interface CancellationFields {
  cancellation_reason?: string | null;
  cancellation_note?: string | null;
  refund_status?: string | null;
}

const STAFF_REASONS: Record<string, string> = {
  OUT_OF_STOCK: "an item ran out",
  KITCHEN_UNAVAILABLE: "the kitchen can't take it right now",
  CUSTOMER_REQUEST: "you asked to cancel",
  DUPLICATE_OR_TEST: "it was a duplicate order",
  OTHER_BY_STAFF: "",
};

const AUTOMATIC: Record<string, string> = {
  PAYMENT_NOT_COMPLETED: "The payment wasn't completed, so the order was closed.",
  PAYMENT_ABANDONED: "The payment was left unfinished, so the order was closed.",
  PAYMENT_FAILED: "The payment didn't go through, so the order was closed.",
};

export function cancellationMessage(order: CancellationFields): { reason: string; money: string } {
  const code = order.cancellation_reason ?? "";
  let reason: string;
  if (code in STAFF_REASONS) {
    const why = STAFF_REASONS[code];
    reason = why
      ? `The restaurant cancelled your order: ${why}.`
      : "The restaurant cancelled your order.";
    if (order.cancellation_note) reason += ` “${order.cancellation_note}”`;
  } else {
    reason = AUTOMATIC[code] ?? "This order was cancelled.";
  }

  let money: string;
  switch (order.refund_status) {
    case "PENDING":
      money = "Your refund is on its way to how you paid.";
      break;
    case "REFUNDED":
      money = "Refunded in full to how you paid. Banks usually show it within 5-7 working days.";
      break;
    case "FAILED":
      money = "The restaurant is sorting out your refund and will return the full amount.";
      break;
    default:
      money = "Nothing was charged for this order.";
  }
  return { reason, money };
}
