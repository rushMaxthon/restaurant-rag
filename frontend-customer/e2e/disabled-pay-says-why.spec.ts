import { expect, test } from "@playwright/test";
import {
  choosePickup,
  fillCart,
  fillCheckoutContact,
  openScheduling,
  resetApp,
  signIn,
} from "./helpers";

/**
 * A Pay button that cannot be pressed says why.
 *
 * Asked for on 2026-10-03: "if the button is disable then we need to show user
 * what's the issue why it's disable right". The cart screen already did this —
 * its button reads "Closed right now" or "Minimum ₹150 to order" rather than
 * going quietly grey — and checkout only did it for a missing address.
 *
 * The state driven here is "Schedule for later with no time picked", because
 * it is the one a customer can reach in a few clicks. The other three are
 * covered in `src/lib/pay-gate.test.ts`, where they can be stated directly
 * instead of being engineered on screen: an empty cart cannot reach checkout
 * at all, and a branch with no payment method is admin data.
 *
 * Collection rather than delivery, so this does not depend on the address
 * autocomplete answering — see the note in `fillCheckoutContact`.
 */
test.describe("a Pay button that cannot be pressed", () => {
  test("says why, and becomes pressable when the reason is answered", async ({ page }) => {
    await resetApp(page);
    await choosePickup(page);
    await fillCart(page, 3);
    await signIn(page, "/checkout");
    await fillCheckoutContact(page);

    // "Schedule for later" without choosing a time, through the helper.
    //
    // Driving the toggle by hand here failed: it is a `button`, not a `tab`,
    // and more importantly `openScheduling` waits for the step's heading
    // first. Immediately after sign-in the checkout route is still rendering
    // while the session hydrates, so a bare `isVisible()` answers false, the
    // click is skipped, and the test then waits twenty seconds for slots that
    // were never asked for. That race is exactly why the helper exists.
    //
    // It returns false when the branch is CLOSED, which offers no toggle
    // because scheduling is then the only mode — in which case the page
    // already starts in the state being tested.
    await openScheduling(page);

    const slots = page.locator(".slot-grid .slot-chip");
    await slots.first().waitFor({ state: "visible", timeout: 20_000 });

    // Nothing picked yet, so the order cannot be placed.
    const pay = page.getByRole("button", { name: /^Pay |payment unavailable/i }).first();
    await expect(pay).toBeDisabled();

    // The reason is on the screen. WHERE depends on the layout, by design:
    //
    // - the schedule step says "Pick a time to continue." beside the chips,
    //   which is the best placement there is for this one — next to the
    //   control that fixes it — and it predates this work
    // - the fixed Pay bar on a phone adds "Choose a time first", because by
    //   the time a thumb reaches that bar the schedule step has scrolled away
    //
    // So the assertion is that SOMETHING visible explains it, rather than
    // that a particular element does. Asserting the summary panel carried it
    // would have been asserting a duplicate of a better message.
    const explained = page
      .locator(".pay-reason:visible")
      .or(page.getByText(/pick a time to continue/i))
      .first();
    await expect(explained, "a disabled Pay button explains itself").toBeVisible();

    // And answering it makes the button pressable, which is what turns the
    // message into an instruction rather than a dead end.
    await slots.first().click();
    await expect(page.getByRole("button", { name: /^Pay /i }).first()).toBeEnabled();
  });

  test("keeps the reason legible and the button tappable on a phone", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "mobile", "phone-sized screens only");

    await resetApp(page);
    await choosePickup(page);
    await fillCart(page, 3);
    await signIn(page, "/checkout");
    await fillCheckoutContact(page);

    await openScheduling(page);
    await page.locator(".slot-grid .slot-chip").first().waitFor({ state: "visible", timeout: 20_000 });

    await expect(page.locator(".pay-reason:visible")).toHaveText(/time/i);

    // The reason goes ABOVE the row rather than inside the button, because the
    // button is `flex-1` on a 393px screen: a sentence in it would either
    // shrink the tap target below the 44px floor or run off the edge. Both are
    // asserted, because either one would make the fix worse than the silence.
    const bar = await page.evaluate(() => {
      const button = [...document.querySelectorAll(".above-tab-bar button")].at(-1);
      const box = button?.getBoundingClientRect();
      return {
        height: box ? Math.round(box.height) : 0,
        right: box ? Math.round(box.right) : 0,
        width: window.innerWidth,
      };
    });
    expect(bar.height, "the Pay button stays thumb-sized").toBeGreaterThanOrEqual(44);
    expect(bar.right, "the Pay button stays on screen").toBeLessThanOrEqual(bar.width + 1);
  });
});
