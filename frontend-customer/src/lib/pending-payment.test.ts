import { beforeEach, describe, expect, it } from "vitest";

import {
  canResumePayment,
  clearPendingPayment,
  readPendingPayment,
  writePendingPayment,
  type PendingPayment,
} from "./pending-payment";
import { STORAGE, tenantKey } from "./tenant-storage";

/**
 * A payment survives a reload, and a finished one does not reopen.
 *
 * Two halves of one report, on 2026-10-03: a successful Razorpay payment left
 * the customer on the checkout instead of the order, and refreshing the page
 * "goes back to the address screen".
 *
 * Both came from the payment sheet being component state and nothing else.
 * Razorpay is a modal over the page — unlike Stripe, which is handed a
 * `returnUrl` and redirects the browser itself — so when its handler resolved,
 * the cart was cleared and nothing moved. The checkout re-rendered with an
 * empty cart, which is the address step. A reload lost the order's id outright.
 *
 * Writing it down is only half the fix, and the easier half. The value lives
 * in a store the customer can read and edit, so these tests are mostly about
 * what happens when it is not what we wrote.
 */

const VALID: PendingPayment = {
  orderId: "7a1c9f2e-0000-4000-8000-000000000001",
  orderNumber: "BB-1042",
  clientSecret: "order_QkLm9ZxYwVuT",
  publishableKey: "rzp_test_PUBLICKEY01",
  method: "RAZORPAY",
};

/**
 * A localStorage stub rather than jsdom.
 *
 * `vitest.config.ts` runs these in `environment: "node"` and neither jsdom nor
 * happy-dom is installed — the same reason `guest-preferences.test.ts` has one
 * of these, and the same shape, because the module only touches
 * getItem/setItem/removeItem.
 */
function installStorage(): void {
  const held = new Map<string, string>();
  (globalThis as { window?: unknown }).window = {
    localStorage: {
      getItem: (key: string) => held.get(key) ?? null,
      setItem: (key: string, value: string) => void held.set(key, value),
      removeItem: (key: string) => void held.delete(key),
      clear: () => held.clear(),
    },
    // A hostname, because these keys are scoped to the tenant being served.
    // Without one the assertions would pass against a fallback key.
    location: { hostname: "bhagwati-bakery.localhost" },
  };
}

function store(value: unknown): void {
  window.localStorage.setItem(
    tenantKey(STORAGE.pendingPayment),
    typeof value === "string" ? value : JSON.stringify(value),
  );
}

describe("readPendingPayment", () => {
  beforeEach(() => installStorage());

  it("reads back exactly what was written", () => {
    writePendingPayment(VALID);
    expect(readPendingPayment()).toEqual(VALID);
  });

  it("is null when nothing is stored", () => {
    expect(readPendingPayment()).toBeNull();
  });

  it("is null after it is cleared", () => {
    writePendingPayment(VALID);
    clearPendingPayment();
    expect(readPendingPayment()).toBeNull();
  });

  it("survives a value that is not JSON at all", () => {
    // Anything can end up in localStorage, including another tool's value
    // under a colliding key. Throwing here would take the checkout down.
    store("not json {");
    expect(readPendingPayment()).toBeNull();
  });

  it("refuses a half-written payment", () => {
    // The failure that matters: a sheet rendered from this would show a Pay
    // button with no order behind it, and the customer would press it.
    const { clientSecret: _omitted, ...withoutSecret } = VALID;
    store(withoutSecret);
    expect(readPendingPayment()).toBeNull();
  });

  it("refuses an empty id, secret or key", () => {
    for (const field of ["orderId", "clientSecret", "publishableKey"] as const) {
      store({ ...VALID, [field]: "" });
      expect(readPendingPayment(), `empty ${field}`).toBeNull();
    }
  });

  it("refuses a method no gateway here can settle", () => {
    // `method` chooses which component renders. An unknown value would fall
    // through to the Stripe branch and mount a card form against a Razorpay
    // order id.
    store({ ...VALID, method: "BITCOIN" });
    expect(readPendingPayment()).toBeNull();
    store({ ...VALID, method: "COD" });
    expect(readPendingPayment()).toBeNull();
  });

  it("keeps only the fields it knows", () => {
    // Extra keys are dropped rather than passed through, so nothing a page
    // writes here can reach a component as a prop it did not expect.
    store({ ...VALID, is_admin: true, amount: 99999 });
    expect(readPendingPayment()).toEqual(VALID);
  });

  it("accepts an order number that is empty, because that is cosmetic", () => {
    // It is printed in a sentence ("Order BB-1042 is held for you"). A missing
    // one reads a little worse; it is not a reason to lose the payment.
    store({ ...VALID, orderNumber: "" });
    expect(readPendingPayment()?.orderId).toBe(VALID.orderId);
  });
});

