import { expect, test } from "@playwright/test";
import {
  API_BASE,
  TENANT_HEADER,
  customerAuth,
  fillCart,
  resetApp,
  signIn,
} from "./helpers";

/**
 * A saved address is one address, and it can be ordered to.
 *
 * Both halves of one screenshot taken on 2026-10-03, at `/checkout`, with a
 * saved address card plainly selected on screen:
 *
 *   1. the page said "Please choose your address from the suggestions so we
 *      can work out the delivery charge" — about an address the customer had
 *      chosen, had not typed, and could see nothing wrong with
 *   2. the picker showed "12 Velanja - Gothan Road, Surat, Gujarat, 394150"
 *      twice
 *
 * The first was a coordinate that never left the browser: the checkout filled
 * its form from the saved address and left `pickedPoint` null, so the order
 * carried no point and the server refused it. The order request also had no
 * way to NAME the saved address, even though the delivery quote has taken one
 * since the autocomplete was built — so the quote priced that address from its
 * stored rooftop while the order refused the very same address for having no
 * coordinates.
 *
 * The second was a cached list. The checkout does compare the typed address
 * against the picker's contents before saving, but that list is a cached
 * query: the first order writes the row, the cache does not know yet, and the
 * second order the same evening writes it again. Any client can lose that
 * race, so the rule moved to the server.
 *
 * These go over the wire rather than through the form, because what is being
 * checked is what the two sides agree on — and because the duplicate needed
 * TWO saves with no refetch between them, which is exactly what a form cannot
 * easily be made to do.
 */

type Saved = {
  id: string;
  address_line_1: string;
  city: string;
  state: string;
  postal_code: string;
  latitude: number | null;
  longitude: number | null;
};

const ADDRESS = {
  label: "OTHER",
  address_line_1: "12 Velanja - Gothan Road",
  city: "Surat",
  state: "Gujarat",
  postal_code: "394150",
};

async function savedAddresses(
  request: import("@playwright/test").APIRequestContext,
): Promise<Saved[]> {
  const headers = await customerAuth(request);
  const response = await request.get(`${API_BASE}/profile/me`, { headers });
  expect(response.ok(), "the profile reads back").toBeTruthy();
  return ((await response.json()).saved_addresses ?? []) as Saved[];
}

/**
 * Remove every copy of the test address before measuring.
 *
 * Not tidiness. A leftover row from an earlier run — or from the run that
 * proved these tests catch the bug — is indistinguishable from the duplicate
 * being tested, so the count assertion would report whichever happened last
 * rather than what this code does.
 */
async function clearTestAddress(
  request: import("@playwright/test").APIRequestContext,
): Promise<void> {
  const headers = await customerAuth(request);
  for (const entry of await savedAddresses(request)) {
    if (entry.postal_code === ADDRESS.postal_code) {
      await request.delete(`${API_BASE}/profile/addresses/${entry.id}`, { headers });
    }
  }
}

/**
 * The first orderable dish on THIS storefront, whichever tenant it is.
 *
 * Read through `/app-config` with the tenant header rather than by walking
 * `/restaurants`: a customer token is bound to the app client the host
 * resolves to, so a dish from another restaurant is refused with "This app
 * cannot access data for another restaurant" — a 403 that arrives before any
 * address rule is reached, and which made the first version of this test
 * green against the bug it exists for.
 */
async function anyDish(
  request: import("@playwright/test").APIRequestContext,
): Promise<{ id: string; restaurant_id: string; restaurant_location_id: string }> {
  const config = await (
    await request.get(`${API_BASE}/app-config`, { headers: TENANT_HEADER })
  ).json();
  const restaurantId = config.restaurant?.id ?? config.restaurant_id;
  expect(restaurantId, "this storefront resolves to a restaurant").toBeTruthy();

  const payload = await (
    await request.get(`${API_BASE}/menu-items?restaurant_id=${restaurantId}`, {
      headers: TENANT_HEADER,
    })
  ).json();
  const items = Array.isArray(payload) ? payload : (payload.items ?? []);
  const dish = items.find(
    (item: { is_available?: boolean; restaurant_location_id?: string }) =>
      item.is_available !== false && item.restaurant_location_id,
  );
  expect(dish, "the storefront's own menu has something to order").toBeTruthy();
  return dish;
}

