import { expect, test } from "@playwright/test";
import { ADDRESS_LINE_1, API_BASE, customerAuth, fillCart, resetApp, signIn } from "./helpers";

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

/**
 * Put an address on the account if it has not got one.
 *
 * `full_name` is REQUIRED by `UserProfileUpdateRequest`, so it is sent back
 * unchanged — this is a PATCH that behaves like a PUT, which is the same
 * reason the address goes missing in the first place.
 */
async function ensureAddressOnFile(request: import("@playwright/test").APIRequestContext) {
  const headers = await customerAuth(request);
  const body = await (await request.get(`${API_BASE}/profile/me`, { headers })).json();
  const user = body.user as Account;
  if (user.default_address || (body.saved_addresses ?? []).length > 0) return;

  const response = await request.patch(`${API_BASE}/profile/me`, {
    headers,
    data: {
      full_name: user.full_name,
      phone_number: user.phone_number,
      default_address: "1 Test Street, Surat, Gujarat 395004",
    },
  });
  if (!response.ok()) {
    throw new Error(
      `Could not put an address on the test account: ${response.status()} ` +
        `${await response.text()}`,
    );
  }
}

async function accountDetails(request: import("@playwright/test").APIRequestContext) {
  const profile = await request.get(`${API_BASE}/profile/me`, {
    headers: await customerAuth(request),
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
    // The precondition is ESTABLISHED, not hoped for. This used to
    // `test.skip()` when the account had no address — and the account reliably
    // had none by the time it ran, because the name-change test above sends
    // `PATCH /profile/me` with only a name and `default_address` defaults to
    // null on that schema, so a name edit blanks the address. The test
    // therefore skipped itself on most runs and reported green, which is
    // indistinguishable from passing in the summary line.
    await ensureAddressOnFile(request);

    await resetApp(page);
    await fillCart(page, 1);
    await signIn(page, "/checkout");

    // Delivery is the default fulfillment, so the address fields are showing.
    const line1 = page.getByLabel(ADDRESS_LINE_1);
    await expect(line1).not.toHaveValue("");

    // Whatever we put there, the customer can replace.
    await line1.fill("742 Evergreen Terrace");
    await expect(line1).toHaveValue("742 Evergreen Terrace");
  });
});
