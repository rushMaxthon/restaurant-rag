import { expect, test } from "@playwright/test";
import { fillCart, fillCheckoutContact, resetApp, signIn } from "./helpers";

/**
 * The bill has to add up on screen, not just in the response.
 *
 * On a real delivery order the summary read "Taxes and charges ₹29.85" and
 * opening it showed packaging ₹5, platform fee ₹10 and restaurant GST ₹7.50.
 * Three numbers that sum to ₹22.50 beside one that says ₹29.85. The fourth
 * line — GST on the delivery fee — and the panel's own total row were both
 * below the cut, because `.order-summary` set `overflow: hidden` to keep a
 * 3px decorative bar off its rounded corners and took the popover with it.
 *
 * Nothing was wrong with the data, which is exactly why this needs a browser:
 * a clip removes nothing from the DOM, so every assertion about text and
 * visibility passed while the customer could not see half the panel. The
 * check below is therefore geometric — does the panel fit inside the first
 * ancestor that clips? — and it generalises past this one decoration to any
 * future ancestor that starts clipping.
 */
test.describe("the taxes and charges breakdown", () => {
  test("opens fully, and its parts add up to the figure on the bill", async ({ page }) => {
    await resetApp(page);
    await signIn(page);
    await fillCart(page);

    await page.goto("/checkout");
    await fillCheckoutContact(page);

    // The summary row only opens when the server actually sent a breakdown.
    const opener = page.getByRole("button", { name: "Taxes and charges" });
    await opener.waitFor({ state: "visible", timeout: 30_000 });
    await opener.click();

    const panel = page.getByRole("dialog", { name: "Taxes and charges" });
    await expect(panel).toBeVisible();

    // 1. Nothing is cut off. Walk up from the panel to the first ancestor that
    //    clips, and require the panel to sit inside it. `toBeVisible` cannot
    //    see this: a clipped element still has a box and still has its text.
    const clipped = await panel.evaluate((el) => {
      const own = el.getBoundingClientRect();
      for (let node = el.parentElement; node; node = node.parentElement) {
        const cs = getComputedStyle(node);
        const clips = [cs.overflowX, cs.overflowY].some((v) => v !== "visible");
        if (!clips) continue;
        const box = node.getBoundingClientRect();
        return {
          by: node.className || node.tagName,
          cutBottom: Math.round(own.bottom - box.bottom),
          cutRight: Math.round(own.right - box.right),
        };
      }
      return null;
    });
    if (clipped) {
      expect(
        clipped,
        `the breakdown is cut off by .${clipped.by}`,
      ).toMatchObject({ cutBottom: expect.any(Number) });
      expect(clipped.cutBottom).toBeLessThanOrEqual(0);
      expect(clipped.cutRight).toBeLessThanOrEqual(0);
    }

    // 2. The parts add up to the whole. The panel repeats the total under a
    //    rule, so this compares what the customer can read against what they
    //    are being charged — which is the complaint that started this.
    const money = (text: string) => Number(text.replace(/[^\d.]/g, ""));
    const amounts = await panel.locator("dl dd").allInnerTexts();
    const total = money(
      (await panel.locator("div").last().locator("span").last().innerText()).trim(),
    );

    expect(amounts.length).toBeGreaterThanOrEqual(2);
    const sum = amounts.reduce((runningTotal, text) => runningTotal + money(text), 0);
    // To the paisa: every figure here is the server's, rounded by the server.
    expect(Math.abs(sum - total)).toBeLessThan(0.01);
  });
});
