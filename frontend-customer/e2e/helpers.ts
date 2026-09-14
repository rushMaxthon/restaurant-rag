import { expect, type Locator, type Page } from "@playwright/test";

export const CUSTOMER = { email: "customer1@example.com", password: "password123" };

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
  label: string,
  value: string,
  /**
   * What the field should read once React has it, when that differs from what
   * was typed. The phone field groups digits as you type, so "4155550132"
   * becomes "(415) 555-0132" — asserting the raw value would fail on a field
   * that is working correctly.
   */
  expected = value,
): Promise<void> {
  const field = page.getByLabel(label, { exact: true });
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
  await fillField(page, "Email", CUSTOMER.email);
  // Exact, because the reveal toggle's aria-label is "Show password" and
  // getByLabel matches aria-label too — a substring match hits both and fails
  // strict mode.
  await fillField(page, "Password", CUSTOMER.password);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page).not.toHaveURL(/\/login/, { timeout: 30_000 });
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
  const line1 = page.getByLabel("Address line 1", { exact: true });
  if (!(await line1.isVisible().catch(() => false))) return;

  await fillField(page, "Address line 1", "1600 Pennsylvania Avenue NW");
  await fillField(page, "City", "Washington");
  await fillField(page, "State", "DC");
  await fillField(page, "ZIP code", "20500");
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
