import { expect, test, type APIRequestContext } from "@playwright/test";
import { resetApp, signIn } from "./helpers";

/**
 * Saving a dish, and what saving it is FOR.
 *
 * A favourite in a food app is not a wishlist entry — it is "my usual" — so
 * the thing worth testing is not that a heart fills in, but that the dish
 * turns up where someone hungry will meet it, with a way to order it.
 */

const API = "http://127.0.0.1:8000/api";

async function token(request: APIRequestContext): Promise<string> {
  const auth = await request.post(`${API}/auth/login`, {
    data: { email: "customer1@example.com", password: "password123" },
  });
  return (await auth.json()).access_token;
}

/** Start from nothing saved, so the strip's absence means something. */
async function clearFavourites(request: APIRequestContext) {
  const bearer = await token(request);
  const headers = { Authorization: `Bearer ${bearer}` };
  const ids = await (await request.get(`${API}/favorites/ids`, { headers })).json();
  for (const id of ids as string[]) {
    await request.delete(`${API}/favorites/${id}`, { headers });
  }
}

test.describe("saving a dish", () => {
  test("a saved dish appears in what you always order", async ({ page, request }) => {
    await clearFavourites(request);

    await resetApp(page);
    await signIn(page, "/menu");
    await page.waitForLoadState("networkidle");

    // Nothing saved: the strip is not there at all, rather than a heading over
    // an empty rail.
    await expect(page.locator(".usual")).toHaveCount(0);

    const heart = page.locator(".heart").first();
    await expect(heart).toHaveAttribute("data-on", "false");
    await heart.click();
    // Optimistic: it fills in on the tap, not after the round trip.
    await expect(heart).toHaveAttribute("data-on", "true");

    // And the server agrees, which the screen alone cannot tell us.
    const bearer = await token(request);
    await expect
      .poll(
        async () =>
          (
            await (
              await request.get(`${API}/favorites/ids`, {
                headers: { Authorization: `Bearer ${bearer}` },
              })
            ).json()
          ).length,
        { timeout: 15_000 },
      )
      .toBe(1);

    await page.reload();
    await page.waitForLoadState("networkidle");
    await expect(page.getByRole("heading", { name: /what you always order/i })).toBeVisible();
    await expect(page.locator(".usual")).toHaveCount(1);
  });

  test("unsaving it takes it back out again", async ({ page, request }) => {
    await clearFavourites(request);
    await resetApp(page);
    await signIn(page, "/menu");
    await page.waitForLoadState("networkidle");

    const heart = page.locator(".heart").first();
    await heart.click();
    await expect(heart).toHaveAttribute("data-on", "true");
    await heart.click();
    await expect(heart).toHaveAttribute("data-on", "false");

    const bearer = await token(request);
    await expect
      .poll(
        async () =>
          (
            await (
              await request.get(`${API}/favorites/ids`, {
                headers: { Authorization: `Bearer ${bearer}` },
              })
            ).json()
          ).length,
        { timeout: 15_000 },
      )
      .toBe(0);
  });

  test("a guest is not offered somewhere to save it to", async ({ page }) => {
    // Signed out there is no account to hold favourites, so the control is
    // absent rather than present and failing.
    await resetApp(page);
    await page.goto("/menu");
    await page.waitForLoadState("networkidle");
    await expect(page.locator(".dish-card").first()).toBeVisible();
    await expect(page.locator(".heart")).toHaveCount(0);
  });
});

test.describe("what people order together", () => {
  test("every pairing shown can actually be ordered here", async ({ page }) => {
    await resetApp(page);
    await page.goto("/menu");
    await page.waitForLoadState("networkidle");

    const pairs = page.locator(".pair");
    const count = await pairs.count();
    test.skip(count === 0, "This branch has no generated pairings yet.");

    // The bug this guards: the unscoped endpoint answers for the whole
    // marketplace, so a burger and a milkshake from another restaurant were
    // offered on this menu — dishes that cannot go in this cart at all.
    const names = await page.locator(".menu-grid .dish-title").allInnerTexts();
    const onThisMenu = new Set(names.map((name) => name.trim().toLowerCase()));

    for (let i = 0; i < count; i += 1) {
      const dishes = (await pairs.nth(i).locator(".pair__what").innerText()).split(" + ");
      for (const dish of dishes) {
        expect(
          onThisMenu.has(dish.trim().toLowerCase()),
          `"${dish.trim()}" is paired here but is not on this menu`,
        ).toBe(true);
      }
    }

    // And each says who ordered it, which is the point of these over a bundle.
    await expect(pairs.first().locator(".pair__who")).toContainText(/ordered these together/i);
  });
});

test.describe("the list of what you saved", () => {
  test("a dish saved on the menu is on the account, and survives a new browser", async ({
    page,
    request,
    browser,
  }) => {
    await clearFavourites(request);
    await resetApp(page);
    await signIn(page, "/menu");
    await page.waitForLoadState("networkidle");

    const name = (await page.locator(".dish-card .dish-title").first().innerText()).trim();
    await page.locator(".heart").first().click();
    await expect(page.locator(".heart").first()).toHaveAttribute("data-on", "true");

    await page.goto("/profile");
    await page.waitForLoadState("networkidle");
    await expect(
      page.getByRole("heading", { name: /what you keep coming back to/i }),
    ).toBeVisible();
    await expect(page.locator(".line--saved")).toHaveCount(1);
    await expect(page.locator(".line--saved")).toContainText(name);

    // The real test of "saved in the backend": a browser that has never seen
    // this app before, with its own storage, signing in fresh. Anything held
    // only on the client is gone here.
    const fresh = await browser.newContext();
    const other = await fresh.newPage();
    await resetApp(other);
    await signIn(other, "/profile");
    await other.waitForLoadState("networkidle");
    await expect(other.locator(".line--saved")).toContainText(name);
    await fresh.close();
  });

  test("removing it from the account takes it off the server too", async ({ page, request }) => {
    await clearFavourites(request);
    await resetApp(page);
    await signIn(page, "/menu");
    await page.waitForLoadState("networkidle");
    await page.locator(".heart").first().click();
    await expect(page.locator(".heart").first()).toHaveAttribute("data-on", "true");

    await page.goto("/profile");
    await page.waitForLoadState("networkidle");
    await page.locator(".line--saved .rail__danger").first().click();
    await expect(page.locator(".line--saved")).toHaveCount(0);

    const bearer = await token(request);
    await expect
      .poll(
        async () =>
          (
            await (
              await request.get(`${API}/favorites/ids`, {
                headers: { Authorization: `Bearer ${bearer}` },
              })
            ).json()
          ).length,
        { timeout: 15_000 },
      )
      .toBe(0);
  });

  test("with nothing saved it says how to save something", async ({ page, request }) => {
    await clearFavourites(request);
    await resetApp(page);
    await signIn(page, "/profile");
    await page.waitForLoadState("networkidle");
    // An empty screen is an invitation, not a blank.
    await expect(page.getByText(/tap the heart on a dish/i)).toBeVisible();
  });
});
