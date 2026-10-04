# Admin panel visual refresh — design

Date: 2026-10-04. Scope: `frontend-admin/` only.

## What was asked for

Hitesh, preparing a client demo: "redesign and improve the full admin panel,
using a plan, each screen". Clarified in conversation:

- **Goal — looks premium.** Visual quality only.
- **Direction — refine what is there.** Keep the identity: dark and light
  themes, the orange accent, Plus Jakarta Sans. No screen should become
  unfamiliar.
- **Method — foundation first, then screen by screen**, in demo order, one
  commit per batch.

Assumption (mine, not stated): all 27 screens are in scope, for both ADMIN and
OWNER, at desktop and at phone width.

## What does not change

- What any screen does, what it is called, and where anything lives.
  Navigation, routes, tabs, forms and their fields stay as they are.
- The backend, the API contract, and the other three clients.
- Dependencies. `frontend-admin` stays dependency-free at runtime (CLAUDE.md);
  nothing is added.
- The CSS architecture: `tokens.css` → `components.css` → `legacy.css` in its
  named layer → utilities. No rewrite onto utilities, no formatter over
  `legacy.css` (`adminStyles.test.ts` matches selector text literally).

## What is wrong today

Measured in `legacy.css` (15,066 lines) and seen on the running panel.

**The scales that exist are used; the ones that do not are improvised.**

| Property | Uses | Distinct values | On a token |
|---|---|---|---|
| font-size | 533 | 15 | 528 |
| border-radius | 342 | 39 | 311 |
| box-shadow | 124 | 26 | 112 |
| transition | 86 | 36 | 83 |
| **padding** | 336 | **153** | **10** |
| **gap** | 607 | **57** | **20** |
| **font-weight** | 312 | 8 | **0** |

Type, radius, shadow and motion are in good shape. **Spacing is the problem**:
`--space-*` exists and is used 22 times against ~940 spacing declarations, so
every card, row and toolbar has its own rhythm (`10px`, `12px`, `14px`, `5px`,
`12px 14px`, `14px 16px`…). This is the main reason screens that share
components still do not look like one product.

**Radius has two families** in use at once (`--radius-1..8` and
`--radius-sm/md/lg`), 39 distinct values in all.

**Weight is heavy and unranked.** 700 and 800 account for 233 of 312
declarations; 650, 750 and 900 also appear. When most text is bold, nothing
is.

**Colour still escapes the tokens**: 119 hex literals, 156 `rgba()` calls and
44 gradients in `legacy.css`.

**Each feature invented its own surfaces.** Class prefixes `mkt-` (317
rules), `ai-` (307), `rpt-` (141), `ph-` (118), `hub-` (117), `dashboard-`
(99) each define their own card, tile, tab and loading state. There are 15
keyframes, of which four are spinners and four are shimmers for the same two
ideas.

**Seen on screen** (owner login, dark theme, 1568px):

1. *Three page headers.* Dashboard has a title and no eyebrow; Orders has an
   eyebrow, a title and a description; Reports puts actions beside a
   differently sized title. Refresh is a different button on each.
2. *Three stat tiles.* Dashboard: large, icon top-right. Orders/Offers: small,
   icon left, and the row stops at about 60% of the width. Reports: a third
   size with tinted icon chips.
3. *Two tab styles.* Pill tabs on the branch page, a segmented bar on Reports.
4. *Cards inside cards.* A table sits in a bordered panel inside a bordered
   surface, so lists read as three nested boxes.
5. *Small, crowded text.* Table rows and tile captions sit at the bottom of
   the type scale with tight line height.
6. *Empty states and loading states differ* from screen to screen.

## The design

### 1. Foundation — tokens

All in `frontend-shared/tokens.css` and `frontend-admin/src/index.css`.
Additive; no existing token changes value unless listed here.

- **Spacing.** Adopt the existing `--space-*` scale (4px base) as the only
  source for `padding` and `gap`. Add semantic aliases so intent is readable:
  `--pad-card`, `--pad-card-lg`, `--pad-row`, `--pad-control`, `--gap-stack`,
  `--gap-inline`, `--gap-section`. Off-scale values (`5px`, `14px`, `10px`)
  snap to the nearest step.
- **Radius.** One family. `--radius-sm/md/lg` become aliases of the numbered
  steps and stop being used directly. Four roles: control, card, modal, pill.
- **Weight.** Four tokens — `--fw-regular` 500, `--fw-medium` 600,
  `--fw-strong` 700, `--fw-heavy` 800 — with a rule for each: body 500, labels
  and table cells 600, headings and figures 700, 800 reserved for the page
  title and the big number in a stat tile. 650/750/900 go.
