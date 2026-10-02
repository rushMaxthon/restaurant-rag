import { expect, type APIRequestContext, type Locator, type Page } from "@playwright/test";

// The app's own rule, not a copy of it. The postal field is labelled from
// the tenant's currency — "PIN code" on an INR storefront, "ZIP code" on a
// USD one — so a test that hardcodes one of them is testing a different
// storefront than the one it is driving.
import { postalCodeLabel } from "../src/lib/delivery-address";

/**
 * Signing in, from a test, against a backend that serves many restaurants.
 *
 * Six specs each carried their own copy of this, with the address written into
 * it, and all six broke the day storefronts started resolving by host. That is
 * the reason it lives here now: an account identifier repeated in seven places
 * is an account identifier that will be wrong in seven places.
 *
 * **Two rules, and they are opposites.** A CUSTOMER belongs to one app client
 * — `docs/per-app-identity.md`, enforced by a partial unique index on
 * `(app_client_id, lower(email))` — and the backend picks that client from
 * `X-Forwarded-Host`. So a customer login without the header is refused: it is
 * looked up against the wrong tenant. STAFF have `app_client_id` NULL and
 * belong to no tenant, so a staff login WITH the header is refused for the
 * mirror-image reason — the header names a client the account is not in.
 * Verified both directions against the running backend; neither is guessable
 * from the error, which is "Invalid email or phone number or password" for all
 * four combinations.
 *
 * A browser cannot set that header on its own requests, which is why the
 * storefront's SSR layer sets it and why a test has to.
 */
export const API_BASE = process.env["E2E_API_BASE"] ?? "http://127.0.0.1:8000/api";

/** The address the storefront is served on — which is what selects a tenant. */
const STOREFRONT_HOST = process.env["E2E_HOST"] ?? "localhost";

/** On every customer-scoped call. Never on a staff one. */
export const TENANT_HEADER = { "X-Forwarded-Host": STOREFRONT_HOST };

export type Credentials = { email: string; password: string };

/** Platform staff, who belong to no tenant. */
export const ADMIN: Credentials = { email: "admin@example.com", password: "password123" };

let tenantConfig: { app_key?: string; currency?: { code?: string } } | null = null;

/** `/app-config` for the host under test, fetched once. */
async function config(request: APIRequestContext) {
  if (tenantConfig) return tenantConfig;
  const response = await request.get(`${API_BASE}/app-config`, { headers: TENANT_HEADER });
  if (!response.ok()) {
    throw new Error(
      `Could not resolve the tenant on "${STOREFRONT_HOST}": ${API_BASE}/app-config ` +
        `answered ${response.status()}. Is the backend running, and is there an ` +
        `app_client_domains row for this host? (seed.py: ensure_development_host)`,
    );
  }
  tenantConfig = await response.json();
  return tenantConfig!;
}

/** What THIS storefront calls the postal code field. */
export async function postalFieldLabel(request: APIRequestContext): Promise<string> {
  return postalCodeLabel((await config(request)).currency?.code);
}

let resolvedCustomer: Credentials | null = null;

/**
 * The customer this tenant's storefront can sign in as.
 *
 * **Derived, not hardcoded.** It used to be `customer1@example.com`, which
 * belongs to the MARKETPLACE client and therefore cannot sign in at
 * `localhost` however correct its password is — fifteen specs failed on the
 * login screen, and the ones that never sign in kept passing, so nothing said
 * so. Replacing one hardcoded address with another would repeat that in
 * miniature, so this applies the same rule `seed.py`'s `ensure_tenant_customer`
 * uses to CREATE the account: `{app_key}@example.com`, where the app key is
 * whatever this host actually resolves to. Point the suite at another tenant
 * and it signs in as that tenant's customer.
 */
export async function customerCredentials(request: APIRequestContext): Promise<Credentials> {
  if (resolvedCustomer) return resolvedCustomer;

  const password = process.env["E2E_CUSTOMER_PASSWORD"] ?? "password123";
  const override = process.env["E2E_CUSTOMER_EMAIL"];
  if (override) {
    resolvedCustomer = { email: override, password };
    return resolvedCustomer;
  }

  const appKey = (await config(request)).app_key;
  if (!appKey) throw new Error(`/app-config returned no app_key for "${STOREFRONT_HOST}"`);

  resolvedCustomer = { email: `${appKey}@example.com`, password };
  return resolvedCustomer;
}

