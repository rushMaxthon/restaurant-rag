import { expect, test } from "@playwright/test";

import { API_BASE, TENANT_HEADER, resetApp } from "./helpers";

/**
 * Signing in with a phone number and a one-time code.
 *
 * The flow a customer ordering food in India expects, and the one that creates
 * the account on the way through — there is no separate sign-up, because "do
 * you have an account" is a question the number already answers.
 *
 * Every test here skips itself when the deployment cannot send a code.
 * `enable_phone_otp_login` is off by default and the fixed code is refused
 * outside a local environment, so a run against anything but a developer's
 * machine has nothing to exercise — and a suite that fails for that reason is
 * a suite people learn to ignore.
 */

/** A number nobody has used before, so each run exercises account creation. */
const freshNumber = () => `9${Math.floor(100_000_000 + Math.random() * 899_999_999)}`;

async function phoneLoginAvailable(request: import("@playwright/test").APIRequestContext) {
  const reply = await request.post(`${API_BASE}/auth/otp/request`, {
    headers: TENANT_HEADER,
    data: { phone_number: freshNumber() },
    failOnStatusCode: false,
  });
  return reply.ok() ? ((await reply.json()) as { debug_code: string | null }) : null;
}

test.describe("signing in with a phone number", () => {
  test("a new number creates an account and signs straight in", async ({ page }) => {
    const available = await phoneLoginAvailable(page.request);
    test.skip(!available, "This deployment cannot send a code.");
    const code = available!.debug_code;
    test.skip(!code, "No fixed code to type; a real SMS cannot be read from here.");

    await resetApp(page);
    await page.goto("/login");
    await page.waitForLoadState("networkidle");

    await page.getByLabel("Phone number").fill(freshNumber());
    await page.getByRole("button", { name: /send code/i }).click();

    // A number nobody has used is a sign-up, so the form asks for a name —
    // the only point in this flow where one can be collected.
    const name = page.getByLabel("Your name");
    await expect(name).toBeVisible({ timeout: 20_000 });
    await name.fill("Playwright Phone");
    await page.getByLabel("Your code").fill(code!);
    await page.getByRole("button", { name: /create my account/i }).click();

    await expect(page).not.toHaveURL(/\/login/, { timeout: 30_000 });
    // Signed in for real, not merely redirected: the account page is gated,
    // and it greets you by the name just given.
    await page.goto("/profile");
    await expect(page.getByRole("heading", { name: "Playwright Phone" })).toBeVisible({
      timeout: 20_000,
    });
  });

  test("the same number signs back into the same account", async ({ page }) => {
    const available = await phoneLoginAvailable(page.request);
    test.skip(!available, "This deployment cannot send a code.");
    const code = available!.debug_code;
    test.skip(!code, "No fixed code to type; a real SMS cannot be read from here.");

    const number = freshNumber();
    await resetApp(page);

    for (const pass of ["first", "second"] as const) {
      await page.goto("/login");
      await page.waitForLoadState("networkidle");
      await page.getByLabel("Phone number").fill(number);
      await page.getByRole("button", { name: /send code/i }).click();

      if (pass === "first") {
        await expect(page.getByLabel("Your name")).toBeVisible({ timeout: 20_000 });
        await page.getByLabel("Your name").fill("Returning Tester");
      } else {
        // The second time it is a sign-in, not a sign-up: no name is asked
        // for, which is also how the page says "we know you".
        await expect(page.getByLabel("Your code")).toBeVisible({ timeout: 20_000 });
        await expect(page.getByLabel("Your name")).toHaveCount(0);
      }

      await page.getByLabel("Your code").fill(code!);
      await page.getByRole("button", { name: /create my account|^sign in$/i }).click();
      await expect(page).not.toHaveURL(/\/login/, { timeout: 30_000 });

      // Signed out properly between passes. Clearing storage is not enough:
      // the provider holds the session in memory, so `/login` would redirect
      // straight back out and the next click would find nothing to press.
      if (pass === "first") await resetApp(page);
    }
  });

  test("a wrong code is refused, and says so", async ({ page }) => {
    const available = await phoneLoginAvailable(page.request);
    test.skip(!available, "This deployment cannot send a code.");

    await resetApp(page);
    await page.goto("/login");
    await page.waitForLoadState("networkidle");
    await page.getByLabel("Phone number").fill(freshNumber());
    await page.getByRole("button", { name: /send code/i }).click();

    await expect(page.getByLabel("Your code")).toBeVisible({ timeout: 20_000 });
    await page.getByLabel("Your code").fill("000000");
    await page.getByRole("button", { name: /create my account|^sign in$/i }).click();

    await expect(page.getByRole("alert")).toBeVisible({ timeout: 20_000 });
    await expect(page).toHaveURL(/\/login/);
  });

  test("there is no password anywhere, and no separate sign-up", async ({ page }) => {
    // A number is the whole identity. An email form sat behind a link for a
    // while and had to go: the phone form asked the server whether it could
    // send a code and quietly switched to email when the answer was no, so a
    // backend that was restarting left somebody looking at a password box
    // they had never seen and could not use.
    await resetApp(page);
    await page.goto("/login");
    await page.waitForLoadState("networkidle");

    await expect(page.getByLabel("Phone number")).toBeVisible();
    await expect(page.getByLabel("Password", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /sign in with email/i })).toHaveCount(0);
    await expect(page.getByRole("link", { name: /create an account/i })).toHaveCount(0);
  });

  test("an old link to the sign-up page lands on the form that replaced it", async ({ page }) => {
    // Kept as a redirect rather than deleted: links to it exist in bookmarks
    // and in messages sent before the change, and a 404 is a worse answer
    // than the form that replaced it. The redirect carries the destination
    // through, so somebody on their way to the checkout still gets there.
    await resetApp(page);
    await page.goto("/register?redirect=%2Fcheckout");
    await expect(page).toHaveURL(/\/login/);
    expect(new URL(page.url()).searchParams.get("redirect")).toBe("/checkout");
    await expect(page.getByLabel("Phone number")).toBeVisible();
  });
});
