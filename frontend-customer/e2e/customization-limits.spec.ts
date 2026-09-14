import { expect, test, type APIRequestContext } from "@playwright/test";
import { resetApp } from "./helpers";

/**
 * The limits an owner sets, as the customer meets them.
 *
 * A group carries a selection type and a minimum and a maximum. The customer
 * used to be told about one of them, in two places that disagreed — a badge
 * saying "Choose 2" above a line saying "Choose up to 4" — and the ceiling was
 * checked only at the Add button, so a seventh topping went on and the refusal
 * arrived at the end.
 *
 * Discovered from the API, not hardcoded: which group is capped is admin data.
 */

type Capped = { itemId: string; title: string; max: number; options: string[] };

async function findCappedGroup(request: APIRequestContext): Promise<Capped | null> {
  const restaurants = await (await request.get("http://127.0.0.1:8000/api/restaurants")).json();
  const rows = Array.isArray(restaurants) ? restaurants : (restaurants.items ?? []);
  for (const restaurant of rows) {
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
      for (const group of groups as Record<string, never>[]) {
        const max = Number(group.max_selection);
        const names = ((group.options ?? []) as { name: string; is_active?: boolean }[])
          .filter((option) => option.is_active !== false)
          .map((option) => option.name);
        // A cap only means something when there are more options than the cap.
        if (group.selection_type === "MULTI" && max > 0 && names.length > max) {
          return { itemId: item.id as string, title: group.title as string, max, options: names };
        }
      }
    }
  }
  return null;
}

test.describe("the limits an owner set", () => {
  test("the group says how many, and counts what is chosen", async ({ page, request }) => {
    const found = await findCappedGroup(request);
    test.skip(!found, "No group has a maximum with more options than the maximum.");
    const { itemId, title, max, options } = found!;

    await resetApp(page);
    await page.goto(`/menu/${itemId}`);
    await page.waitForLoadState("networkidle");

    const card = page.locator(".choice-card", { hasText: title }).first();
    // Both numbers, in one sentence, before anything is chosen.
    await expect(card.locator(".choice-card__hint")).toContainText(new RegExp(`${max}`));

    await card.getByRole("button", { name: options[0]!, exact: false }).first().click();
    await expect(card.locator(".choice-card__hint")).toContainText("1 chosen");
  });

  test("the ceiling is enforced where the choosing happens", async ({ page, request }) => {
    const found = await findCappedGroup(request);
    test.skip(!found, "No group has a maximum with more options than the maximum.");
    const { itemId, title, max, options } = found!;

    await resetApp(page);
    await page.goto(`/menu/${itemId}`);
    await page.waitForLoadState("networkidle");

    const card = page.locator(".choice-card", { hasText: title }).first();
    for (const name of options.slice(0, max)) {
      await card.getByRole("button", { name, exact: false }).first().click();
    }

    // One more than allowed: the option is visible, so the customer can see
    // what they are choosing between, but it will not go on.
    const beyond = card.getByRole("button", { name: options[max]!, exact: false }).first();
    await expect(beyond).toBeVisible();
    await expect(beyond).toBeDisabled();

    // Taking one off puts the rest back within reach.
    await card.getByRole("button", { name: options[0]!, exact: false }).first().click();
    await expect(beyond).toBeEnabled();
  });
});
