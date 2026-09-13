# Customer Storefront — Typography & Design Tokens Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `frontend-customer` an owned, consistent typographic identity and a denser token scale, so the storefront reads as deliberately designed rather than as whatever typeface the viewer's OS happened to supply.

**Architecture:** One self-hosted variable webfont replaces a two-face OS-dependent stack. The radius and spacing scales tighten; the shadow scale flattens. All of it lands in two places only — `src/index.css` (`:root`) for fonts, radii and spacing, and `src/theme/applyTheme.ts` for shadows, because that file publishes shadows at runtime and overrides CSS. Two Vitest guards prevent the failure modes this change introduces.

**Tech Stack:** React 19, Vite 8, hand-written CSS, Vitest 3 + jsdom, Inter Variable (self-hosted woff2).

**Spec:** No separate spec file. The design was agreed in conversation on 2026-09-13 as "Section 1" of the approved Approach B; this plan restates every decision it depends on in full, so it stands alone.

## Global Constraints

- **No new runtime dependencies in `frontend-customer`.** `dependencies` stays exactly `react` + `react-dom`. The font ships as a static asset in `public/`, NOT as an `@fontsource` package. Test tooling in `devDependencies` is fine.
- **Direction is "fast and utilitarian."** Dense, quick-scanning, price and action prominent, minimal decoration. When a choice is ambiguous, pick the one that gets the customer to a price faster.
- **Colour is tenant-owned and out of scope.** `palette.ts` hue-rotates every colour token from one brand colour across 12 presets plus custom, in light and dark. Never hardcode a colour, never touch `palette.ts`, and verify changes survive a non-orange brand.
- **Touch targets keep a 44px minimum.** Density comes from spacing and type scale, never from shrinking hit areas.
- **Comments explain *why*, not what.** Match `backend/app/config/settings.py` density: state the measurement or the incident that produced a number.
- **Verification commands:** `npm test`, `npx tsc -b --noEmit`, `npm run build` — all three must pass before any commit.
- **Working directory for every command:** `frontend-customer/`.

---

### Task 1: Guard — every CSS token referenced is defined

This task exists because the bug it prevents has already happened here. `index.css` carries the comment: *"Referenced in five places and defined in none, which left every non-vegetarian dot on the menu painted in nothing at all."* Retiring and renaming tokens in Tasks 3–5 is exactly the operation that reintroduces it, so the guard lands first.

**Files:**
- Create: `src/styles/tokens.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing importable. It is a standalone guard over the four stylesheets.

- [ ] **Step 1: Write the failing test**

Create `src/styles/tokens.test.ts`:

```ts
/**
 * Every `var(--token)` in the stylesheets must resolve to a definition.
 *
 * This is not hypothetical. `index.css` documents a token that was
 * "referenced in five places and defined in none, which left every
 * non-vegetarian dot on the menu painted in nothing at all" — CSS fails
 * silently, so a missing custom property is invisible until someone notices
 * the colour is absent.
 *
 * Definitions come from two sources: the `:root` block in the stylesheets, and
 * `applyTheme.ts`, which writes colour and shadow tokens onto the root element
 * at runtime. A token defined only in `applyTheme.ts` is still defined.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const SRC = join(__dirname, '..');

const STYLESHEETS = [
  'index.css',
  'styles/app.css',
  'styles/home.css',
  'styles/screens.css',
  'styles/dish-row.css',
].map((file) => join(SRC, file));

function read(path: string): string {
  return readFileSync(path, 'utf8');
}

function definedTokens(): Set<string> {
  const defined = new Set<string>();

  for (const sheet of STYLESHEETS) {
    for (const match of read(sheet).matchAll(/^\s*(--[a-z0-9-]+)\s*:/gim)) {
      defined.add(match[1]);
    }
  }

  // applyTheme publishes colour and shadow tokens at runtime.
  for (const match of read(join(SRC, 'theme/applyTheme.ts')).matchAll(/'(--[a-z0-9-]+)'/g)) {
    defined.add(match[1]);
  }

  return defined;
}

function referencedTokens(): Map<string, string[]> {
  const referenced = new Map<string, string[]>();

  for (const sheet of STYLESHEETS) {
    for (const match of read(sheet).matchAll(/var\(\s*(--[a-z0-9-]+)/g)) {
      const token = match[1];
      referenced.set(token, [...(referenced.get(token) ?? []), sheet]);
    }
  }

  return referenced;
}

describe('CSS custom properties', () => {
  it('defines every token the stylesheets reference', () => {
    const defined = definedTokens();
    const undefinedTokens = [...referencedTokens().entries()]
      .filter(([token]) => !defined.has(token))
      .map(([token, sheets]) => `${token} (used in ${sheets.length} file(s))`);

    expect(undefinedTokens).toEqual([]);
  });

  it('defines the typography tokens the app depends on', () => {
    const defined = definedTokens();

    expect(defined.has('--font-ui')).toBe(true);
    expect(defined.has('--font-display')).toBe(true);
  });
});
```

- [ ] **Step 2: Run it and confirm it passes on the current code**

Run: `npm test -- src/styles/tokens.test.ts`

Expected: **PASS**, 2 tests.

This one guard is written against existing behaviour rather than failing first, because its whole purpose is to hold a currently-correct property still while later tasks move tokens around. If it FAILS here, stop: there is already an undefined token, and that is a real bug to report before changing anything.

- [ ] **Step 3: Commit**

```bash
git add src/styles/tokens.test.ts
git commit -m "test(customer): guard against CSS tokens referenced but never defined"
```

---

### Task 2: Guard — every @font-face file exists on disk

A `@font-face` pointing at a missing file fails silently: the browser falls straight through to the fallback and the page looks *almost* right. That is the single most likely way Task 3 breaks without anyone noticing.

**Files:**
- Create: `src/styles/fonts.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing importable.

- [ ] **Step 1: Write the failing test**

Create `src/styles/fonts.test.ts`:

```ts
/**
 * Every file a `@font-face` names must exist in `public/`.
 *
 * A missing font file produces no error anywhere: the browser silently uses
 * the next family in the stack, so the page renders in the fallback and looks
 * plausible. Without this test, a bad path or a file left out of a commit is
 * caught only by someone noticing the letterforms changed.
 */

