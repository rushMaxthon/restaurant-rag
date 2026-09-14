import { expect, test } from "@playwright/test";
import { clickFixed, fillCart, fillField, resetApp, signIn } from "./helpers";

/**
 * A customer whose device is nowhere near the restaurant.
 *
 * Opening hours, slots and cutoffs are written in the restaurant's clock and
 * validated there. The app used to build those times with `setHours`, which
 * reads the DEVICE clock — so on a machine in the same zone as the branch
 * everything looked right, which is exactly why it survived this long. Run the
 * browser in Toronto against a branch in Ahmedabad and the old code turned the
 * branch's 7pm window into the customer's own 7pm, sent an instant nine and a
 * half hours out, and the server refused it after the form was filled in.
 *
 * The assertions are deliberately about the JOURNEY rather than about a
 * particular clock face: the branch's hours are seeded data and the suite runs
 * at whatever time it runs. What must hold is that a customer half a world
 * away is offered times the server then accepts.
 */
test.describe("ordering from another timezone", () => {
  test.use({ timezoneId: "America/Toronto", locale: "en-CA" });

  test("the times offered are the branch's, and the server takes them", async ({ page }) => {
    await resetApp(page);

    // Sanity: the browser really is in Toronto, or this proves nothing.
    const deviceZone = await page.evaluate(() => Intl.DateTimeFormat().resolvedOptions().timeZone);
    expect(deviceZone).toBe("America/Toronto");

    await fillCart(page, 3);
    await signIn(page, "/checkout");
    await fillField(page, "Full name", "Toronto Tester");
    await fillField(page, "Phone number", "9876543210");
    if (await page.getByLabel("Delivery address", { exact: true }).isVisible()) {
      await fillField(page, "Delivery address", "B-402 Riverside, Bodakdev");
    }

    const later = page.getByRole("button", { name: /schedule for later/i });
    if (await later.count()) await later.click();

    const times = page.locator(".slot-grid .slot-chip");
    await times.first().waitFor({ state: "visible", timeout: 20_000 });
    await times.first().click();
    await expect(page.getByText(/(arriving|ready) /i).first()).toBeVisible();

    // The real proof: the server accepts the slot this device picked. Under the
    // old code the order was refused here with "not available for the selected
    // time", after everything above had been filled in.
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await clickFixed(page, page.getByRole("button", { name: /^Pay (\$|now)/ }).first());
    await expect(page.getByRole("heading", { name: /pay for your order/i })).toBeVisible({
      timeout: 60_000,
    });
  });

  test("two devices on opposite sides of the world see the same times", async ({ browser }) => {
    // The sharpest form of the question. The branch keeps one clock, so the
    // slots offered must not depend on where the customer is standing. Under
    // the old code these two lists differed by the offset between the zones.
    async function timesSeenFrom(timezoneId: string): Promise<string[]> {
      const context = await browser.newContext({ timezoneId, locale: "en-CA" });
      const page = await context.newPage();
      try {
        await resetApp(page);
        await fillCart(page, 3);
        await signIn(page, "/checkout");
        const later = page.getByRole("button", { name: /schedule for later/i });
        if (await later.count()) await later.click();
        const chips = page.locator(".slot-grid .slot-chip");
        await chips.first().waitFor({ state: "visible", timeout: 20_000 });
        return await chips.allInnerTexts();
      } finally {
        await context.close();
      }
    }

    const toronto = await timesSeenFrom("America/Toronto");
    const kolkata = await timesSeenFrom("Asia/Kolkata");

    expect(toronto.length).toBeGreaterThan(0);
    expect(toronto).toEqual(kolkata);
  });
});