async function login(
  request: APIRequestContext,
  credentials: Credentials,
  headers: Record<string, string>,
): Promise<string> {
  const response = await request.post(`${API_BASE}/auth/login`, {
    data: { email: credentials.email, password: credentials.password },
    headers,
  });
  if (!response.ok()) {
    throw new Error(
      `Could not sign in as ${credentials.email} (${response.status()}). ` +
        `Customer accounts are per tenant and are created by seed.py's ` +
        `ensure_tenant_customer; set E2E_CUSTOMER_EMAIL and E2E_CUSTOMER_PASSWORD ` +
        `to override.`,
    );
  }
  return (await response.json()).access_token as string;
}

/** A bearer token for the same customer the browser signs in as. */
export async function customerToken(request: APIRequestContext): Promise<string> {
  return login(request, await customerCredentials(request), TENANT_HEADER);
}

/**
 * Everything an authenticated customer call needs, in one object.
 *
 * The tenant header is on EVERY request, not just the login. A customer token
 * carries the app client it was issued for, and the backend checks it against
 * the one the host resolves to — so the same token that signs in fine is
 * refused on the next call with "Token was issued for a different app" if the
 * header is dropped. Returning the pair together is what stops a spec from
 * remembering one and forgetting the other, which is how this read as a
 * mysterious `undefined.full_name` rather than as an auth failure.
 */
export async function customerAuth(request: APIRequestContext): Promise<Record<string, string>> {
  return { Authorization: `Bearer ${await customerToken(request)}`, ...TENANT_HEADER };
}

/** A bearer token for platform staff. No tenant header — see above. */
export async function staffToken(
  request: APIRequestContext,
  credentials: Credentials = ADMIN,
): Promise<string> {
  return login(request, credentials, {});
}

/** Stripe's universally-accepted test card. Never a real number. */
export const TEST_CARD = { number: "4242424242424242", expiry: "1230", cvc: "123" };

const STORAGE_STATE = "bangkok-bowl-state";
const STORAGE_TOKEN = "bangkok-bowl-token";
const STORAGE_USER = "bangkok-bowl-user";

/**
 * Start from a known state.
 *
 * Must run on a page that is already on the app's origin: localStorage is
 * origin-scoped, so calling this on about:blank silently writes nothing and the
 * test then runs against whatever the last one left behind.
 */
export async function resetApp(page: Page): Promise<void> {
  await page.goto("/");
  await page.evaluate(
    ([stateKey, tokenKey, userKey]) => {
      localStorage.removeItem(tokenKey!);
      localStorage.removeItem(userKey!);
      const raw = localStorage.getItem(stateKey!);
      const state = raw ? JSON.parse(raw) : {};
      state.cart = [];
      // A returning customer who has already picked a branch.
      //
      // The branch gate is a modal over everything until a branch is chosen, so
      // without this every test that touches the menu stops at a dialog it was
      // never about. Seeded rather than clicked through: the gate deserves its
      // own test (below in order-flow) rather than four extra clicks in each of
      // thirty-five, and seeding keeps them testing the thing they name.
      state.branchChosen = true;
      localStorage.setItem(stateKey!, JSON.stringify(state));
    },
    [STORAGE_STATE, STORAGE_TOKEN, STORAGE_USER],
  );
  await page.reload();
}

/**
 * Start from a truly first-time visitor: no account, no cart, no branch picked.
 *
 * `resetApp` deliberately pre-answers the branch gate; this is for the tests
 * that are about meeting it.
 */
export async function resetAppFirstVisit(page: Page): Promise<void> {
  await page.goto("/");
  await page.evaluate(
    ([stateKey, tokenKey, userKey]) => {
      localStorage.removeItem(tokenKey!);
      localStorage.removeItem(userKey!);
      localStorage.removeItem(stateKey!);
    },
    [STORAGE_STATE, STORAGE_TOKEN, STORAGE_USER],
  );
  await page.reload();
}

/**
 * Type into a field and make sure the value survived.
 *
 * The app is server-rendered and then hydrated. Anything typed into an input
 * before React takes over is discarded when it does — the DOM value is replaced
 * by the component's (empty) state. Playwright is fast enough to lose a field
 * that way every time; a real person typing quickly can lose one too, which is
 * worth knowing independently of these tests.
 *
 * `fill` on its own would pass and leave the form empty, so the value is
 * asserted and retyped once if it did not stick.
 */
