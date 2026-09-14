import { expect, test } from "@playwright/test";
import { clickFixed, fillCart, fillField, payWithTestCard, resetApp, signIn } from "./helpers";

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

  await fillField(page, "Full name", "Settle Tester");
  await fillField(page, "Phone number", "9876543210");
  if (await page.getByLabel("Delivery address", { exact: true }).isVisible()) {
    await fillField(page, "Delivery address", "B-402 Riverside, Bodakdev");
  }
  const later = page.getByRole("button", { name: /schedule for later/i });
  if (await later.count()) await later.click();
  const times = page.locator(".slot-grid .slot-chip");
  await times.first().waitFor({ state: "visible", timeout: 20_000 });
  await times.first().click();

  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await clickFixed(page, page.getByRole("button", { name: /^Pay (\$|now)/ }).first());
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
  const stored = await page.evaluate(() => {
    const raw = localStorage.getItem("bangkok-bowl-state");
    return raw ? (JSON.parse(raw).cart as unknown[]).length : -1;
  });
  expect(stored, "cart in localStorage after paying").toBe(0);
});
