import { expect, test, type APIRequestContext } from "@playwright/test";
import { resetApp } from "./helpers";

const API = "http://127.0.0.1:8000/api";
const ITEM = "07e52a7c-2d32-4414-87cf-f62c0bf9c6ff";

/** The Toppings cap as it stands, so the test can put it back exactly. */
async function readToppingsMax(request: APIRequestContext): Promise<number> {
  const item = await (await request.get(`${API}/menu-items/${ITEM}`)).json();
  const groups = item.sizes.flatMap(
    (z: { customization_groups?: { title: string; max_selection: number }[] }) =>
      z.customization_groups ?? [],
  );
  return groups.find((g: { title: string }) => g.title === "Toppings")?.max_selection ?? 0;
}

/** Set the Toppings cap through the admin API, the way the dashboard does. */
async function setToppingsMax(request: APIRequestContext, max: number) {
  const auth = await request.post(`${API}/auth/login`, {
    data: { email: "admin@example.com", password: "password123" },
  });
  const { access_token } = await auth.json();
  const item = await (await request.get(`${API}/menu-items/${ITEM}`)).json();
  const group = (g: Record<string, never>) => ({
    title: g.title,
    selection_type: g.selection_type,
    is_required: g.is_required,
    min_selection: g.min_selection,
    max_selection: g.title === "Toppings" ? max : g.max_selection,
    supports_halves: g.supports_halves,
    is_active: g.is_active,
    sort_order: g.sort_order,
    options: (g.options as Record<string, never>[]).map((o) => ({
      name: o.name,
      extra_price: Number(o.extra_price),
      is_active: o.is_active,
      is_countable: o.is_countable,
      sort_order: o.sort_order,
    })),
  });
  const res = await request.put(`${API}/menu-items/${ITEM}`, {
    headers: { Authorization: `Bearer ${access_token}` },
    data: {
      name: item.name,
      category: item.category,
      cuisine_type: item.cuisine_type,
      description: item.description,
      price: Number(item.price),
      is_veg: item.is_veg,
      is_available: item.is_available,
      image_url: item.image_url,
      is_new_launch: item.is_new_launch,
      has_sizes: item.has_sizes,
      has_customizations: item.has_customizations,
      customization_groups: [],
      restaurant_location_id: item.restaurant_location_id,
      sizes: item.sizes.map((z: Record<string, never>) => ({
        name: z.name,
        price: Number(z.price),
        is_active: z.is_active,
        sort_order: z.sort_order,
        customization_groups: (z.customization_groups as Record<string, never>[]).map(group),
      })),
    },
  });
  expect(res.status()).toBe(200);
}

/**
 * The owner's number, on the customer's screen, without a deploy.
 *
 * Moves the cap to something other than what it is now through the same
 * endpoint the dashboard uses, counts what the web menu then allows on each
 * half, and puts back whatever was there — restoring a hardcoded number would
 * quietly rewrite the menu if someone had changed it.
 */
test("the owner's cap reaches the web menu, per half", async ({ page, request }) => {
  const before = await readToppingsMax(request);
  // Somewhere other than where it is, so the check is about the change.
  const target = before === 1 ? 2 : 1;
  await setToppingsMax(request, target);
  try {
    await resetApp(page);
    await page.goto(`/menu/${ITEM}`);
    await page.waitForLoadState("networkidle");

    const card = page.locator(".choice-card", { hasText: "Toppings" }).first();
    await card.locator(".split-switch__option", { hasText: /half & half/i }).click();

    const names = await card.locator(".option-row > span:first-child").allInnerTexts();
    // Tick until the app refuses, and count what it took.
    let taken = 0;
    for (const name of names) {
      const row = card.getByRole("button", { name, exact: false }).first();
      if (await row.isDisabled()) break;
      await row.click();
      taken += 1;
    }

    // Both halves, each up to the owner's number.
    expect(taken).toBe(target * 2);
    await expect(card.locator(".choice-card__hint")).toContainText(
      `${target} left, ${target} right`,
    );
  } finally {
    await setToppingsMax(request, before);
  }
});