export async function fillField(
  page: Page,
  /**
   * A string is matched EXACTLY; a regular expression is matched as written.
   *
   * Exact is the right default — "Address line 1" would otherwise also match
   * "Address line 2" under a substring rule. But a label is allowed to carry a
   * hint inside it, and the accessible name then includes that hint: the
   * checkout's address field reads "Address line 1Start typing and pick your
   * building", so the exact string stopped matching the moment it became an
   * autocomplete. A regex anchored at the start survives the hint being
   * reworded.
   */
  label: string | RegExp,
  value: string,
  /**
   * What the field should read once React has it, when that differs from what
   * was typed. The phone field groups digits as you type, so "4155550132"
   * becomes "(415) 555-0132" — asserting the raw value would fail on a field
   * that is working correctly.
   */
  expected = value,
): Promise<void> {
  const field =
    typeof label === "string"
      ? page.getByLabel(label, { exact: true })
      : page.getByLabel(label);
  await field.waitFor({ state: "visible" });

  // `fill` sets the value in one shot, which a controlled React input can drop
  // if hydration lands mid-way. Real keystrokes go through the same onChange a
  // person's typing would, and the loop retypes until the value survives — a
  // single fill-and-verify can pass and still submit an empty form, because the
  // wipe happens after the check.
  for (let attempt = 0; attempt < 5; attempt += 1) {
    await field.click();
    await field.clear();
    await field.pressSequentially(value, { delay: 15 });
    await page.waitForTimeout(400);
    if ((await field.inputValue()) === expected) return;
  }
  await expect(field).toHaveValue(expected);
}

/**
 * Click something that lives in a `position: fixed` bar.
 *
 * `locator.click()` cannot do this below lg. Its actionability check calls
 * scrollIntoViewIfNeeded first, and a fixed element never "arrives" — it moves
 * with the viewport — so Chromium scrolls the page instead and then hit-tests
 * against where the button used to be, blaming whatever line of the order
 * summary it just slid under the cursor.
 *
 * Measured in the failing state, elementFromPoint over the button's centre
 * returns the button, hitIsInsideBar is true, and no ancestor up to <html>
 * carries a transform or a competing z-index. Nothing covers it.
 *
 * So this clicks at real coordinates, which is NOT `{ force: true }`: the hit
 * point is asserted to resolve inside the target first, and the click is a
 * genuine mouse event at that point. If something ever did cover the button,
 * both the assertion and the click would land on the coverer and this would
 * fail — which is the whole reason for testing it on a phone viewport.
 */
export async function clickFixed(page: Page, locator: Locator): Promise<void> {
  await locator.waitFor({ state: "visible" });
  await expect(locator).toBeEnabled();

  const box = await locator.boundingBox();
  if (!box) throw new Error("clickFixed: target has no box");
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;

  const covered = await page.evaluate(
    ([px, py]) => {
      const hit = document.elementFromPoint(px!, py!);
      return hit?.closest("button")
        ? null
        : (hit?.tagName ?? "nothing") + "." + (hit?.className ?? "");
    },
    [x, y],
  );
  if (covered) throw new Error(`clickFixed: ${covered} covers the target at ${x},${y}`);

  await page.mouse.click(x, y);
}

/** Sign in through the real form, so the redirect round-trip is exercised. */
export async function signIn(page: Page, redirectTo?: string): Promise<void> {
  await page.goto(redirectTo ? `/login?redirect=${encodeURIComponent(redirectTo)}` : "/login");
  // Let hydration finish before typing; see fillField for why it matters.
  await page.waitForLoadState("networkidle");
  const customer = await customerCredentials(page.request);
  await fillField(page, "Email", customer.email);
  // Exact, because the reveal toggle's aria-label is "Show password" and
  // getByLabel matches aria-label too — a substring match hits both and fails
  // strict mode.
  await fillField(page, "Password", customer.password);
  await page.getByRole("button", { name: /sign in/i }).click();
  try {
    await expect(page).not.toHaveURL(/\/login/, { timeout: 30_000 });
  } catch {
    // Without this, a missing account surfaces as "expected not to have URL
    // /login" thirty seconds later, which says nothing about what to do. It is
    // the single most likely reason this suite fails on a fresh checkout.
    const refusal = await page
      .locator(".inline-error, [role='alert']")
      .first()
      .innerText()
      .catch(() => "");
    throw new Error(
      `Could not sign in as ${customer.email}.` +
        (refusal ? ` The form said: ${refusal.trim()}` : "") +
        `

That account is created by seed.py's ensure_tenant_customer, one per ` +
        `tenant, because customer identity is scoped to the app client serving ` +
        `this host. Create it, or set E2E_CUSTOMER_EMAIL and ` +
        `E2E_CUSTOMER_PASSWORD to an account that exists on this tenant.`,
    );
  }
}

