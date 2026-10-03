import { expect, test } from "@playwright/test";
import { fillCart, resetApp, signIn } from "./helpers";

/**
 * The storefront, measured rather than looked at.
 *
 * This exists because white-on-brand shipped at 3.25:1 on every primary button
 * in the product and nothing noticed for weeks. It was a deliberate choice,
 * documented in `brand-palette.ts`, made against a number the author had
 * measured — and still wrong, because 3.25 clears AA for large text and these
 * labels are 12 to 16px. A screenshot cannot catch that. Arithmetic can.
 *
 * It walks every page in both themes and asserts three things:
 *
 *   contrast  every run of text against the colour it ACTUALLY sits on,
 *             found by walking up for the first opaque ancestor.
 *   leaks     a surface painted on the wrong side of the theme — a light box
 *             on a dark page, which is how the "Open now" chip was found.
 *   overflow  the document never scrolls sideways at any width.
 *
 * **Text over photography is skipped, and has to be.** The walk stops at the
 * first opaque background, so a caption over a hero image is measured against
 * whatever is behind the picture rather than the picture. That produced a
 * confident 1.1:1 for white type that is perfectly legible. A wrong number is
 * worse than no number — it sends you to fix something that is not broken — so
 * anything inside a hero is left to human eyes. The same applies to the one
 * control whose background is painted by a sibling rather than by itself.
 */
const AUDIT = `(() => {
  const dark = document.documentElement.classList.contains('dark');
  const seen = new Set();
  const push = (list, key, value) => { if (!seen.has(key)) { seen.add(key); list.push(value); } };
  const name = (el) => el.tagName.toLowerCase() + (el.className && typeof el.className === 'string'
    ? '.' + el.className.trim().split(/\\s+/).slice(0, 2).join('.') : '');
  const rgb = (v) => { const m = /rgba?\\(([^)]+)\\)/.exec(v); if (!m) return null;
    const p = m[1].split(',').map(Number); return { r: p[0], g: p[1], b: p[2], a: p[3] === undefined ? 1 : p[3] }; };
  const lin = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
  const lum = (c) => 0.2126 * lin(c.r) + 0.7152 * lin(c.g) + 0.0722 * lin(c.b);
  const ratio = (a, b) => { const la = lum(a), lb = lum(b); return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05); };
  const over = (fg, bg) => ({ r: fg.r * fg.a + bg.r * (1 - fg.a), g: fg.g * fg.a + bg.g * (1 - fg.a), b: fg.b * fg.a + bg.b * (1 - fg.a), a: 1 });
  const effBg = (el) => { let n = el;
    while (n && n !== document.documentElement) { const cs = getComputedStyle(n);
      if (cs.backgroundImage && cs.backgroundImage !== 'none') return null;
      const c = rgb(cs.backgroundColor); if (c && c.a >= 0.95) return c; n = n.parentElement; }
    const c = rgb(getComputedStyle(document.body).backgroundColor); return c && c.a >= 0.95 ? c : null; };

  const leaks = [], contrast = [];
  for (const el of document.querySelectorAll('body *')) {
    // Over a photograph nothing here can be trusted; see the note above.
    if (el.closest('.hero-full, .hero, [data-hero]')) continue;
    // The selected segment's background is painted by a SIBLING — the pill
    // slides behind it — so walking up from the button finds the track it
    // sits on rather than the pill covering it. Measured that way the label
    // reads 1.19:1; measured against what is actually behind the glyphs it is
    // dark ink on the lifted brand, around 7:1. Same blind spot as a photo.
    if (el.matches('.segmented-option[data-selected="true"]')) continue;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity < 0.1) continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;

    const bg = rgb(cs.backgroundColor);
    if (bg && bg.a > 0.9 && r.width > 60 && r.height > 24) {
      const L = lum(bg);
      if (dark && L > 0.5) push(leaks, 'bg|' + name(el), { el: name(el), v: cs.backgroundColor });
    }

    const hasText = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim().length > 1);
    if (!hasText) continue;
    const fg = rgb(cs.color);
    if (!fg || fg.a <= 0.1) continue;
    const bgc = effBg(el);
    if (!bgc) continue;
    const c = ratio(fg.a < 1 ? over(fg, bgc) : fg, bgc);
    const size = parseFloat(cs.fontSize), weight = +cs.fontWeight || 400;
    const need = size >= 24 || (size >= 18.66 && weight >= 700) ? 3 : 4.5;
    if (c < need) push(contrast, 'c|' + name(el) + '|' + cs.color,
      { el: name(el), text: el.textContent.trim().slice(0, 30), ratio: +c.toFixed(2), need, size: Math.round(size) });
  }
  return { sideways: document.documentElement.scrollWidth > window.innerWidth + 2, leaks, contrast };
})()`;

const PAGES = ["/", "/menu", "/about", "/terms", "/privacy", "/refunds", "/cart", "/checkout", "/orders", "/profile"];

test("every page reads, in both themes", async ({ page }) => {
  test.setTimeout(600_000);
  await resetApp(page);
  await signIn(page);
  await fillCart(page, 2);

  const failures: string[] = [];

  for (const theme of ["light", "dark"] as const) {
    if (theme === "dark") {
      await page.goto("/");
      const toggle = page.getByRole("button", { name: /dark mode/i }).first();
      if (await toggle.isVisible().catch(() => false)) await toggle.click();
      await page.waitForTimeout(700);
    }

    for (const path of PAGES) {
      await page.goto(path);
      await page.waitForTimeout(2000);
      const r = (await page.evaluate(AUDIT)) as {
        sideways: boolean;
        leaks: { el: string; v: string }[];
        contrast: { el: string; text: string; ratio: number; need: number; size: number }[];
      };
      if (r.sideways) failures.push(`${theme} ${path}: scrolls sideways`);
      for (const l of r.leaks) failures.push(`${theme} ${path}: light surface on a dark page — ${l.el} ${l.v}`);
      for (const c of r.contrast) {
        failures.push(`${theme} ${path}: ${c.ratio}:1 needs ${c.need} — ${c.size}px ${c.el} "${c.text}"`);
      }
    }
  }

  expect(failures, failures.join("\n")).toEqual([]);
});
