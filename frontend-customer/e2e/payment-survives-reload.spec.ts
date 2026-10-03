import { expect, test } from "@playwright/test";
import {
  PAY_BUTTON,
  chooseCardPayment,
  choosePickup,
  clickFixed,
  fillCart,
  fillCheckoutContact,
  openScheduling,
  resetApp,
  signIn,
} from "./helpers";

/**
 * A payment under way survives a reload, and a finished one does not reopen.
 *
 * Reported 2026-10-03: "if I pay and also navigate too, but if I do page
 * refresh then still keep me on last screen right? because that's the point —
 * current one is going back to address screen while do refresh".
 *
 * The payment sheet was component state and nothing else, so a reload dropped
 * the order's id and the gateway's. That alone would be recoverable, except
 * the cart is cleared the moment a payment succeeds — so what the customer
 * actually got was an empty address form, with a paid order they could no
 * longer reach from anywhere on the page.
 *
 * Driven with card rather than Razorpay because Razorpay's window cannot be
 * paid by a test. The persistence being checked is the same code either way:
 * the sheet is restored from one stored value, and `method` only decides which
 * component it renders. The Razorpay-specific half — that a successful payment
 * NAVIGATES rather than silently clearing the cart — is covered by
 * `src/lib/pending-payment.test.ts` and by the handler being one function.
 */
test.describe("a payment under way", () => {
  test("is still there after a reload", async ({ page }) => {
    await resetApp(page);
    // Collection, deliberately — the same choice `mobile-layout` makes, for a
    // related reason. This test needs to REACH a payment sheet, and whether a
    // delivery order can be placed depends on the address autocomplete
    // answering: when the suggestion service is slow, `fillCheckoutContact`
    // falls through to a typed address, which the server then refuses for
    // carrying no coordinates. That refusal is correct and has its own tests;
    // here it would be a flake in a test about persistence.
    await choosePickup(page);
    await fillCart(page, 3);
    await signIn(page, "/checkout");

    await fillCheckoutContact(page);
    await openScheduling(page);
    const times = page.locator(".slot-grid .slot-chip");
    await times.first().waitFor({ state: "visible", timeout: 20_000 });
    await times.first().click();

    await chooseCardPayment(page);
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await clickFixed(page, page.getByRole("button", { name: PAY_BUTTON }).first());

    const sheet = page.getByRole("heading", { name: /pay for your order/i });
    await expect(sheet).toBeVisible({ timeout: 60_000 });

    // The order number is on the sheet ("Order BB-1042 is held for you"), and
    // it is what proves the SAME payment came back rather than a new one.
    const held = page.getByText(/is held for you/i);
    await expect(held).toBeVisible();
    const before = await held.textContent();

    await page.reload();

    // The bug: this used to be the address form, because `pending` was gone.
    await expect(sheet, "the payment sheet survives a reload").toBeVisible({ timeout: 30_000 });
    await expect(held).toHaveText(before!.trim(), { timeout: 15_000 });

    // And emphatically not back at step one.
    await expect(page.getByLabel(/^Address line 1/)).toHaveCount(0);
  });

  test("is not reopened once the order has moved on", async ({ page }) => {
    // The other direction, and the one that would be worse to get wrong: a
    // stored payment for an order that is no longer awaiting one must send the
    // customer to that order, not reopen a gateway over it.
    //
    // Written against a storage value rather than a real settled payment,
    // because settling one needs a webhook this test cannot deliver. What is
    // being checked is the restore decision, which reads the order from the
    // server either way.
    await resetApp(page);
    await signIn(page, "/orders");

    // A real order of this customer's that is NOT payment-pending. Taken from
    // their own history, so the id is one the server will return to them.
    const settled = await page.evaluate(async () => {
      const token = Object.keys(window.localStorage)
        .filter((k) => k.endsWith(":token"))
        .map((k) => window.localStorage.getItem(k))[0];
      const reply = await fetch("http://127.0.0.1:8000/api/orders", {
        headers: { Authorization: `Bearer ${token}`, "X-Forwarded-Host": window.location.hostname },
      });
      const body = await reply.json();
      const rows = Array.isArray(body) ? body : (body.items ?? []);
      return (
        rows.find((o: { status: string }) => o.status !== "PAYMENT_PENDING")?.id ??
        null
      );
    });
    test.skip(!settled, "this account has no order past PAYMENT_PENDING to test against");

    await page.evaluate((orderId) => {
      const key = `storefront:${window.location.hostname.toLowerCase()}:pending-payment`;
      window.localStorage.setItem(
        key,
        JSON.stringify({
          orderId,
          orderNumber: "BB-0000",
          clientSecret: "pi_stale_secret",
          publishableKey: "pk_test_stale",
          method: "CARD",
        }),
      );
    }, settled);

    await page.goto("/checkout");

    // Sent to the order, not handed a payment window for one already paid.
    await page.waitForURL(new RegExp(`/orders/${settled}`), { timeout: 30_000 });
    await expect(page.getByRole("heading", { name: /pay for your order/i })).toHaveCount(0);

    // And the stale value is gone, so this does not happen again on the next
    // visit to the checkout.
    const left = await page.evaluate(() =>
      window.localStorage.getItem(
        `storefront:${window.location.hostname.toLowerCase()}:pending-payment`,
      ),
    );
    expect(left, "the stale payment is cleared, not just ignored").toBeNull();
  });
});