/**
 * Order for collection rather than delivery.
 *
 * Seeded into the store the way `resetApp` seeds the chosen branch, because
 * the switch itself lives on the cart page and clicking through to it is four
 * steps of a journey the caller is not testing.
 *
 * Used where a test is about something OTHER than delivery — the payment
 * sheet, for instance — so it does not depend on the branch having a delivery
 * price configured. That is not hypothetical: this storefront's branch has
 * `delivery_fee = 0.00` and the courier reports the area unserviceable, so
 * `create_order` refuses every delivery order with "We could not work out a
 * delivery charge for this address". A test of the Stripe sheet should not go
 * red for that, and a test that quietly worked around it would hide it.
 */
export async function choosePickup(page: Page): Promise<void> {
  await page.goto("/");
  await page.evaluate(
    ([stateKey]) => {
      const raw = localStorage.getItem(stateKey!);
      const state = raw ? JSON.parse(raw) : {};
      state.fulfillment = "PICKUP";
      localStorage.setItem(stateKey!, JSON.stringify(state));
    },
    [STORAGE_STATE],
  );
}

/** Matches the label whether or not it carries a hint after the words. */
export const ADDRESS_LINE_1 = /^Address line 1/;

/**
 * Choose a real address from the suggestion list, near the branch.
 *
 * Returns false when no suggestion arrives — the key is missing, the service
 * is down, or the query matched nothing — so the caller can fall back rather
 * than fail a test that is not about addresses.
 *
 * The query is seeded from the BRANCH the storefront is on, read off the
 * branch picker in the header, so this follows the tenant rather than naming
 * a city. Suggestions are biased to the branch's location by the backend, so a
 * street name plus that city is enough to get deliverable results.
 */
async function pickAddressNearBranch(page: Page): Promise<boolean> {
  const line1 = page.getByLabel(ADDRESS_LINE_1);
  if (!(await line1.isVisible().catch(() => false))) return false;

  // Two characters would match half the country; a word gives the service
  // something to work with while staying generic enough for any tenant.
  await line1.click();
  await line1.fill("Main Road");

  const option = page.getByRole("option").first();
  try {
    await option.waitFor({ state: "visible", timeout: 10_000 });
  } catch {
    return false;
  }
  await option.click();
  // The pick fills city, state and postal code itself, which is the point of
  // it — so waiting for one of them to be populated is how we know it landed.
  await expect(page.getByLabel("City", { exact: true })).not.toHaveValue("", {
    timeout: 10_000,
  });
  return true;
}

/**
 * Fill the checkout contact block: name, phone and the structured address.
 *
 * One helper because every spec that reaches checkout needs all of it, and
 * because the address became six fields rather than one — a change that would
 * otherwise be copied into five specs and drift.
 */
export async function fillCheckoutContact(page: Page): Promise<void> {
  await fillField(page, "Full name", "Playwright Tester");
  // Typed as digits; the field groups them as you type.
  await fillField(page, "Phone number", "4155550132", "(415) 555-0132");

  // Delivery only; a pickup order has nowhere to deliver to.
  //
  // The regex is load-bearing. This was an exact match on "Address line 1",
  // which stopped matching when the field became an autocomplete and its label
  // grew a hint — and because the miss is handled by returning early, every
  // checkout test quietly stopped filling in an address and carried on as
  // though it were a pickup order. A guard that treats "not found" as "not
  // applicable" turns a broken selector into a silent gap in coverage.
  const line1 = page.getByLabel(ADDRESS_LINE_1);
  if (!(await line1.isVisible().catch(() => false))) return;

  // PICKED from the autocomplete, not typed — and picked near the branch.
  //
  // This typed "1600 Pennsylvania Avenue NW, Washington, DC 20500" into an
  // Indian bakery's checkout. It went unnoticed for as long as the selector
  // above was broken and the whole block was skipped; the moment the block
  // ran, checkout answered, correctly, "We could not work out a delivery
  // charge for this address."
  //
  // Typing any address is not enough either. A delivery order needs
  // COORDINATES, which only arrive when a suggestion is chosen, and the
  // backend refuses a checkout without them rather than pricing from a
  // re-geocoded line. So this drives the control the way a customer does.
  const picked = await pickAddressNearBranch(page);
  if (!picked) {
    // Typed as a fallback so a spec that is not about delivery still gets
    // through when the suggestion service is unavailable. It will be refused
    // at the Pay button, which is the correct behaviour and a clearer failure
    // than an empty form.
    await fillField(page, ADDRESS_LINE_1, "Radhe Shyam Society, Singanpor");
    await fillField(page, "City", "Surat");
    await fillField(page, "State", "Gujarat");
    // Not "ZIP code": the label is derived from the tenant's currency, so it
    // reads "PIN code" here. The VALUE needs no such care — `POSTAL_SHAPE`
    // checks the shape rather than the format, for reasons given where it is
    // defined.
    await fillField(page, await postalFieldLabel(page.request), "395004");
  }
}

