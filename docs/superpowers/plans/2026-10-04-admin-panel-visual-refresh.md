# Admin Panel Visual Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make all 27 screens of `frontend-admin` look like one premium product by putting spacing, weight, radius, elevation and colour on tokens and collapsing duplicated components, without changing what any screen does.

**Architecture:** A foundation pass adds the missing tokens and unifies the shared components every screen is built from; seven screen batches then bring each feature's own CSS (`rpt-`, `mkt-`, `ai-`…) onto that foundation. A new stylesheet test, `styleBudget.test.ts`, counts off-token declarations per class family and can only go down, so each batch starts by lowering its family's budget to zero and watching the test fail.

**Tech Stack:** React 19 + Vite, hand-written CSS (`frontend-shared/tokens.css`, `frontend-shared/components.css`, `frontend-admin/src/index.css`, `frontend-admin/src/legacy.css`), vitest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-04-admin-panel-visual-refresh-design.md`

## Global Constraints

- Scope is `frontend-admin/` plus additive changes to `frontend-shared/`. Nothing in `backend/`, `frontend-customer/src`, `frontend-kitchen/src` or `mobile/` is edited.
- No behaviour change: no screen gains, loses, renames or moves a control, tab, route or field. Markup changes are limited to swapping a bespoke header/tile/tab for the shared component with the same content.
- No new dependencies in `frontend-admin` (CLAUDE.md).
- **Never run a formatter over `legacy.css`.** `adminStyles.test.ts` matches selector text literally, including the two-line group `.page-intro h1,\n.login-card h1` and `.admin-table th, .admin-table td`.
- Every `var(--x)` used in `legacy.css` must resolve (`adminStyles.test.ts`). A token is never deleted without an alias left behind.
- Badge tones stay doubled: `.status-pill.status-pill--success`.
- `index.css` cascade order (shared tokens → shared components → `legacy.css` in `layer(legacy)` → the panel's own `:root`) is load-bearing and is not reordered.
- Shared tokens are only ADDED. An existing token in `frontend-shared/tokens.css` is not re-valued.
- Shared CSS never assumes a warm accent; the storefront rewrites `--primary` per tenant.
- Touch targets stay ≥ 44px at phone width; a disabled button still states why.
- Comments explain why, in the density the surrounding CSS already has.
- Windows checkout: run commands from Git Bash with forward slashes; python is `backend/.venv/Scripts/python.exe`.
- Commit messages end with:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01JFJkFSMqqK5aVpJZytBUDN
  ```
  Commit per task. Push only when Hitesh asks.

## Review Focus

Conditions the spec implies that no stylesheet test exercises. Each is checked by hand in the task that owns the screen (the "Look" step).

1. **Light theme.** Work is done in dark by default; a token that only has a dark value leaves a dark band on a light page. Every screen is viewed in both themes — Task 1 Step 9 and the Look step of every screen task.
2. **Phone width (390px).** A tile row or toolbar that fits at 1440px wraps badly or overflows; the sidebar becomes a drawer. Checked in every Look step with the audit's `overflow` list.
3. **Long real data.** A 60-character restaurant or dish name, a ₹1,23,456.00 amount, an empty list, a 200-row table. Checked on Orders (Task 4), Menu Items (Task 5) and Restaurants (Task 6) against live data, not seed-length strings.
4. **The ADMIN role.** The browser session is usually an OWNER; ADMIN sees the restaurant picker, Storefront apps, Users with every role, and all-restaurant tables. Each screen task walks both roles (`admin@example.com` / seed password on localhost).
5. **The storefront and kitchen board.** They import `frontend-shared/`. Task 1 and Task 2 build both after touching it.

---

## Reference: the snap table

Used by every task. An off-scale value becomes the nearest step; when two are equally near, the smaller one inside a control and the larger one between blocks.

| Literal | Token | | Literal | Token |
|---|---|---|---|---|
| 2px, 3px | keep literal (optical nudge) | | 16px | `var(--space-4)` |
| 4px, 5px | `var(--space-1)` | | 18px, 20px | `var(--space-5)` |
| 6px, 8px | `var(--space-2)` | | 22px, 24px | `var(--space-6)` |
| 10px, 12px | `var(--space-3)` | | 28px, 32px | `var(--space-8)` |
| 14px | `var(--space-4)` between blocks, `var(--space-3)` inside a control | | 40px | `var(--space-10)` |

