import { expect, test, type Page } from "@playwright/test";
import { fillCart, fillField, forceBranchClosed, resetApp, signIn } from "./helpers";

/**
 * The phone layout, measured rather than eyeballed.
 *
 * Desktop is skipped: these assertions are about a 393px screen and a
 * fingertip, and they are trivially true at 1280px.
 *
 * The reference width is `window.innerWidth`, not documentElement.clientWidth.
 * Under Chromium's Pixel 5 emulation the two disagree on checkout (393 against
 * 551) and that gap is present with no app code involved - it survives
 * removing Stripe's injected frame and predates this suite. Measuring app
 * elements against the width they are actually laid out in still catches the
 * thing that matters: one element sticking out past the rest of the page.
 */
test.describe("mobile layout", () => {
  // The conditional form only receives fixtures, not testInfo, so the project
  // check goes in a beforeEach where testInfo is a real argument.
  test.beforeEach(({}, testInfo) => {
    test.skip(testInfo.project.name !== "mobile", "phone-sized screens only");
  });

  async function assertFits(page: Page, where: string) {
    const report = await page.evaluate(() => {
      const width = window.innerWidth;
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
      return { width, over };
    });
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
});