/**
 * Put enough in the cart to clear the branch minimum.
 *
 * Adds the first addable dish repeatedly rather than picking by name: the menu
 * is seeded data that changes, and a test that depends on a particular dish
 * existing breaks for a reason that has nothing to do with the flow.
 */
export async function fillCart(page: Page, times = 3): Promise<void> {
  await page.goto("/menu");
  const add = page.getByRole("button", { name: /^Add / }).first();
  await add.waitFor({ state: "visible", timeout: 30_000 });
  await add.click();

  // After the first add the control becomes a stepper on that same card.
  const more = page.getByRole("button", { name: /^Add another / }).first();
  for (let i = 1; i < times; i += 1) {
    await more.click();
    await page.waitForTimeout(250);
  }
}

/**
 * Force the branch closed, whatever the clock says.
 *
 * The closed-branch path used to be tested by asking the live branch whether
 * it was open and skipping when it was — so it ran only if the suite happened
 * to be run late enough, which in practice meant it did not run. Since the
 * whole point of it is the behaviour nobody sees during office hours, that is
 * the wrong way round.
 *
 * Only the two availability flags are rewritten. The slots are left alone, so
 * the app still computes a real next opening and a real set of bookable times
 * from the branch's own hours — a fixture with invented hours would pass
 * without proving the page can read the ones it will meet in production.
 */
export async function forceBranchClosed(page: Page): Promise<void> {
  await page.route("**/api/restaurants/*", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    for (const location of body.locations ?? []) {
      location.delivery_available_now = false;
      location.pickup_available_now = false;
      location.delivery_unavailable_reason = "Outside the branch's opening hours.";
      location.pickup_unavailable_reason = "Outside the branch's opening hours.";
    }
    await route.fulfill({ response, json: body });
  });
}

/**
 * Pay with Stripe's Payment Element.
 *
 * The fields live in Stripe's own cross-origin iframes — which is the whole
 * point of the Element, since card data never reaches this app — so they are
 * reached through frame locators rather than the page.
 */
export async function payWithTestCard(page: Page): Promise<void> {
  // Stripe mounts several iframes and only one holds the card fields, so the
  // right one is found by looking for the field rather than by position.
  const frames = page.frameLocator('iframe[name^="__privateStripeFrame"]');
  let cardFrame = frames.first();
  for (let i = 0; i < 6; i += 1) {
    const candidate = frames.nth(i);
    if (await candidate.getByRole("textbox", { name: /card number/i }).count()) {
      cardFrame = candidate;
      break;
    }
  }

  // By accessible name, not placeholder: Stripe labels these "Expiration
  // (MM/YY)" and "Security code" while the placeholders read "MM / YY" and
  // "CVC", so placeholder locators silently filled only the card number and the
  // form was submitted incomplete.
  await cardFrame.getByRole("textbox", { name: /card number/i }).fill(TEST_CARD.number);
  await cardFrame.getByRole("textbox", { name: /expiration/i }).fill(TEST_CARD.expiry);
  await cardFrame.getByRole("textbox", { name: /security code/i }).fill(TEST_CARD.cvc);

  // The submit lives on our page, not inside Stripe's iframe. Scrolled into
  // view and given a beat first: the sheet animates in, and a click dispatched
  // while the button is still moving lands on nothing — the form never
  // submits, with no error to show for it.
  const pay = page.getByRole("button", { name: /^Pay \$/ });
  await pay.scrollIntoViewIfNeeded();
  await page.waitForTimeout(500);
  await pay.click();
}
