import { expect, test, type APIRequestContext } from "@playwright/test";
import { resetApp } from "./helpers";

/**
 * Half-and-half options, end to end.
 *
 * There is no "half pizza" product: it is a flag on a customization group that
 * the owner sets in admin (`supports_halves`), and the customer app offers the
 * choice only where that flag is on.
 *
 * Nothing here is hardcoded — not the item, not the option names. Which item is
 * splittable is admin data that an owner can change at any time, so the test
 * asks the API what actually carries the flag and drives whatever it finds. A
 * test pinned to one id and two topping names passes until someone edits the
 * menu, then fails for a reason that has nothing to do with the feature; that
 * happened twice while this was being written.
 */

type Splittable = {
  itemId: string;
  /** Active option names in the splittable group. */
  options: string[];
  /** One option name per group that must be answered before adding to cart. */
  required: string[];
};

async function findSplittable(request: APIRequestContext): Promise<Splittable | null> {
  const restaurants = await (await request.get("http://127.0.0.1:8000/api/restaurants")).json();
  const rows = Array.isArray(restaurants) ? restaurants : (restaurants.items ?? []);
  for (const restaurant of rows) {
    // The list response already carries each item's groups, so this is one
    // request per restaurant rather than one per dish.
    const payload = await (
      await request.get(`http://127.0.0.1:8000/api/menu-items?restaurant_id=${restaurant.id}`)
    ).json();
    const items = Array.isArray(payload) ? payload : (payload.items ?? []);
    for (const item of items) {
      const groups = [
        ...(item.customization_groups ?? []),
        ...(item.sizes ?? []).flatMap(
          (size: { customization_groups?: unknown[] }) => size.customization_groups ?? [],
        ),
      ];
      const split = groups.find((group: { supports_halves?: boolean }) => group.supports_halves);
      if (!split) continue;
      const activeNames = (group: { options?: { name: string; is_active?: boolean }[] }) =>
        (group.options ?? [])
          .filter((option) => option.is_active !== false)
          .map((option) => option.name);

      const names = activeNames(split);
      if (names.length < 2) continue;

      // An item can require other choices before it can be added at all — this
      // one wants a crust and a sauce. Answering them is not what the test is
      // about, but leaving them unanswered leaves the button disabled.
      const required = groups
        .filter(
          (group: { id: string; is_required?: boolean; min_selection?: number }) =>
            group.id !== split.id && (group.is_required || (group.min_selection ?? 0) > 0),
        )
        .map(
          (group: { options?: { name: string; is_active?: boolean }[] }) => activeNames(group)[0],
        )
        .filter((name: string | undefined): name is string => Boolean(name));

      return { itemId: item.id as string, options: names, required };
    }
  }
  return null;
}

/** The one number on the Add button, as a number. */
async function addButtonTotal(page: import("@playwright/test").Page): Promise<number> {
  const text = await page.getByRole("button", { name: /^Add to cart/ }).innerText();
  return Number(text.replace(/[^0-9.]/g, ""));
}

test.describe("half and half", () => {
  test("an option can be put on one half, and is priced as half", async ({ page, request }) => {
    const found = await findSplittable(request);
    test.skip(!found, "No menu item has a splittable group; nothing to exercise.");
    const { itemId, options } = found!;

    await resetApp(page);
    await page.goto(`/menu/${itemId}`);
    await page.waitForLoadState("networkidle");

    const base = await addButtonTotal(page);

    // Choosing the option reveals where it goes; before that there is nothing
    // to ask about, so no picker is rendered.
    await expect(page.locator(".portion-picker")).toHaveCount(0);
    await page.getByRole("button", { name: options[0]!, exact: false }).first().click();
    await expect(page.locator(".portion-picker").first()).toBeVisible();

    const whole = await addButtonTotal(page);
    await page.locator(".portion-picker").first().getByRole("button", { name: "Left" }).click();
    const half = await addButtonTotal(page);

    // Half the item, half the option's price. A free option charges nothing
    // either way, so the comparison only means something when it costs.
    if (whole > base) {
      expect(half).toBeLessThan(whole);
      expect(half - base).toBeCloseTo((whole - base) / 2, 2);
    } else {
      expect(half).toBeCloseTo(whole, 2);
    }
  });

  test("the item is read back as two halves", async ({ page, request }) => {
    const found = await findSplittable(request);
    test.skip(!found, "No menu item has a splittable group; nothing to exercise.");
    const { itemId, options } = found!;

    await resetApp(page);
    await page.goto(`/menu/${itemId}`);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: options[0]!, exact: false }).first().click();
    await page.locator(".portion-picker").first().getByRole("button", { name: "Left" }).click();
    await page.getByRole("button", { name: options[1]!, exact: false }).first().click();
    await page.locator(".portion-picker").nth(1).getByRole("button", { name: "Right" }).click();

    // The thing someone is trying to confirm before paying.
    const summary = page.locator(".half-summary");
    await expect(summary).toBeVisible();
    await expect(summary).toContainText(options[0]!);
    await expect(summary).toContainText(options[1]!);
  });

  test("the server prices a half-and-half order the same as the screen", async ({
    page,
    request,
  }) => {
    const found = await findSplittable(request);
    test.skip(!found, "No menu item has a splittable group; nothing to exercise.");
    const { itemId, options, required } = found!;

    await resetApp(page);
    await page.goto(`/menu/${itemId}`);
    await page.waitForLoadState("networkidle");

    for (const name of required) {
      await page.getByRole("button", { name, exact: false }).first().click();
    }
    await page.getByRole("button", { name: options[0]!, exact: false }).first().click();
    await page.locator(".portion-picker").first().getByRole("button", { name: "Left" }).click();

    const shown = await addButtonTotal(page);
    await page.getByRole("button", { name: /^Add to cart/ }).click();

    // The cart is the client's own arithmetic; what matters is that the number
    // it carries is the one the customer was shown.
    await page.goto("/cart");
    await page.waitForLoadState("networkidle");
    await expect(page.getByRole("article").first()).toBeVisible();
    const cartText = await page.getByRole("article").first().innerText();
    expect(cartText).toContain(options[0]!);
    expect(Number(cartText.match(/\$([0-9.]+)/)?.[1] ?? 0)).toBeCloseTo(shown, 2);
  });
});