Weights: 300/400/500 → `var(--fw-regular)`; 600/650 → `var(--fw-medium)`; 700/750 → `var(--fw-strong)`; 800/900 → `var(--fw-heavy)`, and then demote per the rule in Task 1 (heavy is for the page title and a stat figure only).

Colour: a hex/`rgba()` that equals a token becomes the token; a translucent white/black on the sidebar becomes `color-mix(in srgb, var(--sidebar-ink) N%, transparent)`; a tint of the brand becomes `color-mix(in srgb, var(--primary) N%, var(--surface))`.

## Reference: the Look step

Every screen task ends with this, on `http://localhost:5174` with the backend on 8000:

1. Open the screen. Paste `frontend-admin/scripts/audit-pages.js` into the console (or `eval(localStorage.__audit)`); record `leaks`, `contrast`, `tiny`, `overflow` counts.
2. Screenshot at 1440px and at 390px, dark then light (Display settings toggles the theme).
3. Compare with the "before" set taken in the task's first step. The counts must not rise; the screen must have the same controls in the same places.
4. Repeat signed in as ADMIN if the screen is admin-visible.

---

### Task 1: Tokens and the style budget

**Files:**
- Create: `frontend-admin/src/styleBudget.ts`, `frontend-admin/src/styleBudget.test.ts`
- Modify: `frontend-shared/tokens.css` (append to `:root`, after `--leading-relaxed`)
- Modify: `frontend-admin/src/index.css` (`:root` block, the "Legacy aliases" group)

**Interfaces:**
- Produces: tokens `--fw-regular|medium|strong|heavy`, `--pad-card`, `--pad-card-lg`, `--pad-row`, `--pad-control`, `--gap-stack`, `--gap-inline`, `--gap-section`, `--radius-control`, `--radius-card`, `--radius-modal`, `--sidebar-ink`.
- Produces: `measure(css: string): Record<string, Counts>` and `familyOf(selector: string): string` from `styleBudget.ts`, where `Counts = { spacing: number; weight: number; colour: number }`; and the `BUDGET` map in the test, which every later task lowers.

- [ ] **Step 1: Write the measuring module**

`frontend-admin/src/styleBudget.ts`:

```ts
/**
 * How much of the stylesheet is still improvised, per class family.
 *
 * Type, radius, shadow and motion were put on tokens long ago and are used.
 * Spacing, weight and colour were not: 336 paddings in 153 distinct values,
 * every weight a bare number, 119 hex literals. That is what makes two screens
 * built from the same components sit on different rhythms.
 *
 * This counts what is left, grouped by the first word of the selector's class
 * (`rpt`, `mkt`, `admin`…), so a screen can be brought onto the scale one
 * family at a time and cannot drift back afterwards.
 */

export interface Counts {
  spacing: number;
  weight: number;
  colour: number;
}

/** `.rpt-card__title:hover` → `rpt`; `.dark .mkt-x` → `mkt`. */
export function familyOf(selector: string): string {
  const classes = selector.match(/\.([a-zA-Z][\w-]*)/g) ?? [];
  const first = classes.map((c) => c.slice(1)).find((c) => c !== "dark");
  if (!first) return "(element)";
  return first.split(/[-_]/)[0];
}

const SPACING = /(?:^|;|\s)(?:padding|gap|row-gap|column-gap)\s*:\s*([^;]+)/g;
const WEIGHT = /font-weight\s*:\s*([^;]+)/g;
const COLOUR = /#[0-9a-fA-F]{3,8}\b|rgba?\(/g;

// 0, 1px-3px (optical nudges and hairlines) and percentages are not rhythm.
const offScale = (value: string) =>
  value
    .split(/\s+/)
    .some((part) => /^\d*\.?\d+(px|rem|em)$/.test(part) && !/^[0-3]px$/.test(part));

export function measure(css: string): Record<string, Counts> {
  const out: Record<string, Counts> = {};
  const stripped = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const rule = /([^{}]+)\{([^{}]*)\}/g;
  let match: RegExpExecArray | null;
  while ((match = rule.exec(stripped))) {
    const selector = match[1].trim();
    if (selector.startsWith("@") || /^(from|to|\d+%)/.test(selector)) continue;
    const family = familyOf(selector.split(",")[0]);
    const body = match[2];
    const counts = (out[family] ??= { spacing: 0, weight: 0, colour: 0 });
    for (const m of body.matchAll(SPACING)) {
      if (!m[1].includes("var(") && offScale(m[1].trim())) counts.spacing += 1;
    }
    for (const m of body.matchAll(WEIGHT)) {
      if (!m[1].includes("var(")) counts.weight += 1;
    }
    counts.colour += body.match(COLOUR)?.length ?? 0;
  }
  return out;
}
```

