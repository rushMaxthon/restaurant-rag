import { expect, test } from "@playwright/test";
import { branchIsOpen, fillCart, fillField, payWithTestCard, resetApp, signIn } from "./helpers";

/**
 * The whole journey, end to end, against the real backend and real Stripe.
 *
 * Every one of these covers something that was actually broken and shipped:
 * a login loop that produced a 4,000-character URL, a cart that let you reach
 * checkout after the branch had closed, an order that completed with no payment
 * step at all. None of them would have been caught by a unit test, because each
 * was a failure of wiring rather than of logic.
 */

test.describe("browsing without an account", () => {
  test("a guest can use the menu and the cart without being asked to sign in", async ({ page }) => {
    await resetApp(page);

    // Browsing used to demand an account. Asking someone to register before
    // they have seen the food is how you lose them.
    await page.goto("/menu");
    await expect(page).toHaveURL(/\/menu/);
    await expect(page.getByRole("button", { name: /^Add / }).first()).toBeVisible();

    await fillCart(page, 3);
    await page.goto("/cart");

    // The cart lives in localStorage, so it belongs to the browser, not the
    // account: a guest reaches it and sees their dishes, with no redirect.
    await expect(page).toHaveURL(/\/cart/);
    await expect(page.getByRole("article").first()).toBeVisible();

    // What the CTA says depends on the clock — a closed branch offers no
    // checkout at all — so the assertion is that it never demands an account
    // before it has to.
    await expect(page.getByRole("link", { name: /^continue to checkout/i })).toHaveCount(0);
  });

  test("the concierge answers a guest", async ({ page }) => {
    await resetApp(page);
    await page.goto("/concierge");
    await expect(page).toHaveURL(/\/concierge/);

    await page.waitForLoadState("networkidle");
    const composer = page.getByRole("textbox").first();
    await composer.click();
    await composer.pressSequentially("something spicy", { delay: 15 });
    await expect(composer).toHaveValue("something spicy");
    await page.keyboard.press("Enter");

    // A guest gets a real answer, not a sign-in wall. Asserted on the
    // conversation itself: the question echoed back, a reply, and dish cards.
    // Ollama is slow and variable locally, hence the long wait.
    await expect(page.getByText("something spicy").first()).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("article").first()).toBeVisible({ timeout: 170_000 });
    await expect(page.getByRole("link", { name: /^sign in/i })).toHaveCount(0);
  });
});

test.describe("the sign-in gate", () => {
  test("a gated route redirects once, and does not loop", async ({ page }) => {
    await resetApp(page);
    await page.goto("/checkout");
    await page.waitForURL(/\/login/);

    const url = page.url();
    // The bug produced roughly 4,000 characters of nested %2525252F.
    expect(url.length).toBeLessThan(120);
    expect(new URL(url).searchParams.get("redirect")).toBe("/checkout");
  });

  test("signing in returns you to where you were going", async ({ page }) => {
    await resetApp(page);
    await fillCart(page, 3);
    await signIn(page, "/checkout");
    await expect(page).toHaveURL(/\/checkout/);
  });
});

test.describe("placing and paying for an order", () => {
  test("card payment, scheduling for the next open window when closed", async ({ page }) => {
    await resetApp(page);
    await fillCart(page, 3);
    await signIn(page, "/checkout");
    await expect(page).toHaveURL(/\/checkout/);

    await fillField(page, "Full name", "Playwright Tester");
    await fillField(page, "Phone number", "9876543210");
    if (await page.getByLabel("Delivery address", { exact: true }).isVisible()) {
      await fillField(page, "Delivery address", "B-402 Riverside, Bodakdev, Ahmedabad");
    }

    // Outside opening hours the branch cannot take an ASAP order, so the UI
    // offers its next bookable window instead of letting the request fail at
    // the server. Whether this branch runs depends on the clock, which is why
    // the assertion below is about the outcome rather than the path.
    const slots = page.locator(".slot-chip");
    if ((await slots.count()) > 0) {
      await slots.first().click();
    }

    // Card is the only method: this product does not take cash.
    await expect(page.getByText(/pay by card/i)).toBeVisible();

    // Desktop submits from the sticky summary ("Pay $48.91"); below lg the
    // summary scrolls away and the bottom bar carries it ("Pay now"). Same
    // form, two different labels.
    const placeOrder = page.getByRole("button", { name: /^Pay (\$|now)/ });
    await placeOrder.first().scrollIntoViewIfNeeded();
    await placeOrder.first().click();

    // The order now exists as PAYMENT_PENDING and Stripe's Element is mounted.
    await expect(page.getByRole("heading", { name: /pay for your order/i })).toBeVisible({
      timeout: 60_000,
    });

    await payWithTestCard(page);

    // Stripe took the money and the app returned to the order. It stays
    // PAYMENT_PENDING until a verified webhook arrives — the browser saying
    // "it worked" is not evidence that money moved — so the assertion is that
    // we reached the order, not that it is paid.
    await page.waitForURL(/\/orders\/[0-9a-f-]{36}/, { timeout: 90_000 });
    await expect(page.getByText(/order #/i).first()).toBeVisible();
  });

  test("an order that was placed shows up in the history", async ({ page }) => {
    await resetApp(page);
    await signIn(page);
    await page.goto("/orders");

    await expect(page.getByRole("heading", { name: /your orders/i })).toBeVisible();
    await expect(page.getByText(/order #/i).first()).toBeVisible({ timeout: 30_000 });
  });
});

test.describe("branch opening hours", () => {
  test("a closed branch says when it opens instead of failing later", async ({ page }) => {
    await resetApp(page);
    await fillCart(page, 3);

    if (await branchIsOpen(page)) {
      test.skip(true, "Branch is open right now; the closed-branch path cannot be exercised.");
    }

    // What the customer used to get instead: a working Continue button, and a
    // rejection from the server after they had filled in everything.
    await expect(page.getByText(/is closed right now/i)).toBeVisible();
    await expect(page.getByText(/opens again/i)).toBeVisible();
    await expect(page.getByRole("button", { name: /closed right now/i })).toBeDisabled();
  });
});
