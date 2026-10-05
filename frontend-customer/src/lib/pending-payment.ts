import { STORAGE, readTenant, removeTenant, writeTenant } from "@/lib/tenant-storage";

/**
 * A payment the customer has started but not finished.
 *
 * This lives in storage as well as in the checkout's state, so that a reload
 * can resume it. It has to: the cart is cleared the moment a payment succeeds,
 * and the payment sheet was component state only — so refreshing the page
 * while a gateway's window was open dropped the order's id and left the
 * customer on an empty address form with a paid order they could no longer
 * reach. Reported 2026-10-03 as "if I refresh it keeps me on the last screen,
 * but the current one goes back to the address screen".
 *
 * Everything stored here is either public — the gateway's own publishable key
 * is in this page's source — or useless without the server's verification: the
 * order ids name an order the server re-checks on every call. That is what
 * makes it safe to write into a store the customer can read.
 *
 * It is NOT safe to TRUST on the way back in, which is a different question.
 * The customer can edit it, so the shape is checked field by field, and the
 * checkout then asks the server what state that order is really in rather than
 * believing the word "pending" written in a browser.
 */
export type PendingPayment = {
  orderId: string;
  orderNumber: string;
  /**
   * Stripe's client secret, or — for Razorpay, which has no such thing — the
   * Razorpay ORDER id that its Checkout window is opened against. The name
   * comes from the provider contract rather than from either gateway.
   */
  clientSecret: string;
  publishableKey: string;
  method: "CARD" | "RAZORPAY";
};

/**
 * The payment under way, if the stored value is a whole one.
 *
 * Returns null rather than throwing for anything it does not recognise. A
 * half-written or hand-edited value must not render a payment sheet with no
 * order behind it — a Pay button that cannot work is worse than no sheet,
 * because the customer presses it.
 */
export function readPendingPayment(): PendingPayment | null {
  const raw = readTenant(STORAGE.pendingPayment);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<PendingPayment>;
    if (
      typeof parsed.orderId === "string" &&
      parsed.orderId.length > 0 &&
      typeof parsed.orderNumber === "string" &&
      typeof parsed.clientSecret === "string" &&
      parsed.clientSecret.length > 0 &&
      typeof parsed.publishableKey === "string" &&
      parsed.publishableKey.length > 0 &&
      (parsed.method === "CARD" || parsed.method === "RAZORPAY")
    ) {
      return {
        orderId: parsed.orderId,
        orderNumber: parsed.orderNumber,
        clientSecret: parsed.clientSecret,
        publishableKey: parsed.publishableKey,
        method: parsed.method,
      };
    }
  } catch {
    // Corrupt. Treated as absent; the next payment overwrites it.
  }
  return null;
}

export function writePendingPayment(value: PendingPayment): void {
  writeTenant(STORAGE.pendingPayment, JSON.stringify(value));
}

export function clearPendingPayment(): void {
  removeTenant(STORAGE.pendingPayment);
}

/**
 * May the checkout reopen a payment window for this order?
 *
 * Deliberately stricter than the test `/orders/$orderId` uses to decide it is
 * "confirming payment", which is `PAYMENT_PENDING` and not COD. That is right
 * for a screen that WATCHES an order and wrong for one that would charge it
 * again: `PAYMENT_PENDING` with `payment_status: PAID` is the gap between a
 * settled payment and the status advancing, and in that gap the customer has
 * already paid. Reusing the looser test there would reopen a gateway over a
 * paid order, which is the one outcome worse than the bug being fixed.
 *
 * COD is excluded for a different reason: a cash order sits at
 * `PAYMENT_PENDING` until the rider is handed the money, so nothing the
 * customer does on this screen can ever resolve it.
 */
export function canResumePayment(order: { status: string; payment_status: string }): boolean {
  return (
    order.status === "PAYMENT_PENDING" &&
    order.payment_status !== "COD" &&
    order.payment_status !== "PAID"
  );
}
