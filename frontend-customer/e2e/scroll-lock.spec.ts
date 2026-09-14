import { expect, test } from "@playwright/test";
import { resetApp } from "./helpers";

/**
 * Opening a menu must not resize the page.
 *
 * Radix locks scrolling through react-remove-scroll, which hides the page
 * scrollbar and pads the body by that scrollbar's width to replace the space.
 * This page already reserves the track permanently (`html { scrollbar-gutter:
 * stable }`), so the compensation lands on top of a gap that never went away
 * and the content narrows by the scrollbar's width the moment a dropdown opens.
 *
 * Headless Chromium draws OVERLAY scrollbars, which occupy no layout space, so
 * a plain "open it and measure" test passes whether or not the bug is fixed and
 * proves nothing. The width is therefore forced: the test injects the same rule
 * react-remove-scroll injects, with a real 10px value, and asserts the app's
 * own rule still wins. That is exactly the thing being fixed - one stylesheet
 * overriding another that carries !important and is added later.
 */
test.describe("opening a menu", () => {
  test("does not shift the page when the scrollbar is hidden", async ({ page }) => {
    await resetApp(page);
    await page.goto("/menu");
    await page.waitForLoadState("networkidle");
    await page.locator(".sort-select").first().waitFor({ state: "visible", timeout: 30_000 });

    // Stand in for a classic 10px scrollbar, exactly as the library writes it.
    await page.addStyleTag({
      content: `body[data-scroll-locked] {
        overflow: hidden !important;
        padding-right: 10px !important;
        margin-right: 10px !important;
      }`,
    });

    const cardBefore = await page.locator("article").first().boundingBox();
    await page.locator(".sort-select").first().click();
    await expect(page.getByRole("option", { name: /price: low to high/i })).toBeVisible();

    const locked = await page.evaluate(() => ({
      attr: document.body.getAttribute("data-scroll-locked"),
      padRight: getComputedStyle(document.body).paddingRight,
      marginRight: getComputedStyle(document.body).marginRight,
    }));

    // The lock really is on, so the override is being exercised.
    expect(locked.attr).toBe("1");
    expect(locked.padRight).toBe("0px");
    expect(locked.marginRight).toBe("0px");

    // And nothing moved.
    const cardDuring = await page.locator("article").first().boundingBox();
    expect(Math.round(cardDuring!.x)).toBe(Math.round(cardBefore!.x));
    expect(Math.round(cardDuring!.width)).toBe(Math.round(cardBefore!.width));
  });

  test("the menu is usable on a phone", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "mobile", "phone-sized screens only");

    await resetApp(page);
    await page.goto("/menu");
    await page.waitForLoadState("networkidle");

    const trigger = page.locator(".sort-select").first();
    await trigger.waitFor({ state: "visible", timeout: 30_000 });
    await expect(trigger).toHaveJSProperty("offsetHeight", 48);

    const before = await page.evaluate(() => document.documentElement.clientWidth);
    await trigger.click();

    const option = page.getByRole("option", { name: /top rated/i });
    await expect(option).toBeVisible();

    // Measured after the open animation, not during it. Radix zooms the panel
    // in from 95%, so a height read mid-flight is 5% short and the assertion
    // would be about the animation rather than the layout.
    await page
      .waitForFunction(
        () => document.getAnimations().every((a) => a.playState !== "running"),
        null,
        {
          timeout: 5000,
        },
      )
      .catch(() => undefined);

    // The list has to fit the screen and be reachable with a thumb.
    const box = (await option.boundingBox())!;
    const width = await page.evaluate(() => document.documentElement.clientWidth);
    expect(width).toBe(before);
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(width + 1);
    // 44px is the fingertip minimum the rest of this app already meets.
    expect(box.height).toBeGreaterThanOrEqual(44);

    // And it actually sorts.
    await option.click();
    await expect(trigger).toContainText(/top rated/i);
  });
});
