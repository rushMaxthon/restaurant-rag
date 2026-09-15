import { expect, test, type APIRequestContext } from "@playwright/test";
import { clickFixed, fillCheckoutContact, resetApp, signIn } from "./helpers";

/**
 * A half-and-half pizza, from the dish page to what the server stored.
 *
 * The pieces were all tested separately and the join between them was not:
 * checkout built its order payload without the portion, so every split pizza
 * reached the kitchen as a whole one and was priced as two whole toppings
 * against a screen that had charged for two halves. Nothing short of following
 * one order all the way through would have caught it.
 */

const API = "http://127.0.0.1:8000/api";

type Splittable = { itemId: string; options: string[]; required: string[] };

async function findSplittable(request: APIRequestContext): Promise<Splittable | null> {
  const restaurants = await (await request.get(`${API}/restaurants`)).json();
  const rows = Array.isArray(restaurants) ? restaurants : (restaurants.items ?? []);
  for (const restaurant of rows) {
    const payload = await (
      await request.get(`${API}/menu-items?restaurant_id=${restaurant.id}`)
    ).json();
    const items = Array.isArray(payload) ? payload : (payload.items ?? []);
    for (const item of items) {
      const groups = [
        ...(item.customization_groups ?? []),
        ...(item.sizes ?? []).flatMap(
          (size: { customization_groups?: unknown[] }) => size.customization_groups ?? [],
        ),
      ];
      const split = groups.find((g: { supports_halves?: boolean }) => g.supports_halves);
      if (!split) continue;
      const names = (g: { options?: { name: string; is_active?: boolean }[] }) =>
        (g.options ?? []).filter((o) => o.is_active !== false).map((o) => o.name);
      if (names(split).length < 2) continue;
      const required = groups
        .filter(
          (g: { id: string; is_required?: boolean; min_selection?: number }) =>
            g.id !== split.id && (g.is_required || (g.min_selection ?? 0) > 0),
        )
        .map((g: { options?: { name: string; is_active?: boolean }[] }) => names(g)[0])
        .filter((n: string | undefined): n is string => Boolean(n));
      return { itemId: item.id as string, options: names(split), required };
    }
  }
  return null;
}

test("a split pizza reaches the server as a split pizza", async ({ page, request }) => {
  const found = await findSplittable(request);
  test.skip(!found, "No menu item has a splittable group; nothing to exercise.");
  const { itemId, options, required } = found!;

  await resetApp(page);
  await page.goto(`/menu/${itemId}`);
  await page.waitForLoadState("networkidle");
  for (const name of required) {
    await page.getByRole("button", { name, exact: false }).first().click();
  }

  const card = page
    .locator(".choice-card")
    .filter({ has: page.locator(".split-switch") })
    .first();
  await card.locator(".split-switch__option", { hasText: /half & half/i }).click();
  await card.getByRole("button", { name: options[0]!, exact: false }).first().click();
  await card.getByRole("button", { name: options[1]!, exact: false }).first().click();

  // What the dish page says this costs.
  const addText = await page.getByRole("button", { name: /^Add to cart/ }).innerText();
  const shown = Number(addText.replace(/[^0-9.]/g, ""));
  await page.getByRole("button", { name: /^Add to cart/ }).click();

  // The cart says which half each topping is on, rather than listing names
  // that read the same as a whole pizza.
  await page.goto("/cart");
  await page.waitForLoadState("networkidle");
  const cartText = await page.getByRole("article").first().innerText();
  expect(cartText).toMatch(/left half/i);
  expect(cartText).toMatch(/right half/i);

  // And so does the checkout summary, on the last screen before paying.
  await signIn(page, "/checkout");
  await expect(page).toHaveURL(/\/checkout/);
  await fillCheckoutContact(page);
  await expect(page.getByText(/left half/i).first()).toBeVisible();

  // Outside opening hours the branch cannot take an ASAP order and the Pay
  // button waits for a slot ("Pick a time to continue"), so this runs or does
  // not depending on the clock.
  const later = page.getByRole("button", { name: /schedule for later/i });
  if (await later.count()) await later.click();
  const times = page.locator(".slot-grid .slot-chip");
  if (await times.count()) {
    await times.first().waitFor({ state: "visible", timeout: 20_000 });
    await times.first().click();
  }

  // Place it. The order is PAYMENT_PENDING at this point, which is enough:
  // what is being checked is what the server was told, not that money moved.
  // Below lg the pay button lives in a fixed bottom bar; clickFixed explains
  // why a plain click is not enough there.
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await clickFixed(page, page.getByRole("button", { name: /^Pay (\$|now)/ }).first());
  await expect(page.getByRole("heading", { name: /pay for your order/i })).toBeVisible({
    timeout: 60_000,
  });

  // The stored order: the halves survived, and the server's own total agrees
  // with the number the customer was shown.
  const auth = await request.post(`${API}/auth/login`, {
    data: { email: "customer1@example.com", password: "password123" },
  });
  const { access_token } = await auth.json();
  const orders = await (
    await request.get(`${API}/orders`, { headers: { Authorization: `Bearer ${access_token}` } })
  ).json();
  const latest = (Array.isArray(orders) ? orders : (orders.items ?? []))[0];
  expect(latest).toBeTruthy();

  const line = latest.items.find((i: { menu_item_id: string }) => i.menu_item_id === itemId);
  expect(line, "the split pizza is on the order").toBeTruthy();
  // `selected_options_snapshot`, not `selected_options`: what an order stores
  // is a frozen copy of the choice, so it still reads correctly after the menu
  // has moved on.
  const chosen = (line.selected_options_snapshot ?? []) as {
    option_name: string;
    portion?: string;
  }[];
  const portions = chosen.map((o) => o.portion ?? "WHOLE");
  expect(portions).toContain("LEFT");
  expect(portions).toContain("RIGHT");

  // Priced as halves by the server, not as whole toppings.
  expect(Number(line.unit_price)).toBeCloseTo(shown, 2);
});