- **Elevation.** Three levels with a stated use: flat (bordered, no shadow) for
  anything inside a surface; raised for the surface itself; overlay for modals
  and menus. Fixes cards-inside-cards: an inner block is never bordered AND
  shadowed.
- **Colour.** Remaining hex, `rgba()` and gradient literals move to tokens or
  `color-mix()` off tokens, so both themes are driven from one place. Brand
  gradients are kept only where they are the accent (primary button, active
  nav item).

### 2. Foundation — shared components

One definition each, in `frontend-shared/components.css` where both web apps
share it and in `legacy.css` where it is the panel's own. Feature-prefixed
copies are re-pointed at these rather than restyled individually.

| Component | Decision |
|---|---|
| Page header (`PageIntro`) | One layout: eyebrow, title, one-line description, actions right. Every screen uses it, including Dashboard and Reports. |
| Stat tiles (`StatTiles`) | One tile: label, figure, caption, icon chip. Row always fills the width (auto-fit grid). Selected state for the filtering tiles. |
| Surface / card | `admin-surface` is the one raised block. Blocks inside it are flat. |
| Table (`ResponsiveTable`) | Sits directly in the surface, no inner box. Sticky header, 48px rows, hairline dividers, right-aligned tabular numerals, row hover. |
| Toolbar (`DataToolbar`) | Search, filters, count and primary action on one baseline, one control height. |
| Tabs | One style (the pill tabs), used by Reports too. |
| Buttons | Three: primary, secondary, ghost; one height per size; icon-only variant for row actions. |
| Forms | One field: label, control, hint, error. One control height. Checkbox rows aligned. Section headings inside long forms. |
| Status pill (`StatusPill`) | Unchanged in meaning; one size, the measured inks kept. |
| Modal / confirm | One header, body, footer layout; actions right. |
| Empty / error / loading | One empty state, one error panel, one skeleton, one spinner. |
| Sidebar | Section labels, active state and the account block tightened; no structural change. |

### 3. Screens

After the foundation, each screen gets a pass for what is bespoke to it:
charts on Dashboard and Reports, the order timeline, the menu editor's nested
size and customization blocks, the long branch and restaurant forms, the
marketing builder, the AI Manager chat, the branding phone preview.

Batches, in demo order:

| Batch | Screens |
|---|---|
| 0 | Foundation: tokens and shared components |
| 1 | Login, sidebar and shell, Dashboard, Reports |
| 2 | Orders, Order detail |
| 3 | Menu Items, Menu item editor |
| 4 | Restaurants, Restaurant detail, Locations, Branch detail |
| 5 | Offers, Combo suggestions, Marketing, Campaign editor, Campaign detail, Channels |
| 6 | Kitchen Staff, Users, Taste questions, Storefront content, Branding |
| 7 | AI Manager, AI Logs, Notifications, Display settings, Storefront apps |

## Guardrails

From CLAUDE.md and the existing suites; each has broken something before.

- `adminStyles.test.ts` asserts on literal selector text including line
  breaks, and that every `var(--x)` in `legacy.css` resolves. No formatter;
  no token deleted without an alias left behind.
- Badge tones stay doubled (`.status-pill.status-pill--success`).
- The unlayered-beats-layered cascade in `index.css` is load-bearing.
- `frontend-shared/` is also imported by the storefront and the kitchen
  board. A change to a shared class is checked in those two as well; a token
  is only added, never re-valued, without looking at all three.
- Tenant colour is written at runtime in the storefront; nothing here may
  assume a warm accent in shared CSS.
- A disabled button still says why. Touch targets stay at 44px on phone
  width.

## How each batch is verified

1. Screenshots of every screen in the batch before and after, dark and light,
   at 1440px and 390px.
2. `scripts/audit-pages.js` before and after (rendered contrast, touch-target
   size, overflow, numeric alignment); no new failures.
3. `npm run test` (246 today, including `adminStyles.test.ts`) and
   `npm run build`.
4. For batch 0 and any change under `frontend-shared/`: `npm run build` in
   `frontend-customer` and `frontend-kitchen` too.
5. Walk the batch as OWNER and as ADMIN.
6. One commit per batch.

## Success

- Padding and gap on tokens for the shared components and every screen
  touched; no off-scale spacing left in them.
- One page header, one stat tile, one table, one tab style, one empty state
  across all 27 screens.
- No hex or `rgba()` literal left in the rules a batch touches.
- Both themes correct on every screen, no white bands or unreadable text.
- No behaviour change: the same tests pass, and no screen gains, loses or
  moves a control.

## Out of scope

Navigation or information-architecture changes, new features, the storefront,
the kitchen board and the mobile app, new dependencies, and a utility-class
rewrite of `legacy.css`.
