import { expect, test } from "@playwright/test";
import { PAY_BUTTON, STORAGE_STATE_KEY, clickFixed, openScheduling, fillCart, fillCheckoutContact, fillField, payWithTestCard, resetApp, signIn } from "./helpers";

/**
 * What happens AFTER the card is accepted.
 *
 * Both halves of this were broken and neither would fail an existing test: the
 * basket survived a successful payment (so the same food could be paid for
 * twice), and the order page said "Card payment confirming..." until the
 * customer thought to reload, because nothing ever called the endpoint that
 * reconciles with Stripe.
 */
test("a paid order empties the cart and settles without a refresh", async ({ page }) => {
  await resetApp(page);
  await fillCart(page, 3);
  await signIn(page, "/checkout");

  await fillCheckoutContact(page);
  await openScheduling(page);
  const times = page.locator(".slot-grid .slot-chip");
  await times.first().waitFor({ state: "visible", timeout: 20_000 });
  await times.first().click();

  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await clickFixed(page, page.getByRole("button", { name: PAY_BUTTON }).first());
  await expect(page.getByRole("heading", { name: /pay for your order/i })).toBeVisible({
    timeout: 60_000,
  });

  await payWithTestCard(page);
  await page.waitForURL(/\/orders\/[0-9a-f-]{36}/, { timeout: 90_000 });

  // The order settles on its own. No reload here on purpose - the polling is
  // the thing being tested.
  await expect(page.getByText(/paid by card/i)).toBeVisible({ timeout: 45_000 });
  await expect(page.getByText(/confirming your payment/i)).toHaveCount(0);

  // And the basket is gone, so the same food cannot be bought twice.
  await expect(page.getByRole("link", { name: /cart with 0 items/i })).toBeVisible();
  // Read through the same tenant-scoped key the app writes — one deployment
  // serves every restaurant, so the storefront's keys carry the host that
  // selected the tenant. A literal `bangkok-bowl-state` here would find
  // nothing and report a cart length of -1, which the assertion below would
  // correctly call a failure for entirely the wrong reason.
  const stored = await page.evaluate((key) => {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw).cart as unknown[]).length : -1;
  }, STORAGE_STATE_KEY);
  expect(stored, "cart in localStorage after paying").toBe(0);
});