describe("storage that fights back", () => {
  /**
   * Every accessor here can throw, and one of them throwing must not cost the
   * customer their checkout.
   *
   * `localStorage` throws outright in some privacy modes rather than returning
   * null, and `setItem` throws when the origin's quota is full. The cost of
   * that is a payment that cannot be resumed after a reload — annoying. The
   * cost of letting it propagate is the checkout failing to render at all,
   * which is the thing being fixed, made worse.
   */
  beforeEach(() => installStorage());

  it("reads nothing rather than throwing when storage is blocked", () => {
    window.localStorage.getItem = () => {
      throw new Error("SecurityError");
    };
    expect(() => readPendingPayment()).not.toThrow();
    expect(readPendingPayment()).toBeNull();
  });

  it("gives up quietly when there is no room to write", () => {
    window.localStorage.setItem = () => {
      throw new Error("QuotaExceededError");
    };
    expect(() => writePendingPayment(VALID)).not.toThrow();
  });

  it("gives up quietly when it cannot clear", () => {
    // This one matters more than it looks: clearing happens right after a
    // payment succeeds, immediately before navigating to the order. An
    // exception here would strand a customer who HAS paid on the checkout —
    // precisely the bug this module exists to fix.
    window.localStorage.removeItem = () => {
      throw new Error("SecurityError");
    };
    expect(() => clearPendingPayment()).not.toThrow();
  });

  it("is safe with no window at all", () => {
    // Server-side rendering. The checkout route renders on the server before
    // it ever reaches a browser, so these run with no `window` in scope.
    const saved = (globalThis as { window?: unknown }).window;
    delete (globalThis as { window?: unknown }).window;
    try {
      expect(readPendingPayment()).toBeNull();
      expect(() => writePendingPayment(VALID)).not.toThrow();
      expect(() => clearPendingPayment()).not.toThrow();
    } finally {
      (globalThis as { window?: unknown }).window = saved;
    }
  });
});

describe("canResumePayment", () => {
  it("is true for an order a gateway has not settled yet", () => {
    expect(canResumePayment({ status: "PAYMENT_PENDING", payment_status: "PENDING" })).toBe(true);
  });

  it("is false once the payment landed", () => {
    // The restore path turns on this: true here would reopen a payment window
    // over an order that is already paid.
    expect(canResumePayment({ status: "PLACED", payment_status: "PAID" })).toBe(false);
    expect(canResumePayment({ status: "PAYMENT_PENDING", payment_status: "PAID" })).toBe(false);
  });

  it("is false for cash on delivery", () => {
    // A COD order sits at PAYMENT_PENDING until the rider is handed the money.
    // Nothing on the checkout screen can advance that, so resuming a payment
    // sheet for it would be an unclosable loop.
    expect(canResumePayment({ status: "PAYMENT_PENDING", payment_status: "COD" })).toBe(false);
  });

  it("is false for an order that was cancelled", () => {
    expect(canResumePayment({ status: "CANCELLED", payment_status: "PENDING" })).toBe(false);
  });
});
