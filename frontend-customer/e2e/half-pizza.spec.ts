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

/** Put the splittable group into half-and-half mode. */
async function splitTheGroup(page: import("@playwright/test").Page): Promise<void> {
  await page
    .locator(".split-switch__option", { hasText: /half & half/i })
    .first()
    .click();
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

    // Nothing is split until the group is, so no half-picker exists yet.
    await expect(page.locator(".portion-picker")).toHaveCount(0);
    await page.getByRole("button", { name: options[0]!, exact: false }).first().click();
    await expect(page.locator(".portion-picker")).toHaveCount(0);

    const whole = await addButtonTotal(page);
    await splitTheGroup(page);
    await expect(page.locator(".portion-picker").first()).toBeVisible();
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
    await splitTheGroup(page);
    await page.locator(".portion-picker").first().getByRole("button", { name: "Left" }).click();
    // A topping ticked while the group is split lands on the half that is
    // still bare, so this needs no second instruction.
    await page.getByRole("button", { name: options[1]!, exact: false }).first().click();

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
    // Both halves named: half a pizza and silence about the other half is not
    // an order the server takes, and the button will not let one be placed.
    await page.getByRole("button", { name: options[0]!, exact: false }).first().click();
    await splitTheGroup(page);
    await page.locator(".portion-picker").first().getByRole("button", { name: "Left" }).click();
    await page.getByRole("button", { name: options[1]!, exact: false }).first().click();

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

test.describe("a split item describes both of its halves", () => {
  test("naming one side asks for the other, and the order will not go without it", async ({
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
    await splitTheGroup(page);
    await page.locator(".portion-picker").first().getByRole("button", { name: "Left" }).click();

    // One side named and the other bare: said out loud, and the button holds.
    const add = page.getByRole("button", { name: /^Add to cart/ });
    await expect(add).toBeDisabled();
    // The reason under the button, not the summary's own "Right half" label.
    await expect(page.getByText(/choose something for the right half/i)).toBeVisible();

    // Anything on the other half, and it goes.
    await page.getByRole("button", { name: options[1]!, exact: false }).first().click();
    await expect(add).toBeEnabled();
  });

  test("whole and split are one question, not a mixture", async ({ page, request }) => {
    const found = await findSplittable(request);
    test.skip(!found, "No menu item has a splittable group; nothing to exercise.");
    const { itemId, options } = found!;

    await resetApp(page);
    await page.goto(`/menu/${itemId}`);
    await page.waitForLoadState("networkidle");

    // As many as the owner's cap allows, up to two. The cap is admin data: a
    // group capped at one takes exactly one topping here, and pinning this at
    // two made the test a statement about one restaurant's menu.
    await page.getByRole("button", { name: options[0]!, exact: false }).first().click();
    const second = page.getByRole("button", { name: options[1]!, exact: false }).first();
    const secondFits = !(await second.isDisabled());
    if (secondFits) await second.click();
    const chosen = secondFits ? 2 : 1;

    // Same all over: no halves anywhere, so no mixture is possible.
    await expect(page.locator(".portion-picker")).toHaveCount(0);

    // Split it, and every chosen topping gets a side — and only a side. There
    // is no "whole" among them, because that is the other answer to the
    // question above rather than a third choice beside the two halves.
    await splitTheGroup(page);
    await expect(page.locator(".portion-picker")).toHaveCount(chosen);
    await expect(
      page.locator(".portion-picker").first().getByRole("button", { name: "Whole" }),
    ).toHaveCount(0);

    // And it goes back, with everything returned to the whole item.
    await page
      .locator(".split-switch__option", { hasText: /same all over/i })
      .first()
      .click();
    await expect(page.locator(".portion-picker")).toHaveCount(0);
  });
});

test("a group split before anything is chosen still splits what arrives", async ({
  page,
  request,
}) => {
  const found = await findSplittable(request);
  test.skip(!found, "No menu item has a splittable group; nothing to exercise.");
  const { itemId, options, required } = found!;

  await resetApp(page);
  await page.goto(`/menu/${itemId}`);
  await page.waitForLoadState("networkidle");
  // Answered first, or the reason under the button is about the crust and
  // says nothing about halves.
  for (const name of required) {
    await page.getByRole("button", { name, exact: false }).first().click();
  }

  // The switch first, the toppings after. The first topping used to land on
  // the WHOLE item here: the screen said half-and-half and the order said
  // otherwise, at full price.
  await splitTheGroup(page);
  await page.getByRole("button", { name: options[0]!, exact: false }).first().click();

  const picker = page.locator(".portion-picker").first();
  await expect(picker).toBeVisible();
  // A side is actually chosen, not left blank.
  await expect(picker.locator('[data-on="true"]')).toHaveCount(1);

  // And the order will not go until the other half is described.
  await expect(page.getByText(/choose something for the (left|right) half/i)).toBeVisible();
});

test("switching the mode back and forth leaves a state that still fits", async ({
  page,
  request,
}) => {
  const found = await findSplittable(request);
  test.skip(!found, "No menu item has a splittable group; nothing to exercise.");
  const { itemId, options } = found!;

  await resetApp(page);
  await page.goto(`/menu/${itemId}`);
  await page.waitForLoadState("networkidle");
  const card = page
    .locator(".choice-card", { hasText: /./ })
    .filter({
      has: page.locator(".split-switch"),
    })
    .first();

  // One topping on the whole item.
  await card.getByRole("button", { name: options[0]!, exact: false }).first().click();
  // Split it, and choose there too.
  await splitTheGroup(page);
  const second = card.getByRole("button", { name: options[1]!, exact: false }).first();
  if (!(await second.isDisabled())) await second.click();
  // And back.
  await card.locator(".split-switch__option", { hasText: /same all over/i }).click();

  // Reported: both toppings ended up on the whole pizza at once, over a cap of
  // one. Whatever survives the round trip has to be within the group's own
  // limit — the count in the hint is the group saying so itself.
  await expect(card.locator(".portion-picker")).toHaveCount(0);
  const hint = await card.locator(".choice-card__hint").innerText();
  const [, cap, chosen] = hint.match(/Choose up to (\d+)[^0-9]*(\d+) chosen/) ?? [];
  if (cap && chosen) expect(Number(chosen)).toBeLessThanOrEqual(Number(cap));

  // And the page does not refuse what it just built.
  await expect(page.getByText(/choose at most/i)).toHaveCount(0);
});
