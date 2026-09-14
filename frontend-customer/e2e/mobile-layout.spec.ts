import { expect, test, type Page } from "@playwright/test";
import { clickFixed, fillCart, fillField, forceBranchClosed, resetApp, signIn } from "./helpers";

/**
 * The phone layout, measured rather than eyeballed.
 *
 * Desktop is skipped: these assertions are about a 393px screen and a
 * fingertip, and they are trivially true at 1280px.
 *
 * `window.innerWidth` is asserted to still BE the device width. That is not a
 * formality. Checkout used to lay out at 551px on a 393px phone, because the
 * two-column grid declared `lg:grid-cols-[minmax(0,1fr)_420px]` and nothing at
 * the base breakpoint - so the implicit mobile column was `auto` and sized to
 * the widest thing inside it, the horizontally scrolling day rail. Chromium
 * responded by zooming the whole page out to fit, which is why the text looked
 * slightly small on checkout and nowhere else, and why the page could be
 * panned sideways. Nothing overflowed its parent, so an overflow check alone
 * never saw it.
 */ test.describe("mobile layout", () => {
  // The conditional form only receives fixtures, not testInfo, so the project
  // check goes in a beforeEach where testInfo is a real argument.
  test.beforeEach(({}, testInfo) => {
    test.skip(testInfo.project.name !== "mobile", "phone-sized screens only");
  });

  async function assertFits(page: Page, where: string) {
    const report = await page.evaluate(() => {
      const width = window.innerWidth;
      const layout = document.documentElement.clientWidth;
      const over: string[] = [];
      for (const el of document.querySelectorAll("main *")) {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;
        // A rail that scrolls its own overflow is doing it on purpose, and so
        // are its children — the day chips are MEANT to run off the edge of a
        // phone, that is what makes the rail swipeable. So the whole subtree of
        // a horizontal scroller is exempt, not just the scroller itself.
        let inScroller = false;
        for (let a: Element | null = el; a && a !== document.body; a = a.parentElement) {
          if (["auto", "scroll"].includes(getComputedStyle(a).overflowX)) {
            inScroller = true;
            break;
          }
        }
        if (inScroller) continue;
        if (r.right > width + 1 || r.left < -1) {
          over.push(
            `${el.tagName}.${el.className.toString().slice(0, 40)} [${Math.round(r.left)}..${Math.round(r.right)}]`,
          );
        }
      }
      return { width, layout, over };
    });
    // The page must be laid out AT the device width, not zoomed out to fit a
    // wider layout. These diverge silently; see the note at the top.
    expect(
      report.width,
      `${where} is laid out at ${report.width}px on a ${report.layout}px screen`,
    ).toBe(report.layout);
    expect(report.over, `${where} has elements outside the ${report.width}px viewport`).toEqual([]);
  }

  async function assertTappable(page: Page, selector: string) {
    const small = await page.evaluate((sel) => {
      return [...document.querySelectorAll(sel)]
        .map((el) => ({
          text: el.textContent?.trim().slice(0, 16),
          height: Math.round(el.getBoundingClientRect().height),
        }))
        .filter((x) => x.height > 0 && x.height < 44);
    }, selector);
    // 44px is the fingertip minimum both Apple and Google publish. Below it
    // people miss, and a miss on a time chip books the wrong slot.
    expect(small, `${selector} below the 44px touch minimum`).toEqual([]);
  }

  test("the closed cart explains itself without spilling off the screen", async ({ page }) => {
    await resetApp(page);
    await fillCart(page, 3);
    await forceBranchClosed(page);
    await signIn(page, "/cart");

    await assertFits(page, "closed cart");
    await page.getByText(/see opening hours/i).click();
    await assertFits(page, "closed cart with hours open");
    await assertTappable(page, ".hours-disclosure > summary");

    // The week's hours are a two-column grid that used to be the first thing
    // to overflow when a branch had a long window like "10:30 am - 11 pm".
    await expect(page.locator(".hours-row").first()).toBeVisible();
  });

  test("the scheduling picker fits and every chip is thumb-sized", async ({ page }) => {
    await resetApp(page);
    await fillCart(page, 3);
    await signIn(page, "/checkout");
    await fillField(page, "Full name", "Tester");

    const later = page.getByRole("button", { name: /schedule for later/i });
    if (await later.count()) await later.click();
    await page.locator(".slot-grid .slot-chip").first().waitFor({ state: "visible" });

    await assertFits(page, "scheduling picker");
    await assertTappable(page, ".slot-chip");
    await assertTappable(page, ".date-field");
  });
  test("every main screen is laid out at the device width", async ({ page }) => {
    await resetApp(page);
    await fillCart(page, 3);

    // Guest-reachable screens first, then the signed-in ones. The zoom-out bug
    // hit exactly one route, so checking one route would not have caught it.
    for (const path of ["/", "/menu", "/cart", "/concierge"]) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      await assertFits(page, path);
    }

    await signIn(page, "/checkout");
    await assertFits(page, "/checkout");

    for (const path of ["/orders", "/account"]) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      await assertFits(page, path);
    }
  });

  test("the dish detail page is laid out at the device width", async ({ page }) => {
    await resetApp(page);
    await page.goto("/menu");
    await page.getByRole("article").first().getByRole("link").first().click();
    await page.waitForURL(/\/menu\/[^/]+$/);
    await page.waitForLoadState("networkidle");
    await assertFits(page, "dish detail");
  });
  test("the payment sheet fits the phone and its controls are reachable", async ({ page }) => {
    await resetApp(page);
    await fillCart(page, 3);
    await signIn(page, "/checkout");

    await fillField(page, "Full name", "Playwright Tester");
    await fillField(page, "Phone number", "9876543210");
    if (await page.getByLabel("Delivery address", { exact: true }).isVisible()) {
      await fillField(page, "Delivery address", "B-402 Riverside, Bodakdev, Ahmedabad");
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
    // Stripe mounts its Element in an iframe; wait for it before measuring, or
    // the sheet is measured empty and proves nothing.
    await page.locator('iframe[name^="__privateStripeFrame"]').first().waitFor({ timeout: 30_000 });
    await page.waitForTimeout(1500);

    await assertFits(page, "payment sheet");
    await assertTappable(page, 'button[type="submit"]');
  });
});