test.describe("a saved address", () => {
  test("is saved once, however many times it is sent", async ({ request }) => {
    const headers = await customerAuth(request);
    await clearTestAddress(request);

    const first = await request.post(`${API_BASE}/profile/addresses`, {
      headers,
      data: ADDRESS,
    });
    expect(first.ok(), await first.text()).toBeTruthy();
    const created = (await first.json()) as Saved;

    // Sent again with no refetch in between — the race the client cannot win.
    // Spacing and case differ, because a customer re-picking the same Google
    // suggestion gets subtly different whitespace each time and that is how
    // the first duplicate got through.
    const second = await request.post(`${API_BASE}/profile/addresses`, {
      headers,
      data: {
        ...ADDRESS,
        address_line_1: "  12   Velanja  -  Gothan  Road ",
        city: "surat",
        state: "gujarat",
      },
    });
    expect(second.ok(), await second.text()).toBeTruthy();

    // The address the second call got back is the one that already existed.
    expect((await second.json()).id).toBe(created.id);

    const list = await savedAddresses(request);
    const matches = list.filter((entry) => entry.postal_code === ADDRESS.postal_code);
    expect(matches.map((entry) => entry.id), "one row for one doorstep").toEqual([created.id]);

    await request.delete(`${API_BASE}/profile/addresses/${created.id}`, { headers });
  });

  test("can be ordered to without naming a coordinate", async ({ request }) => {
    // The server's half of the refusal. A client that sends the saved
    // address's id and no coordinates — which is every client written before
    // the autocomplete, and this one until today — must be able to place the
    // order, because the row already carries the point it was geocoded to.
    //
    // This posts to `/orders`, not `/orders/validate`: validation runs with
    // `require_payment_validation=False` and so never reaches the coordinate
    // check at all. A version of this test that asked validation was green
    // against the bug, which is worse than no test.
    const headers = await customerAuth(request);
    await clearTestAddress(request);
    const created = await request.post(`${API_BASE}/profile/addresses`, {
      headers,
      data: ADDRESS,
    });
    expect(created.ok(), await created.text()).toBeTruthy();
    const saved = (await created.json()) as Saved;

    // Only meaningful if the row actually got a point when it was saved. If
    // the geocoder is unconfigured on this machine there is nothing to fall
    // back TO, and asserting the order succeeds would be asserting the
    // geocoder's availability.
    test.skip(
      saved.latitude === null || saved.longitude === null,
      "the saved address was stored without coordinates, so there is no fallback to test",
    );

    const dish = await anyDish(request);

    // A method this branch actually takes. `_prepare_order_draft` checks the
    // payment method BEFORE it reaches the address, so an unsupported one
    // returns 503 and the coordinate rule is never exercised — which is how
    // the first two versions of this test were green against the bug.
    const config = await (
      await request.get(`${API_BASE}/payments/config`, { headers })
    ).json();
    const method = (config.supported_methods ?? [])[0];
    expect(method, "this branch takes some form of payment").toBeTruthy();

    const order = await request.post(`${API_BASE}/orders`, {
      headers,
      failOnStatusCode: false,
      data: {
        restaurant_id: dish.restaurant_id,
        restaurant_location_id: dish.restaurant_location_id,
        fulfillment_type: "DELIVERY",
        // Six of them, to clear whatever minimum the branch sets. A refusal
        // for being under the minimum is a different sentence and would not
        // hide the one being tested, but it makes the result harder to read.
        items: [{ menu_item_id: dish.id, quantity: 6 }],
        delivery_address: [
          ADDRESS.address_line_1,
          ADDRESS.city,
          ADDRESS.state,
          ADDRESS.postal_code,
        ].join(", "),
        contact_name: "Playwright Tester",
        contact_phone: "4155550132",
        // Deliberately absent: `latitude` and `longitude`. The id is the only
        // thing locating this order.
        saved_address_id: saved.id,
        payment_method: method,
      },
    });

    // The sentence the customer saw. Whatever else this order runs into — a
    // closed branch, a minimum, a payment method — it must not be refused for
    // carrying no coordinates, because it named an address that has some.
    expect(await order.text()).not.toContain("choose your address from the suggestions");

    await request.delete(`${API_BASE}/profile/addresses/${saved.id}`, { headers });
  });

  test("arrives on the checkout with its point, not just its text", async ({ page, request }) => {
    // The browser's half. The form is filled from the saved address on load,
    // so the coordinates must be on the request the page would send — without
    // the customer touching the address field at all.
    const headers = await customerAuth(request);
    await clearTestAddress(request);
    const created = await request.post(`${API_BASE}/profile/addresses`, {
      headers,
      data: { ...ADDRESS, is_default: true },
    });
    expect(created.ok(), await created.text()).toBeTruthy();
    const saved = (await created.json()) as Saved;
    test.skip(
      saved.latitude === null || saved.longitude === null,
      "the saved address was stored without coordinates",
    );

    await resetApp(page);
    await fillCart(page, 3);
    await signIn(page, "/checkout");

    // The delivery quote is the first thing the page asks for once the
    // address is in the form, and it carries the same coordinates the order
    // will. Watching it means not having to drive a payment to find out.
    const quote = await page.waitForRequest(
      (request) => request.url().includes("/orders/delivery-quote") && request.method() === "POST",
      { timeout: 30_000 },
    );
    const body = JSON.parse(quote.postData() ?? "{}");

    expect(body.latitude, "the prefilled address priced from its own rooftop").toBeCloseTo(
      saved.latitude!,
      4,
    );
    expect(body.longitude).toBeCloseTo(saved.longitude!, 4);

    // And the refusal is not on screen, because there is nothing to refuse.
    await expect(page.getByText(/choose your address from the suggestions/i)).toHaveCount(0);

    await request.delete(`${API_BASE}/profile/addresses/${saved.id}`, { headers });
  });
});
