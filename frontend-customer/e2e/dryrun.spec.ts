import { test, type ConsoleMessage, type Page, type Request } from "@playwright/test";
import { writeFileSync, mkdirSync } from "node:fs";
import { fillCart, fillField, resetApp, signIn } from "./helpers";

/**
 * A dry run of the whole customer journey, instrumented.
 *
 * Not an assertion suite - it never fails on purpose. It walks the app the way
 * a person would and records everything that would make the experience feel
 * broken or slow: console errors, failed requests, long waits, and pages that
 * render nothing. The output is a report to read, not a pass/fail.
 */

type Issue = { step: string; kind: string; detail: string };

function instrument(page: Page, issues: Issue[], step: () => string) {
  page.on("console", (m: ConsoleMessage) => {
    if (m.type() === "error" || m.type() === "warning") {
      const text = m.text();
      // React's dev-only key/hydration noise is worth seeing, everything from
      // extensions and favicons is not.
      if (/favicon|Download the React DevTools/i.test(text)) return;
      issues.push({ step: step(), kind: `console.${m.type()}`, detail: text.slice(0, 300) });
    }
  });
  page.on("pageerror", (e) => {
    issues.push({ step: step(), kind: "pageerror", detail: String(e).slice(0, 300) });
  });
  page.on("requestfailed", (r: Request) => {
    const url = r.url();
    if (/stripe\.com|fonts\.g/.test(url)) return;
    issues.push({ step: step(), kind: "requestfailed", detail: `${r.method()} ${url} :: ${r.failure()?.errorText}` });
  });
  page.on("response", (r) => {
    if (r.status() >= 400 && r.url().includes("/api/")) {
      issues.push({ step: step(), kind: `http.${r.status()}`, detail: `${r.request().method()} ${r.url()}` });
    }
  });
}

test("dry run: the whole customer journey", async ({ page }) => {
  const issues: Issue[] = [];
  const timings: { step: string; ms: number; visibleText: number }[] = [];
  let current = "boot";
  instrument(page, issues, () => current);

  async function step(name: string, fn: () => Promise<void>) {
    current = name;
    const t0 = Date.now();
    try {
      await fn();
    } catch (e) {
      issues.push({ step: name, kind: "STEP FAILED", detail: String(e).slice(0, 400) });
    }
    const ms = Date.now() - t0;
    const visibleText = await page
      .evaluate(() => document.body.innerText.trim().length)
      .catch(() => -1);
    timings.push({ step: name, ms, visibleText });
  }

  await step("home", async () => {
    await resetApp(page);
    await page.waitForLoadState("networkidle");
  });

  await step("menu browse", async () => {
    await page.goto("/menu");
    await page.waitForLoadState("networkidle");
  });

  await step("menu search", async () => {
    const search = page.getByRole("searchbox").or(page.getByPlaceholder(/search/i)).first();
    if (await search.count()) {
      await search.click();
      await search.pressSequentially("curry", { delay: 20 });
      await page.waitForTimeout(1200);
    } else {
      issues.push({ step: "menu search", kind: "MISSING", detail: "no search input found on /menu" });
    }
  });

  await step("menu search nonsense", async () => {
    const search = page.getByRole("searchbox").or(page.getByPlaceholder(/search/i)).first();
    if (await search.count()) {
      await search.fill("");
      await search.pressSequentially("zzzzqqq", { delay: 20 });
      await page.waitForTimeout(1200);
      const body = await page.evaluate(() => document.body.innerText);
      if (!/no |nothing|couldn't find|try/i.test(body)) {
        issues.push({ step: "menu search nonsense", kind: "UX", detail: "no empty-state copy for a search with zero results" });
      }
      await search.fill("");
      await page.waitForTimeout(800);
    }
  });

  await step("dish detail", async () => {
    await page.goto("/menu");
    await page.waitForLoadState("networkidle");
    await page.getByRole("article").first().getByRole("link").first().click();
    await page.waitForURL(/\/menu\/[^/]+$/, { timeout: 15_000 });
    await page.waitForLoadState("networkidle");
  });

  await step("add to cart from detail", async () => {
    const add = page.getByRole("button", { name: /add|cart/i }).first();
    await add.click();
    await page.waitForTimeout(800);
  });

  await step("concierge", async () => {
    await page.goto("/concierge");
    await page.waitForLoadState("networkidle");
    const box = page.getByRole("textbox").first();
    await box.click();
    await box.pressSequentially("what is good for someone who hates spice", { delay: 10 });
    await page.keyboard.press("Enter");
    await page.getByRole("article").first().waitFor({ timeout: 170_000 }).catch(() => {
      issues.push({ step: "concierge", kind: "UX", detail: "no dish cards came back within 170s" });
    });
  });

  await step("cart", async () => {
    await fillCart(page, 3);
    await page.goto("/cart");
    await page.waitForLoadState("networkidle");
  });

  await step("login", async () => {
    await signIn(page, "/checkout");
  });

  await step("checkout form", async () => {
    await fillField(page, "Full name", "Dry Run");
    await fillField(page, "Phone number", "9876543210");
    if (await page.getByLabel("Delivery address", { exact: true }).isVisible()) {
      await fillField(page, "Delivery address", "B-402 Riverside, Bodakdev");
    }
  });

  await step("switch to pickup and back", async () => {
    const pickup = page.getByRole("button", { name: /^pickup$/i }).first();
    if (await pickup.count()) {
      await pickup.click();
      await page.waitForTimeout(900);
      const delivery = page.getByRole("button", { name: /^delivery$/i }).first();
      if (await delivery.count()) await delivery.click();
      await page.waitForTimeout(900);
    }
  });

  await step("orders history", async () => {
    await page.goto("/orders");
    await page.waitForLoadState("networkidle");
  });

  await step("order detail", async () => {
    const first = page.getByRole("link").filter({ hasText: /order|#/i }).first();
    if (await first.count()) {
      await first.click();
      await page.waitForTimeout(2000);
    } else {
      issues.push({ step: "order detail", kind: "UX", detail: "no clickable order in history" });
    }
  });

  await step("account", async () => {
    await page.goto("/account");
    await page.waitForLoadState("networkidle");
  });

  await step("unknown route", async () => {
    await page.goto("/this-route-does-not-exist");
    await page.waitForTimeout(1500);
    const body = await page.evaluate(() => document.body.innerText);
    if (body.trim().length < 20) {
      issues.push({ step: "unknown route", kind: "UX", detail: "404 page renders almost nothing" });
    }
  });

  mkdirSync("test-results", { recursive: true });
  writeFileSync(
    "test-results/dryrun.json",
    JSON.stringify({ issues, timings }, null, 1),
    "utf-8",
  );
  console.log("DRYRUN steps:", timings.length, "issues:", issues.length);
});
