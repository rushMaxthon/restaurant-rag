import { expect, test } from "@playwright/test";
import { fillCart, resetApp, signIn } from "./helpers";

/**
 * What the account already knows, filled in for the customer.
 *
 * Checkout asked a signed-in customer for their name, their number and their
 * address on every order — all of which the account already held, and one of
 * which (the address) is the slowest thing on the page to type on a phone.
 *
 * Nothing here asserts a particular name or address: the values come from
 * whatever account the suite signs in as, so the test asks the API what that
 * account holds and expects the form to agree.
 */

type Account = {
  full_name: string;
  phone_number: string | null;
  default_address: string | null;
};

async function accountDetails(request: import("@playwright/test").APIRequestContext) {
  const auth = await request.post("http://127.0.0.1:8000/api/auth/login", {
    data: { email: "customer1@example.com", password: "password123" },
  });
  const { access_token } = await auth.json();
  const profile = await request.get("http://127.0.0.1:8000/api/profile/me", {
    headers: { Authorization: `Bearer ${access_token}` },
  });
  const body = await profile.json();
  const saved = (body.saved_addresses ?? []) as {
    formatted_address: string;
    phone_number: string | null;
    is_default: boolean;
  }[];
  return {
    user: body.user as Account,
    saved,
    /**
     * The number checkout should show.
     *
     * An address's own number wins over the account's: it is the one attached
     * to the door the rider is going to, and someone who saved a doorman's
     * number against an address meant it for that address. Derived from what
     * the account actually holds, because the suite places real orders and so
     * changes what it holds.
     */
    expectedPhone:
      (saved.find((a) => a.is_default) ?? saved[0])?.phone_number ?? body.user.phone_number,
  };
}

test.describe("checkout knows who is ordering", () => {
  test("the name and number are filled in from what we already hold", async ({ page, request }) => {
    const { user, expectedPhone } = await accountDetails(request);

    await resetApp(page);
    await fillCart(page, 1);
    await signIn(page, "/checkout");
    await expect(page).toHaveURL(/\/checkout/);

    await expect(page.getByLabel("Full name")).toHaveValue(user.full_name);

    // Stored as bare digits, shown grouped — the assertion is that the same
    // number is there, not that it looks the way it was stored.
    const digits = (value: string) => value.replace(/\D/g, "");
    if (expectedPhone) {
      await expect
        .poll(async () => digits(await page.getByLabel("Phone number").inputValue()))
        .toContain(digits(expectedPhone).slice(-10));
    }

    // And it says so, rather than filling itself in silently.
    await expect(page.getByText(/filled in from your account/i)).toBeVisible();
  });

  test("everything filled in can still be changed", async ({ page }) => {
    await resetApp(page);
    await fillCart(page, 1);
    await signIn(page, "/checkout");

    const name = page.getByLabel("Full name");
    await expect(name).not.toHaveValue("");

    // The prefill is a starting point, not a lock: someone ordering for a
    // friend types over it, and it has to stay typed over.
    await name.fill("Someone Else Entirely");
    await page.getByLabel("Phone number").click();
    await expect(name).toHaveValue("Someone Else Entirely");

    // A late profile response must not reach in and undo that.
    await page.waitForTimeout(1500);
    await expect(name).toHaveValue("Someone Else Entirely");
  });

  test("an address on file is offered rather than retyped", async ({ page, request }) => {
    const { user, saved } = await accountDetails(request);
    test.skip(
      !user.default_address && saved.length === 0,
      "This account has no address on file; there is nothing to fill in.",
    );

    await resetApp(page);
    await fillCart(page, 1);
    await signIn(page, "/checkout");

    // Delivery is the default fulfillment, so the address fields are showing.
    const line1 = page.getByLabel("Address line 1", { exact: true });
    await expect(line1).not.toHaveValue("");

    // Whatever we put there, the customer can replace.
    await line1.fill("742 Evergreen Terrace");
    await expect(line1).toHaveValue("742 Evergreen Terrace");
  });
});
