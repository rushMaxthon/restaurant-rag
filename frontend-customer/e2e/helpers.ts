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
      if (raw) {
        const state = JSON.parse(raw);
        state.cart = [];
        localStorage.setItem(stateKey!, JSON.stringify(state));
      }
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
export async function fillField(page: Page, label: string, value: string): Promise<void> {
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
    if ((await field.inputValue()) === value) return;
  }
  await expect(field).toHaveValue(value);
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

/** Whether the branch can take an order right now, read from the cart screen. */
export async function branchIsOpen(page: Page): Promise<boolean> {
  await page.goto("/cart");
  const closed = page.getByText(/is closed right now/i);
  return (await closed.count()) === 0;
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
