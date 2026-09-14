import { expect, test } from "@playwright/test";
import {
  clickFixed,
  fillCart,
  fillField,
  forceBranchClosed,
  payWithTestCard,
  resetApp,
  resetAppFirstVisit,
  signIn,
} from "./helpers";

/**
 * The whole journey, end to end, against the real backend and real Stripe.
 *
 * Every one of these covers something that was actually broken and shipped:
 * a login loop that produced a 4,000-character URL, a cart that let you reach
 * checkout after the branch had closed, an order that completed with no payment
 * step at all. None of them would have been caught by a unit test, because each
 * was a failure of wiring rather than of logic.
 */

test.describe("choosing a branch", () => {
  test("a first-time visitor picks a branch before seeing a menu", async ({ page }) => {
    await resetAppFirstVisit(page);

    // Branches of one restaurant do not carry the same food, so the app asks
    // rather than choosing silently. It is a modal, which means it also has to
    // be dismissible in one tap or it is a wall in front of the whole product.
    const gate = page.getByRole("dialog");
    await expect(gate).toBeVisible();
    await expect(gate.getByRole("heading", { name: /which branch/i })).toBeVisible();

    const options = gate.locator(".branch-gate__option");
    await expect(options.first()).toBeVisible();
    const branchName = (await options.first().locator(".branch-gate__name").innerText()).trim();
    await options.first().click();

    // Gone, and the branch it was told about is the one the header now shows.
    await expect(gate).toHaveCount(0);
    await expect(page.getByText(branchName.slice(0, 12)).first()).toBeVisible();

    // And it stays gone: a gate that reappears on every visit is a tax.
    await page.reload();
    await expect(page.getByRole("dialog")).toHaveCount(0);
  });

  test("the menu is reachable once a branch is chosen", async ({ page }) => {
    await resetAppFirstVisit(page);
    await page.getByRole("dialog").locator(".branch-gate__option").first().click();
    await page.goto("/menu");
    await expect(page.getByRole("button", { name: /^Add / }).first()).toBeVisible({
      timeout: 30_000,
    });
  });
});

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
    // A time, specifically: `.slot-chip` also matches the day chips now, and
    // picking a day leaves the order without a time and the Pay button
    // disabled. Scheduling is offered whether or not the branch is open, so
    // when it is open the "Schedule for later" tab has to be opened first.
    const later = page.getByRole("button", { name: /schedule for later/i });
    if (await later.count()) await later.click();

    const times = page.locator(".slot-grid .slot-chip");
    await times.first().waitFor({ state: "visible", timeout: 20_000 });
    await times.first().click();

    // Card is the only method: this product does not take cash.
    await expect(page.getByText(/pay by card/i)).toBeVisible();

    // Desktop submits from the sticky summary ("Pay $48.91"); below lg the
    // summary scrolls away and a fixed bottom bar carries it ("Pay now"). Same
    // form, two different labels — and below lg the fixed bar needs
    // clickFixed, which explains itself in helpers.ts.
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    const placeOrder = page.getByRole("button", { name: /^Pay (\$|now)/ }).first();
    await clickFixed(page, placeOrder);

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

