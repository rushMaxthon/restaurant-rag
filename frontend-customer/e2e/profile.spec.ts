import { expect, test, type APIRequestContext } from "@playwright/test";
import { resetApp, signIn } from "./helpers";

/**
 * The account screen: who you are, where we deliver, what you ordered.
 *
 * Everything shown comes from one `/profile/me` call, which has always
 * returned all of it — the web app simply never asked. Nothing here is
 * hardcoded about the account: the values come from the API, because a suite
 * that places orders changes what the account holds.
 */

const API = "http://127.0.0.1:8000/api";

async function account(request: APIRequestContext) {
  const auth = await request.post(`${API}/auth/login`, {
    data: { email: "customer1@example.com", password: "password123" },
  });
  const { access_token } = await auth.json();
  const profile = await request.get(`${API}/profile/me`, {
    headers: { Authorization: `Bearer ${access_token}` },
  });
  return profile.json();
}

test.describe("the account screen", () => {
  test("shows the details, the addresses and the recent orders", async ({ page, request }) => {
    const summary = await account(request);

    await resetApp(page);
    await signIn(page, "/profile");
    await page.waitForLoadState("networkidle");

    // The name IS the heading here.
    await expect(
      page.getByRole("heading", { name: summary.user.full_name, exact: false }),
    ).toBeVisible();
    await expect(page.getByText(summary.user.email, { exact: false }).first()).toBeVisible();

    // How they stand, said as a sentence rather than counted in tiles.
    await expect(page.getByText(/orders? so far|nothing on your tab/i)).toBeVisible();

    // Addresses: one line each, or an invitation to save one.
    const saved = summary.saved_addresses ?? [];
    if (saved.length) {
      await expect(page.locator(".place")).toHaveCount(saved.length);
    } else {
      await expect(page.getByText(/no address saved/i)).toBeVisible();
    }

    // Order lines: at most six, each linking to itself.
    const orders = summary.recent_orders ?? [];
    if (orders.length) {
      const rows = page.locator(".line");
      await expect(rows).toHaveCount(Math.min(orders.length, 6));
      await expect(rows.first()).toHaveAttribute("href", /\/orders\/[0-9a-f-]{36}/);
    }
  });

  test("the name can be changed and it sticks", async ({ page, request }) => {
    const summary = await account(request);
    const original = summary.user.full_name as string;
    const edited = `${original} (edited)`;

    await resetApp(page);
    await signIn(page, "/profile");
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: /change these/i }).click();
    await page.getByLabel("Name").fill(edited);
    await page.getByRole("button", { name: /save changes/i }).click();

    // Read back from the page, then from the server: the screen agreeing with
    // itself is not evidence that anything was saved.
    await expect(page.getByText(edited, { exact: false }).first()).toBeVisible();
    await expect
      .poll(async () => (await account(request)).user.full_name, { timeout: 15_000 })
      .toBe(edited);

    // Put it back, through the UI, which also covers editing twice in a row.
    await page.getByRole("button", { name: /change these/i }).click();
    await page.getByLabel("Name").fill(original);
    await page.getByRole("button", { name: /save changes/i }).click();
    await expect
      .poll(async () => (await account(request)).user.full_name, { timeout: 15_000 })
      .toBe(original);
  });

  test("it fits a phone without spilling sideways", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "mobile", "phone-sized screens only");

    await resetApp(page);
    await signIn(page, "/profile");
    await page.waitForLoadState("networkidle");

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, "the page scrolls sideways on a phone").toBeLessThanOrEqual(0);

    // Every tap target is thumb-sized. A 12px "Remove" link is a link nobody
    // can hit on a phone.
    for (const selector of [".rail__action", ".line"]) {
      const targets = page.locator(selector);
      for (let i = 0; i < (await targets.count()); i += 1) {
        const box = await targets.nth(i).boundingBox();
        if (box) expect(box.height).toBeGreaterThanOrEqual(28);
      }
    }
  });
});