- [ ] **Step 2: Write the failing test**

`frontend-admin/src/styleBudget.test.ts`:

```ts
/**
 * A ratchet. Each number is how many off-token declarations a family still
 * has; a number may be lowered and never raised. A screen pass starts by
 * setting its families to zero here and watching this fail.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { familyOf, measure, type Counts } from "./styleBudget";

const here = fileURLToPath(new URL(".", import.meta.url));
const css = readFileSync(`${here}legacy.css`, "utf8").replace(/\r\n/g, "\n");

const BUDGET: Record<string, Counts> = {};

describe("familyOf", () => {
  it("names a rule by the first word of its class", () => {
    expect(familyOf(".rpt-card__title:hover")).toBe("rpt");
    expect(familyOf(".dark .mkt-shell")).toBe("mkt");
    expect(familyOf(".primary-button")).toBe("primary");
    expect(familyOf("button")).toBe("(element)");
  });
});

describe("measure", () => {
  it("counts off-scale spacing, bare weights and literal colours", () => {
    const sample = `
      .x-a { padding: 12px 14px; gap: var(--space-3); font-weight: 700; color: #fff; }
      .x-b { padding: 0; gap: 2px; font-weight: var(--fw-strong); border: 1px solid rgba(0,0,0,.1); }
    `;
    expect(measure(sample).x).toEqual({ spacing: 1, weight: 1, colour: 2 });
  });
});

describe("the stylesheet does not drift off its tokens", () => {
  const actual = measure(css);

  it("has a budget for every family", () => {
    const missing = Object.keys(actual).filter((family) => !(family in BUDGET));
    // Printed so the baseline can be pasted in once, in Task 1.
    if (missing.length) console.log(JSON.stringify(actual, null, 1));
    expect(missing).toEqual([]);
  });

  it.each(Object.keys(actual))("%s stays within its budget", (family) => {
    const budget = BUDGET[family] ?? { spacing: 0, weight: 0, colour: 0 };
    expect(actual[family].spacing).toBeLessThanOrEqual(budget.spacing);
    expect(actual[family].weight).toBeLessThanOrEqual(budget.weight);
    expect(actual[family].colour).toBeLessThanOrEqual(budget.colour);
  });
});
```

- [ ] **Step 3: Run it and record the baseline**

Run: `cd frontend-admin && npx vitest run src/styleBudget.test.ts`
Expected: `familyOf` and `measure` PASS; "has a budget for every family" FAILS and prints the JSON object of current counts.

Paste that object as the value of `BUDGET` (replace `{}`), one family per line, sorted by name. Run again.
Expected: all PASS. This is the baseline every later task lowers.

- [ ] **Step 4: Add the tokens**

Append inside `:root` in `frontend-shared/tokens.css`, after the `--leading-relaxed` line:

```css
  /* ---- Weight ------------------------------------------------------------
     Four, with a job each. The panel had 312 weight declarations as bare
     numbers and 233 of them were 700 or 800 — when most text is bold nothing
     is, and the eye has no page title to land on. Regular is 500 because
     Plus Jakarta Sans at 400 goes thin at 12-13px on a dark surface. */
  --fw-regular: 500;   /* body, descriptions, table cells */
  --fw-medium: 600;    /* labels, nav, buttons, emphasised cells */
  --fw-strong: 700;    /* headings, figures */
  --fw-heavy: 800;     /* the page title and the number in a stat tile — nothing else */

  /* ---- Rhythm, by role ---------------------------------------------------
     Names for the steps above, so a rule says what it is spacing rather than
     how many pixels. A card that wants to be roomier changes one line here
     and every card follows. */
  --pad-card: var(--space-4);
  --pad-card-lg: var(--space-6);
  --pad-row: var(--space-3) var(--space-4);
  --pad-control: 0 var(--space-3);
  --gap-inline: var(--space-2);
  --gap-stack: var(--space-3);
  --gap-section: var(--space-6);

  /* ---- Shape, by role ----------------------------------------------------
     Eight radius steps were being chosen by eye, 39 distinct values in one
     stylesheet. A corner belongs to the KIND of box, so there are four. */
  --radius-control: var(--radius-1);
  --radius-card: var(--radius-4);
  --radius-modal: var(--radius-6);
```

Append inside `:root` in `frontend-admin/src/index.css`, directly after the `--sidebar-2` line:

```css
  /* What is written ON the sidebar. It is near-black in both themes, so its
     ink does not flip — and it was fourteen `rgba(255, 255, 255, …)` literals
     because there was no name for it. Opacities are mixed from this. */
  --sidebar-ink: #ffffff;
```

- [ ] **Step 5: Run the stylesheet guards**

Run: `cd frontend-admin && npm run test`
Expected: PASS, 246 + the new tests. `adminStyles.test.ts` still resolves every token.

- [ ] **Step 6: Build all three web apps**

Run: `cd frontend-admin && npm run build && cd ../frontend-customer && npm run build && cd ../frontend-kitchen && npm run build`
Expected: three successful builds. Nothing uses the new tokens yet, so nothing has moved.

- [ ] **Step 7: Capture the "before" set**

With the dev servers up, take the Look-step screenshots and audit counts for every sidebar screen, as OWNER and ADMIN, into the scratchpad directory (not the repo). This is the comparison set for every later task.

- [ ] **Step 8: Commit**

```bash
git add frontend-shared/tokens.css frontend-admin/src/index.css frontend-admin/src/styleBudget.ts frontend-admin/src/styleBudget.test.ts
git commit -m "feat(admin): tokens for weight and rhythm, and a budget that only goes down"
```

---

### Task 2: Shared components

The pieces every screen is made of. Families: `admin`, `page`, `panel`, `data`, `toolbar`, `pagination`, `table`, `modal`, `form`, `field`, `primary`, `secondary`, `status`, `usr`, `empty`, `segmented`, `toggle`, `hint`, `settings`, `insight`, `confirm`, `toast`.

**Files:**
- Modify: `frontend-admin/src/legacy.css` (the rules whose first class is in the families above; the bulk sits in lines 90–3720)
- Modify: `frontend-admin/src/styleBudget.test.ts` (lower those families)
- Modify: `frontend-admin/src/components/StatTiles.tsx`, `PageIntro.tsx` only if a class is renamed — prefer not to

**Interfaces:**
- Consumes: the tokens from Task 1.
- Produces, for Tasks 3–9: `.page-intro` (the one page header), `.usr-stats` / `.usr-stat` (the one stat tile, rendered by `StatTiles`), `.admin-surface` (raised) and `.admin-surface .panel` / inner blocks (flat), `.segmented-tabs` (the one tab style), `.primary-button` / `.secondary-button` / `.ghost-button` / `.icon-button`, `.field`, `.empty-panel`, `.table-skeleton`, `.spinner` with `@keyframes spin`.

- [ ] **Step 1: Lower the budget and watch it fail**

In `styleBudget.test.ts` set each family listed above to `{ spacing: 0, weight: 0, colour: 0 }`, except `admin`, whose `colour` stays at its baseline until Step 6 (the sidebar).

Run: `npx vitest run src/styleBudget.test.ts`
Expected: FAIL on each of those families, each reporting its current count.

- [ ] **Step 2: Spacing and weight, family by family**

For each family, apply the snap table to every `padding`, `gap` and `font-weight` in its rules. Do it by hand, rule by rule; do not reformat. Two worked examples, both in `legacy.css`:

```css
/* before */
.admin-surface,
.panel,
.login-card,
.modal-card {
  padding: 16px;
  border-radius: var(--radius-lg);
/* after */
.admin-surface,
.panel,
.login-card,
.modal-card {
  padding: var(--pad-card);
  border-radius: var(--radius-card);
```

```css
/* before */
.page-intro h1,
.login-card h1 {
  font-size: var(--fs-display-sm);
  font-weight: 800;
/* after — the selector group is untouched; a test matches it as text */
.page-intro h1,
.login-card h1 {
  font-size: var(--fs-display-sm);
  font-weight: var(--fw-heavy);
```

Then demote weight by role: `.admin-surface h2, .panel h2, .modal-card h2` → `var(--fw-strong)`; nav links, buttons, table headers, form labels → `var(--fw-medium)`; table cells, descriptions, hints → `var(--fw-regular)`. `--fw-heavy` remains only on `.page-intro h1` and the stat figure.

- [ ] **Step 3: One elevation rule**

`.admin-surface` keeps `box-shadow: var(--shadow-md)` and its border. Anything nested inside it is flat. Add after the `.admin-surface, .panel, .login-card, .modal-card` rule:

```css
/* A block inside a surface is flat. The surface is the raised thing; a table
   or a panel inside it that is ALSO bordered and shadowed reads as three
   nested boxes, which is what every list page looked like. */
.admin-surface .panel,
.admin-surface .admin-table-wrap,
.admin-surface .admin-surface {
  border: 0;
  box-shadow: none;
  padding: 0;
  background: transparent;
}
```

Confirm the wrapper class name around `ResponsiveTable` in `src/components/ResponsiveTable.tsx` before writing this; use the class it actually renders.

- [ ] **Step 4: The table**

In the `.admin-table` rules: rows `min-height`/cell padding to `var(--pad-row)`; header cells `font-size: var(--fs-tiny)`, `font-weight: var(--fw-medium)`, `letter-spacing: 0.06em`, uppercase, `position: sticky; top: 0`, background `var(--card)`; body cells `font-size: var(--fs-label)`, `font-weight: var(--fw-regular)`; row divider `border-bottom: 1px solid var(--border)`; hover `background: var(--row-hover)`. Leave `.admin-table th, .admin-table td` and `.admin-table .admin-table__cell--right` selectors byte-identical.

- [ ] **Step 4b: Tiles, buttons, toolbar, forms, modal, empty state**

Stat tile row — replace the `.usr-stats` layout so the row always fills the width instead of stopping at 60%:

```css
.usr-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--gap-stack);
}
```

The figure inside `.usr-stat` is `font-size: var(--fs-title)`, `font-weight: var(--fw-heavy)`, `font-variant-numeric: tabular-nums`; its label `var(--fs-tiny)` uppercase `var(--fw-medium)`; its hint `var(--fs-caption)` `var(--hint)`.

Buttons — `.primary-button` and `.secondary-button` share `min-height: var(--control-h)`, `padding: var(--pad-control)`, `border-radius: var(--radius-control)`, `font-weight: var(--fw-medium)`. Add the two variants screens currently improvise:

```css
/* No fill and no border until hovered: for the third action in a row, where
   a second outlined button would compete with the first. */
.ghost-button {
  display: inline-flex;
  align-items: center;
  gap: var(--gap-inline);
  min-height: var(--control-h);
  padding: var(--pad-control);
  border-radius: var(--radius-control);
  color: var(--muted);
  font-weight: var(--fw-medium);
  transition: var(--dur-fast) var(--ease-out);
}

.ghost-button:hover:not(:disabled) {
  background: var(--row-hover);
  color: var(--text);
}

/* A square button holding one icon — the row actions in a table. */
.icon-button {
  display: inline-grid;
  place-items: center;
  width: var(--control-h-sm);
  height: var(--control-h-sm);
  border: 1px solid var(--border);
  border-radius: var(--radius-control);
  color: var(--muted);
  transition: var(--dur-fast) var(--ease-out);
}

.icon-button:hover:not(:disabled) {
  background: var(--row-hover);
  color: var(--text);
}
```

Toolbar — `.data-toolbar` children share one height (`var(--control-h)`) and `gap: var(--gap-stack)`; the count (`.toolbar-meta`) is `var(--fw-medium)`.

Forms — `.field` is label (`var(--fs-label)`, `var(--fw-medium)`), control (`min-height: var(--control-h)`, `border-radius: var(--radius-control)`), hint (`var(--fs-caption)`, `var(--hint)`); `.form-grid` gap is `var(--space-4)`.

Modal — `.modal-card` uses `border-radius: var(--radius-modal)`, `padding: var(--pad-card-lg)`, `box-shadow: var(--shadow-xl)`; `.modal-actions` is right-aligned with `gap: var(--gap-stack)`.

Empty state — `.empty-panel` is centred, `padding: var(--space-10) var(--space-6)`, title `var(--fw-strong)`, copy `var(--hint)`; no gradient wash behind it.

- [ ] **Step 5: One spinner, one skeleton**

Add once, near the first `@keyframes`:

```css
/* The one spinner. There were four — comboStatusSpin, reportsSpin,
   ai-sug-spin, bp-spin — identical but for the name. */
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
```

Leave the four old keyframes in place for now; Tasks 3, 7, 8 and 9 re-point their own family at `spin` and delete their copy. (Deleting them here would touch families this task does not own.)

- [ ] **Step 6: The sidebar's ink**

Replace each `rgba(255, 255, 255, A)` in the `.admin-sidebar*` rules with `color-mix(in srgb, var(--sidebar-ink) P%, transparent)` where P = A × 100, each bare `#fff` with `var(--sidebar-ink)`, the two gradient stops `#171a2f`/`#101221` with `var(--sidebar-2)`/`var(--sidebar)`, and `rgba(255, 82, 0, 0.16)` with `color-mix(in srgb, var(--primary) 16%, transparent)`. Then set `admin.colour` to 0 in the budget.

- [ ] **Step 7: Run tests**

Run: `npm run test`
Expected: PASS. If `adminStyles.test.ts` fails, a selector's text was changed — restore it.

- [ ] **Step 8: Build all three and Look**

Run the three builds from Task 1 Step 6. Then the Look step on Orders, Menu Items, Users and Kitchen Staff (they are made almost entirely of shared components), both themes, both widths, both roles.

- [ ] **Step 9: Commit**

```bash
git add frontend-admin/src
git commit -m "style(admin): shared components on one rhythm, one weight scale, one elevation"
```

---

### Tasks 3–9: one per screen batch

Every batch task has the same eight steps. The table gives what differs.

| Task | Screens | Files (`src/pages/…`, `src/components/…`) | Families to zero | Bespoke work |
|---|---|---|---|---|
| 3 | Login, shell, Dashboard, Reports | `LoginPage`, `DashboardPage`, `ReportsPage`, `Sidebar`, `AnimatedCharts` | `lg`, `login`, `dashboard`, `rpt`, `mobile`, `workspace` | Dashboard and Reports adopt `PageIntro` and `StatTiles`; `rpt-btn` → shared buttons; `rpt-seg` → `segmented-tabs`; `reportsSpin` → `spin`; chart axis text and grid lines on tokens |
| 4 | Orders, Order detail | `OrdersPage`, `OrderDetailPage`, `DeliveryPanel` | `order` | Timeline spacing; totals block right-aligned tabular numerals; long customer names and addresses truncate with a title |
| 5 | Menu Items, Menu item editor | `MenuItemsPage`, `MenuItemEditorPage`, `MenuItemCustomizationEditor`, `RestaurantMenuTable`, `GstPriceSwitch` | `menu`, `branch`, `gst` | Nested size → group → option blocks get one indent step and flat inner cards; the editor's `$` price labels use the restaurant's currency via `useMoney` only if already imported there — otherwise leave |
| 6 | Restaurants, Restaurant detail, Locations, Branch detail | `AdminRestaurantsPage`, `RestaurantDetailPage`, `LocationsPage`, `LocationDetailPage`, `CapabilitiesPanel`, `PaymentSettingsPanel` | `restaurant`, `slot`, `capability`, `location`, `payment` | The long forms get section headings from existing hint text (no fields move); the hero metric cards become the shared stat tile |
| 7 | Offers, Combo suggestions, Marketing, Campaign editor, Campaign detail, Channels | `OffersPage`, `GeneratedCombosPage`, `MarketingPage`, `CampaignEditorPage`, `CampaignDetailPage`, `ChannelsPage`, `components/marketing/*`, `RestaurantOffersManager` | `offer`, `combo`, `generated`, `hub`, `mkt` | `--mkt-shadow-1` → shadow ladder; `mkt-shimmer`/`hub-shimmer` → the shared skeleton; `comboStatusSpin` → `spin`; the six-step builder keeps its layout |
| 8 | Kitchen Staff, Users, Taste questions, Storefront content, Branding | `KitchenStaffPage`, `AdminUsersPage`, `PreferencesPage`, `WebsitePage`, `BrandingPage`, `BrandingPanel` | `pref`, `web`, `bp`, `ph` | `pref-pulse` → skeleton; `bp-spin` → `spin`; the phone preview's `--p`/`--ink` inline tokens are set from JS and are NOT literals to replace |
| 9 | AI Manager, AI Logs, Notifications, Display settings, Storefront apps | `AIManagerPage`, `AILogsPage`, `NotificationsPage`, `SettingsPage`, `TenantsPage`, `components/ai/*`, `TenantSwitcher` | `ai`, `ntf`, `set`, `st`, `tenant` | `ai-sug-spin` → `spin`; chat bubbles keep their shape, only rhythm and colour move |

**Interfaces (every batch):**
- Consumes: the tokens from Task 1 and the shared classes from Task 2, by the names listed there.
- Produces: nothing later tasks depend on. Batches are independent and may run in any order after Task 2.

For each of Tasks 3–9:

- [ ] **Step 1: Lower the budget.** In `styleBudget.test.ts`, set the task's families to `{ spacing: 0, weight: 0, colour: 0 }`.

  Run: `npx vitest run src/styleBudget.test.ts`
  Expected: FAIL for each family, reporting its count.

- [ ] **Step 2: Spacing and weight.** Apply the snap table to every `padding`, `gap` and `font-weight` in the task's families, rule by rule, with the weight roles from Task 2 Step 2.

- [ ] **Step 3: Colour.** Replace each hex, `rgba()` and gradient literal in those families using the colour rule in the snap-table section. A gradient that is decoration (not the primary button or active nav) becomes a flat token.

- [ ] **Step 4: Adopt the shared components.** Where the "Bespoke work" column says a screen adopts `PageIntro`, `StatTiles`, `segmented-tabs` or the shared buttons, change the markup in the page file to render the shared component with the SAME text, values, handlers and order, then delete the family's now-unused rules. Worked example, `ReportsPage.tsx`:

  ```tsx
  // before
  <header className="rpt-header">
    <div className="rpt-header__copy">
      <h1>Restaurant reports</h1>
      <p>{subtitle}</p>
    </div>
    <div className="rpt-header__actions">{actions}</div>
  </header>
  // after
  <PageIntro
    eyebrow="Reports"
    title="Restaurant reports"
    description={subtitle}
    actions={actions}
  />
  ```

  Keep the existing title and description strings exactly; read them from the file, do not retype from this example.

- [ ] **Step 5: Bespoke work.** Do the items in the task's "Bespoke work" column.

- [ ] **Step 6: Run tests and build.**

  Run: `npm run test && npm run build`
  Expected: PASS, and the budget test now passes at zero for the task's families.

- [ ] **Step 7: Look.** The Look step on every screen in the batch.

- [ ] **Step 8: Commit.**

  ```bash
  git add frontend-admin/src
  git commit -m "style(admin): <batch screens> on the shared rhythm and components"
  ```

---

### Task 10: Close out

**Files:**
- Modify: `frontend-admin/src/legacy.css` (delete dead keyframes and rules)
- Modify: `frontend-admin/src/index.css` (radius aliases)
- Modify: `CLAUDE.md` (the token paragraph), `.claude/worklog.md` (entry)

- [ ] **Step 1: Delete what nothing uses.** For each of `comboStatusSpin`, `reportsSpin`, `ai-sug-spin`, `bp-spin`, `pref-pulse`, `mkt-shimmer`, `hub-shimmer`: `grep -n "<name>" src/legacy.css`; if only the `@keyframes` line remains, delete the block.

- [ ] **Step 2: One radius family.** `grep -c "var(--radius-sm)\|var(--radius-md)\|var(--radius-lg)\|var(--radius-xl)" src/legacy.css` must be 0 after replacing each with its role token (`--radius-control`, `--radius-card`, `--radius-modal`). Leave the four aliases defined in `index.css`.

- [ ] **Step 3: Whole-panel check.** `npm run test && npm run build && npm run lint`. Lint is compared against the pre-existing error count (~55), not zero. Then the Look step across all 27 screens once more, both roles, both themes, against the Task 1 "before" set.

- [ ] **Step 4: Record it.** In `CLAUDE.md`, extend the "Know which file owns which token" paragraph with one sentence: weight (`--fw-*`), role spacing (`--pad-*`, `--gap-*`) and role radius live in `frontend-shared/tokens.css`, and `styleBudget.test.ts` is a ratchet whose numbers may only be lowered. Append a dated entry to `.claude/worklog.md`.

- [ ] **Step 5: Commit.**

  ```bash
  git add frontend-admin/src CLAUDE.md .claude/worklog.md
  git commit -m "style(admin): remove the duplicates the refresh left behind"
  ```