test.describe("choosing when the order arrives", () => {
  test("a closed branch leads into scheduling instead of stopping the order", async ({ page }) => {
    await resetApp(page);
    await fillCart(page, 3);
    await forceBranchClosed(page);
    await signIn(page, "/cart");

    // The whole point of the change: closed is a detour, not a wall.
    await page.getByRole("link", { name: /schedule for later/i }).click();
    await expect(page).toHaveURL(/\/checkout/);

    // Closed, scheduling is the only mode, so there is no ASAP tab to dismiss.
    await expect(page.getByText(/is closed right now/i)).toBeVisible();
    await expect(page.getByRole("button", { name: /as soon as possible/i })).toHaveCount(0);

    const times = page.locator(".slot-grid .slot-chip");
    await times.first().waitFor({ state: "visible", timeout: 20_000 });
    await expect(page.getByText(/pick a time to continue/i)).toBeVisible();
    await times.first().click();
    await expect(page.getByText(/(arriving|ready) (today|tomorrow|\w{3},)/i)).toBeVisible();
  });

  test("choosing Schedule for later will not quietly place an ASAP order", async ({ page }) => {
    await resetApp(page);
    await fillCart(page, 3);
    await signIn(page, "/checkout");

    const later = page.getByRole("button", { name: /schedule for later/i });
    // Only meaningful while the branch is open; closed, scheduling is forced.
    if (!(await later.count())) {
      test.skip(true, "Branch is shut, so scheduling is already the only mode.");
    }
    await later.click();

    // No time picked yet. The button used to stay live and the payload fell
    // back to ASAP, so someone who asked for later was charged for now.
    const pay = page.getByRole("button", { name: /^Pay (\$|now)/ }).first();
    await expect(pay).toBeDisabled();
    await expect(page.getByText(/pick a time to continue/i)).toBeVisible();

    // And it comes back once a time exists.
    await page.locator(".slot-grid .slot-chip").first().click();
    await expect(pay).toBeEnabled();
  });

  test("the earliest slot is offered as one tap", async ({ page }) => {
    await resetApp(page);
    await fillCart(page, 3);
    await signIn(page, "/checkout");
    const later = page.getByRole("button", { name: /schedule for later/i });
    if (await later.count()) await later.click();

    // The soonest time the kitchen can manage, promoted out of the grid.
    const earliest = page.getByRole("button", { name: /earliest available/i });
    await expect(earliest).toBeVisible();
    await earliest.click();
    await expect(page.getByText(/(arriving|ready) (today|tomorrow|\w{3},)/i)).toBeVisible();
  });

  test("a custom time can be typed, and a closed-hours one is refused", async ({ page }) => {
    await resetApp(page);
    await fillCart(page, 3);
    await signIn(page, "/checkout");
    const later = page.getByRole("button", { name: /schedule for later/i });
    if (await later.count()) await later.click();

    const field = page.locator('.time-field input[type="time"]');
    await expect(field).toBeVisible();

    // The bounds come from the branch's own window minus its prep time, so a
    // time the kitchen could not cook by is outside min/max by construction.
    const min = await field.getAttribute("min");
    const max = await field.getAttribute("max");
    expect(min).toMatch(/^\d{2}:\d{2}$/);
    expect(max).toMatch(/^\d{2}:\d{2}$/);
    expect(max! > min!).toBe(true);

    await field.fill(max!);
    await expect(page.getByText(/(arriving|ready) /i)).toBeVisible();

    // Midnight is never inside a window here; the picker must say so itself
    // rather than let the server reject it after payment details are entered.
    await field.fill("00:00");
    await expect(page.getByText(/that time is not available/i)).toBeVisible();
  });

  test("the date field books a day the chips do not reach", async ({ page }) => {
    await resetApp(page);
    await fillCart(page, 3);
    await signIn(page, "/checkout");

    const later = page.getByRole("button", { name: /schedule for later/i });
    if (await later.count()) await later.click();

    const date = page.locator('.date-field input[type="date"]');
    await expect(date).toBeVisible();

    // Six days out, which is past the visible chips and inside the branch's
    // horizon. Typed as the value the input actually carries, so this fails if
    // the yyyy-mm-dd round trip ever shifts a day across the UTC boundary -
    // the bug that sends someone's dinner to the wrong evening.
    const target = new Date();
    target.setDate(target.getDate() + 6);
    const yyyy = target.getFullYear();
    const mm = String(target.getMonth() + 1).padStart(2, "0");
    const dd = String(target.getDate()).padStart(2, "0");
    await date.fill(`${yyyy}-${mm}-${dd}`);
    await expect(date).toHaveValue(`${yyyy}-${mm}-${dd}`);

    // The heading above the times names the day that was chosen, in words.
    const expected = new Intl.DateTimeFormat("en-CA", {
      weekday: "short",
      day: "numeric",
      month: "short",
    }).format(target);
    await expect(page.getByText(expected, { exact: false }).first()).toBeVisible();

    const times = page.locator(".slot-grid .slot-chip");
    await times.first().waitFor({ state: "visible", timeout: 20_000 });
    await times.first().click();
    await expect(page.getByText(expected, { exact: false }).first()).toBeVisible();
  });
});

test.describe("branch opening hours", () => {
  test("a closed branch says when it opens instead of failing later", async ({ page }) => {
    await resetApp(page);
    await fillCart(page, 3);
    await forceBranchClosed(page);
    await page.goto("/cart");

    // Two things used to go wrong here, in opposite directions. First the
    // Continue button worked and the server rejected the order after the
    // customer had filled everything in. Then it was disabled, which was
    // honest about "closed" and wrong about "cannot order" — the server takes
    // scheduled orders and checkout offers them, so the cart was ending the
    // journey in front of a door that was open.
    await expect(page.getByText(/is closed right now/i)).toBeVisible();
    await expect(page.getByText(/opens again/i)).toBeVisible();
    await expect(page.getByText(/order now and choose when you want it/i)).toBeVisible();

    // The hours are one tap away rather than a paragraph nobody reads.
    await page.getByText(/see opening hours/i).click();
    await expect(page.getByRole("heading", { name: /(delivery|pickup) hours/i })).toBeVisible();

    // And the way forward is a real link into scheduling, not a dead button.
    const ahead = page.getByRole("link", { name: /(schedule for later|sign in to schedule)/i });
    await expect(ahead).toBeVisible();
  });
});
