/**
 * Cancelling an order from the admin panel: the reasons, the form rule, and
 * how a cancelled order's refund is described. Kept out of the components so
 * the words and the rule can be tested without rendering a dialog.
 *
 * The server holds the real rules (`services/order_cancellation.py`): who may
 * cancel, until when, and that "Other" needs a note. This repeats the last
 * one only so the form can say so before sending.
 */

export type StaffCancelReason =
  | "OUT_OF_STOCK"
  | "KITCHEN_UNAVAILABLE"
  | "CUSTOMER_REQUEST"
  | "DUPLICATE_OR_TEST"
  | "OTHER_BY_STAFF";

export const CANCEL_REASONS: Array<{ value: StaffCancelReason; label: string }> = [
  { value: "OUT_OF_STOCK", label: "Item out of stock" },
  { value: "KITCHEN_UNAVAILABLE", label: "Kitchen closed or too busy" },
  { value: "CUSTOMER_REQUEST", label: "Customer asked to cancel" },
  { value: "DUPLICATE_OR_TEST", label: "Duplicate or test order" },
  { value: "OTHER_BY_STAFF", label: "Other (say why)" },
];

/** Every reason an order can carry, including the automatic ones. */
const REASON_LABELS: Record<string, string> = {
  ...Object.fromEntries(CANCEL_REASONS.map((reason) => [reason.value, reason.label])),
  OTHER_BY_STAFF: "Other",
  PAYMENT_NOT_COMPLETED: "Payment was never completed",
  PAYMENT_ABANDONED: "Customer left the payment",
  PAYMENT_FAILED: "Payment failed",
  UNKNOWN: "Reason not recorded",
};

const ACTOR_WORDS: Record<string, string> = {
  ADMIN: "cancelled by the platform admin",
  OWNER: "cancelled by the owner",
  KITCHEN: "cancelled by the kitchen",
  CUSTOMER: "cancelled by the customer",
  PAYMENT_PROVIDER: "cancelled by the payment provider",
  SYSTEM: "cancelled automatically",
};

export function cancelFormError(reason: StaffCancelReason | null, note: string): string | null {
  if (!reason) return "Choose why the order is being cancelled.";
  if (reason === "OTHER_BY_STAFF" && !note.trim()) return "Say why in the note.";
  return null;
}

export interface RefundFields {
  refund_status?: string | null;
  refund_error?: string | null;
}

/** One line on where a cancelled order's money is, or null if none was owed. */
export function refundLine(order: RefundFields): { tone: "pending" | "done" | "failed"; text: string } | null {
  switch (order.refund_status) {
    case "PENDING":
      return { tone: "pending", text: "Refund on its way: the full amount is being returned to the customer." };
    case "REFUNDED":
      return {
        tone: "done",
        text: "Refunded in full. Banks usually show it to the customer within 5-7 working days.",
      };
    case "FAILED":
      return {
        tone: "failed",
        text: `Refund failed${order.refund_error ? `: ${order.refund_error}` : "."} Fix the cause, then try again.`,
      };
    default:
      return null;
  }
}

export interface CancellationFields {
  cancellation_reason?: string | null;
  cancelled_by?: string | null;
  cancellation_note?: string | null;
}

export function cancellationSummary(order: CancellationFields): string {
  const parts = [REASON_LABELS[order.cancellation_reason ?? ""] ?? "Cancelled"];
  if (order.cancelled_by) parts.push(ACTOR_WORDS[order.cancelled_by] ?? "cancelled");
  if (order.cancellation_note) parts.push(`“${order.cancellation_note}”`);
  return parts.join(" · ");
}