import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const SRC = join(__dirname, '..');
const PUBLIC_DIR = join(SRC, '..', 'public');

const FONT_CSS = join(SRC, 'styles/fonts.css');

describe('@font-face declarations', () => {
  it('declares at least one face', () => {
    const css = readFileSync(FONT_CSS, 'utf8');

    expect(css).toContain('@font-face');
  });

  it('points every src at a file that exists in public/', () => {
    const css = readFileSync(FONT_CSS, 'utf8');
    const urls = [...css.matchAll(/url\(\s*['"]?([^'")]+)['"]?\s*\)/g)].map((m) => m[1]);

    expect(urls.length).toBeGreaterThan(0);

    const missing = urls.filter((url) => !existsSync(join(PUBLIC_DIR, url.replace(/^\//, ''))));

    expect(missing).toEqual([]);
  });

  it('uses font-display: swap so headlines never blank while loading', () => {
    const css = readFileSync(FONT_CSS, 'utf8');

    expect(css).toMatch(/font-display:\s*swap/);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- src/styles/fonts.test.ts`

Expected: **FAIL** — `ENOENT ... src/styles/fonts.css`. The stylesheet does not exist yet. That is the correct failure: the feature is missing, not the test.

- [ ] **Step 3: Leave it red and commit the test**

```bash
git add src/styles/fonts.test.ts
git commit -m "test(customer): require every @font-face file to exist and swap"
```

Task 3 turns it green.

---

### Task 3: Self-host Inter Variable and retire the display serif

The current stack loads no webfont at all, by an explicit decision recorded in `index.css`: *"the project ships no webfont, and a storefront should not blank its own headlines waiting for one to download."* That concern is real and is answered by `font-display: swap` plus `preload`, which were not obviously safe when that note was written. The consequence of the current approach is that the app renders in Palatino Linotype on Windows and Iowan Old Style on macOS — nobody chose either.

**Files:**
- Create: `public/fonts/inter-variable-latin.woff2`
- Create: `src/styles/fonts.css`
- Modify: `src/main.tsx` (stylesheet import order)
- Modify: `index.html` (preload link)
- Modify: `src/index.css` (the `--font-ui` / `--font-display` definitions, around lines 88–99)

**Interfaces:**
- Consumes: nothing.
- Produces: CSS custom properties `--font-ui` and `--font-display`, both resolving to the Inter stack. The 12 existing `var(--font-display)` sites and 3 `var(--font-ui)` sites keep working untouched.

- [ ] **Step 1: Download the font**

```bash
mkdir -p public/fonts
curl -fsSL -o public/fonts/inter-variable-latin.woff2 \
  "https://cdn.jsdelivr.net/npm/@fontsource-variable/inter@5.1.0/files/inter-latin-wght-normal.woff2"
ls -l public/fonts/inter-variable-latin.woff2
```

Expected: a file of roughly 48KB. Verified reachable on 2026-09-13, `Content-Type: font/woff2`, `Content-Length: 48444`. If the download fails or the file is under 10KB, stop — a truncated or HTML-error-page download will pass `existsSync` and still render nothing.

- [ ] **Step 2: Write the font stylesheet**

Create `src/styles/fonts.css`:

```css
/* --- webfont ------------------------------------------------------------------
   One face, self-hosted.

   This reverses a documented decision. `index.css` previously said the project
   "ships no webfont, and a storefront should not blank its own headlines
   waiting for one to download" — a fair concern, and the reason the app used
   whatever the OS had. The cost was that nobody owned the result: the UI stack
   fell through to Segoe UI on Windows and Avenir Next on macOS, and the display
   stack to Palatino Linotype and Iowan Old Style respectively. The app looked
   materially different per platform and neither typeface was chosen.

   `font-display: swap` answers the original objection directly: text paints
   immediately in the fallback and upgrades when the file arrives, so a headline
   is never blank. The file is 48KB, latin-only, and preloaded from `index.html`.

   Self-hosted rather than an `@fontsource` package because `frontend-customer`
   keeps `dependencies` to react and react-dom exactly; a static asset in
   `public/` adds nothing to the dependency tree and removes a network hop.

   One variable file covers every weight the app uses, so weight changes cost no
   extra request.
*/
@font-face {
  font-family: 'InterVariable';
  font-style: normal;
  font-weight: 100 900;
  font-display: swap;
  src: url('/fonts/inter-variable-latin.woff2') format('woff2');
}
```

- [ ] **Step 3: Import it first, before anything that uses it**

In `src/main.tsx`, add the import directly above `import './index.css';`:

```ts
// First: `@font-face` must be registered before any rule that names the family,
// and before `index.css` defines `--font-ui` in terms of it.
import './styles/fonts.css';
import './index.css';
```

- [ ] **Step 4: Preload the file**

In `index.html`, inside `<head>`, directly after the `<meta name="viewport" ...>` line:

```html
    <!-- Preloaded because the font is needed for first paint. Without this the
         browser discovers it only after parsing CSS, which is late enough that
         the swap is visible as a flash of fallback text. `crossorigin` is
         required even same-origin: fonts are fetched in CORS mode, and omitting
         it causes a second, uncached fetch. -->
    <link
      rel="preload"
      href="/fonts/inter-variable-latin.woff2"
      as="font"
      type="font/woff2"
      crossorigin
    />
```

- [ ] **Step 5: Point both tokens at the new face**

In `src/index.css`, replace the typography block (the comment plus the two definitions, currently around lines 88–99) with:

```css
  /* --- typography --------------------------------------------------------
     One face, every screen. The serif that used to carry display type is
     retired: "fast and utilitarian" does not want two voices, and the serif in
     practice resolved to Palatino Linotype on Windows and Iowan Old Style on
     macOS — a different identity per platform, chosen by neither.

     `--font-display` survives as a token rather than being deleted, because it
     is named at 12 call sites across `home.css` and `screens.css`. Pointing it
     at the same stack changes every one of them with a single edit and leaves
     the door open to reintroduce a display face later without hunting them
     down again.

     The fallbacks are ordered by metric similarity to Inter, so the swap moves
     letterforms as little as possible: Segoe UI Variable and Roboto are close;
     the generic `sans-serif` is the last resort. */
  --font-ui: 'InterVariable', 'Segoe UI Variable Text', 'Segoe UI', Roboto,
    system-ui, -apple-system, sans-serif;
  --font-display: var(--font-ui);
```

- [ ] **Step 6: Run the font guard and verify it passes**

Run: `npm test -- src/styles/fonts.test.ts`

Expected: **PASS**, 3 tests. This is the red-to-green transition for Task 2.

- [ ] **Step 7: Run the full check**

```bash
npm test
npx tsc -b --noEmit
npm run build
```

Expected: all tests pass (Task 1's guard included), no type errors, build succeeds.

- [ ] **Step 8: Verify visually that the font actually loaded**

Start the dev server (`npm run dev -- --port 5173 --strictPort`), open `http://localhost:5173/`, and in DevTools console run:

```js
document.fonts.check('16px InterVariable')
```

Expected: `true`. If it returns `false`, the `@font-face` registered but the file did not load — check the Network tab for a 404 on `/fonts/inter-variable-latin.woff2`. Confirm by eye that headings are no longer serif.

- [ ] **Step 9: Commit**

```bash
git add public/fonts/inter-variable-latin.woff2 src/styles/fonts.css src/main.tsx index.html src/index.css
git commit -m "feat(customer): self-host one variable face and retire the display serif"
```

---

### Task 4: Tighten the radius scale

Current radii peak at 26px, which reads soft and consumer-friendly. Utilitarian wants crisper corners. Pill shapes are kept for chips and status only, where the shape carries meaning.

**Files:**
- Modify: `src/index.css` (the radii block, around lines 123–131)

**Interfaces:**
- Consumes: nothing.
- Produces: the same eight token names with new values. No call site changes, so nothing downstream needs updating.

- [ ] **Step 1: Replace the radii block**

In `src/index.css`, replace the radii block with:

```css
  /* --- radii, the app's scale ---------------------------------------------
     Roughly halved at the top end. The old scale peaked at 26px, which reads
     as soft and consumer-friendly; this direction wants the opposite, and a
     dense grid of large-radius cards wastes real estate at every corner.

     `--radius-pill` is deliberately NOT reduced: on a chip or a status badge
     the full round is the signal that the thing is a tag rather than a button,
     so flattening it would remove meaning rather than decoration. */
  --radius-xl: 14px;
  --radius-pill: 999px;
  --radius-lg: 12px;
  --radius-md: 10px;
  --radius-card: 8px;
  --radius-sm: 8px;
  --radius-xs: 6px;
  --radius-button: 6px;
```

Note `--radius-pill` moves from `20px` to `999px`. At 20px it was not a pill at all on anything taller than 40px — it was just another rounded rectangle, indistinguishable from `--radius-lg`, which is why chips and cards currently look alike.

- [ ] **Step 2: Run the full check**

```bash
npm test
npx tsc -b --noEmit
npm run build
```

Expected: all pass. Task 1's guard confirms no token was lost in the edit.

- [ ] **Step 3: Verify visually**

With the dev server running, load `http://localhost:5173/` and a restaurant page. Confirm: cards have visibly tighter corners; category chips and the "Open now" badge are still fully rounded and still read as tags.

- [ ] **Step 4: Commit**

```bash
git add src/index.css
git commit -m "feat(customer): tighten the radius scale, and make the pill an actual pill"
```

---

### Task 5: Flatten the shadow scale

**This task does not touch `index.css`.** `applyTheme.ts` writes `--shadow-xs` through `--shadow-xl` onto the root element at runtime from `theme.colors.shadow`, so whatever `index.css` says is overwritten on first paint. Editing the CSS block would appear to do nothing and waste a debugging session.

**Files:**
- Modify: `src/theme/applyTheme.ts` (the `shadows()` function, around lines 22–32)

**Interfaces:**
- Consumes: `AppTheme` from `./themeBase` (unchanged).
- Produces: the same five keys `--shadow-xs`, `--shadow-sm`, `--shadow-md`, `--shadow-lg`, `--shadow-xl`, with flatter values. Signature of `shadows(theme: AppTheme): Record<string, string>` is unchanged.

- [ ] **Step 1: Replace the shadows function**

In `src/theme/applyTheme.ts`, replace the `shadows` function with:

```ts
/** Tokens the app expresses as shadow objects, which CSS states as one string.
 *
 * Flattened for the dense direction. Five distinct elevations made sense when
 * cards were large and widely spaced; in a tight grid, stacked glow reads as
 * blur rather than as depth, and it fights the hairline borders that now carry
 * separation. The top of the scale is pulled down hard — `--shadow-xl` was a
 * 38px blur, which on a 190px tile spread further than the tile itself.
 *
 * The five names are kept rather than collapsed, because they are referenced
 * across four stylesheets; re-pointing the values costs one edit, renaming them
 * would cost dozens and gain nothing.
 */
function shadows(theme: AppTheme): Record<string, string> {
  const s = theme.colors.shadow;
  return {
    '--shadow-xs': `0 1px 2px ${s}`,
    '--shadow-sm': `0 1px 3px ${s}`,
    '--shadow-md': `0 2px 6px ${s}`,
    '--shadow-lg': `0 4px 12px ${s}`,
    '--shadow-xl': `0 8px 20px ${s}`,
  };
}
```

- [ ] **Step 2: Run the full check**

```bash
npm test
npx tsc -b --noEmit
npm run build
```

Expected: all pass.

- [ ] **Step 3: Verify visually, in both themes**

Load the app. Cards should read as separated by their borders rather than by glow. Then switch to dark mode via the in-app appearance setting (`/appearance`) and confirm the shadows still read correctly — dark mode uses a much stronger shadow colour (`rgba(0, 0, 0, 0.34)` versus light's `rgba(20, 23, 34, 0.12)`), so a blur radius that looks subtle in light can look heavy in dark.

- [ ] **Step 4: Commit**

```bash
git add src/theme/applyTheme.ts
git commit -m "feat(customer): flatten elevation so borders carry separation"
```

---

### Task 6: Introduce an explicit type scale

The stylesheets currently set font sizes ad hoc in px at each call site, so there is no scale to be consistent with. This task adds one as tokens and applies it to the heading sites only — the 12 places that named `--font-display`. Body and control sizing is left alone deliberately: converting 11k lines of CSS to tokens is a separate, much larger change, and doing it here would bury the typography result in noise.

**Files:**
- Modify: `src/index.css` (add a type-scale block immediately after the typography block from Task 3)
- Modify: `src/styles/home.css` (5 `--font-display` sites)
- Modify: `src/styles/screens.css` (7 `--font-display` sites)

**Interfaces:**
- Consumes: `--font-ui` from Task 3.
- Produces: `--text-xs`, `--text-sm`, `--text-base`, `--text-lg`, `--text-xl`, `--text-2xl`, `--text-3xl`, and `--leading-tight` / `--leading-normal`.

- [ ] **Step 1: Add the scale**

In `src/index.css`, directly below the typography block added in Task 3:

```css
  /* --- type scale --------------------------------------------------------
     A 1.2 ratio (minor third), which is tight enough that adjacent steps stay
     distinguishable without any one step dominating a dense screen. A 1.25 or
     1.333 scale pushes the top of the range past 40px, and a page whose
     headline is 40px cannot also show six dishes above the fold.

     Headings additionally get `--leading-tight`: at display sizes the default
     line height opens gaps that read as unintentional spacing. */
  --text-xs: 11px;
  --text-sm: 13px;
  --text-base: 15px;
  --text-lg: 18px;
  --text-xl: 22px;
  --text-2xl: 26px;
  --text-3xl: 31px;

  --leading-tight: 1.15;
  --leading-normal: 1.5;
```

- [ ] **Step 2: Apply the scale at the heading sites**

Find every rule that sets `font-family: var(--font-display)`:

```bash
grep -n 'var(--font-display)' src/styles/home.css src/styles/screens.css
```

For each of the 12 rules, ensure the rule also carries a scale token and tight leading. Where the rule already has a `font-size` in px, replace that value with the nearest scale token — do not add a second `font-size` declaration. Mapping to use:

| Existing px | Token |
|---|---|
| ≤ 12px | `--text-xs` |
| 13–14px | `--text-sm` |
| 15–16px | `--text-base` |
| 17–20px | `--text-lg` |
| 21–24px | `--text-xl` |
| 25–28px | `--text-2xl` |
| ≥ 29px | `--text-3xl` |

Where the rule sets no `font-size` at all, leave it alone — it is inheriting deliberately, and forcing a size would change more than typography.

Add `line-height: var(--leading-tight);` to any rule whose resulting size is `--text-xl` or larger, unless it already sets `line-height`.

- [ ] **Step 3: Run the full check**

```bash
npm test
npx tsc -b --noEmit
npm run build
```

Expected: all pass, including Task 1's guard — which is what catches a mistyped token name like `--text-md` that does not exist.

- [ ] **Step 4: Verify visually**

Load Home and a restaurant page. Headings should sit on a visible scale rather than at arbitrary sizes, and no heading should wrap where it previously did not.

- [ ] **Step 5: Commit**

```bash
git add src/index.css src/styles/home.css src/styles/screens.css
git commit -m "feat(customer): put headings on an explicit type scale"
```

---

### Task 7: Confirm the tokens survive a non-default brand and dark mode

Every change above is brand-neutral by construction, but "by construction" is not evidence. This platform ships 12 theme presets from Sunset `#FF5200` to Indigo `#4338CA` to Slate `#334155`, and a token change that quietly assumes warm colours would only surface on a tenant's site.

**Files:**
- None. This is a verification task with no production change.

**Interfaces:**
- Consumes: everything from Tasks 3–6.
- Produces: nothing.

- [ ] **Step 1: Switch the seeded restaurant to a cold preset**

Using the Supabase MCP (project `eeorvcsfpndaovhvgyom`) or `psql`:

```sql
UPDATE restaurants
SET theme = '{"preset": "indigo", "primary_color": "#4338CA"}'::jsonb
WHERE slug = 'bangkok-bowl';
```

- [ ] **Step 2: Reload and inspect**

Hard-reload `http://localhost:5173/`. Confirm: the entire UI has shifted to indigo; no element is still orange; text remains legible against every surface; the font, radii, shadows and type scale are unchanged by the hue shift.

- [ ] **Step 3: Repeat in dark mode**

Switch to dark via `/appearance` and re-inspect the same screens.

- [ ] **Step 4: Restore the original theme**

```sql
UPDATE restaurants
SET theme = '{"preset": "sunset", "primary_color": "#FF5200"}'::jsonb
WHERE slug = 'bangkok-bowl';
```

- [ ] **Step 5: Record the result**

Append an entry to `.claude/worklog.md` stating which presets and modes were checked and what was observed. If anything looked wrong, write down what and stop rather than continuing to Task 8.

---

### Task 8: Update the project documentation

**Files:**
- Modify: `CLAUDE.md` (the "Conventions that are easy to violate by accident" section)

**Interfaces:**
- Consumes: nothing.
- Produces: nothing.

- [ ] **Step 1: Record the font decision and the token map**

Add to `CLAUDE.md` under the conventions section:

```markdown
**Typography is owned, and self-hosted.** `frontend-customer` ships Inter
Variable from `public/fonts/` via `src/styles/fonts.css`, imported before
`index.css` in `main.tsx` and preloaded from `index.html`. This reversed an
earlier documented decision to use only OS fonts; that decision avoided
render-blocking but left the app rendering in Palatino Linotype on Windows and
Iowan Old Style on macOS. `font-display: swap` addresses the original concern.
`--font-display` still exists as a token but resolves to `--font-ui`.

**Know which file owns which token.** `src/index.css` `:root` owns fonts, radii,
spacing and the type scale. `src/theme/applyTheme.ts` owns colours AND shadows,
writing them onto the root element at runtime — so it OVERRIDES `index.css` for
those. Editing shadow values in CSS appears to do nothing. `themeBase.ts` also
exports `radius` and `spacing` objects; these currently have zero consumers in
components and are not published to CSS.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: record the typography decision and which file owns which token"
```

---

## Self-Review

**Spec coverage.** The agreed Section 1 had four parts. Type → Tasks 2, 3, 6. Scale/radii → Task 4. Shadows → Task 5. Density from spacing not touch targets → held as a global constraint; the spacing scale itself is deliberately left unchanged, because the dense grid landed in `dish-row.css` in the previous commit and re-cutting the global spacing scale would move every screen at once. **This is a scope reduction from what was described as "the spacing scale loses its top end" and should be confirmed before execution.** The desktop dead-space fix was also part of Section 1 as discussed, and was already delivered in commit `fd5c684` via `auto-fill` in `dish-row.css`; no task repeats it.

**Placeholder scan.** No TBDs. Every code step carries the literal content. Task 6 Step 2 is rule-driven rather than a fixed diff because the 12 target rules have differing existing declarations; the mapping table and the two "leave it alone" conditions make it deterministic.

**Type consistency.** `shadows(theme: AppTheme): Record<string, string>` keeps its signature and all five keys. `--font-display` is retained everywhere rather than removed. Token names introduced in Task 6 are referenced only in Task 6. Task 1's guard enforces consistency across all of them.

**Known risk.** Tasks 4, 5 and 6 have no automated test proving the *visual* result — only that nothing broke. CSS value changes are not meaningfully unit-testable, so each carries an explicit visual verification step instead. Task 7 exists because the highest-consequence failure (a brand-dependent assumption) is invisible on the default theme.
