# Redesign plan — storefront and admin

Branch: `redesign`, cut from `V2` at `4e91e61`.
Scope agreed: **customer storefront + admin dashboard**, layouts reworked, not
just repainted. Kitchen board and mobile app are out.

---

## 1. What this is actually for

Not a food-delivery marketplace. Three real restaurants in Surat, each on their
own address, selling to people who live nearby:

| | |
|---|---|
| Bhagwati Bakery | Katargam, trading since 1999, 120 items |
| Famous Fast Food | Dabholi Char Rasta, 4.0 from 276 ratings |
| Famous Chinese Cuisine | Nanavat Main Road, 4.6 from 699 ratings |

**Audience**: someone in the same city, on a phone, who either already knows the
shop or is deciding whether to trust it.
**Job**: make a repeat order fast, and make a first order feel safe.

That is a different product from a marketplace, and the design should stop
looking like one.

## 2. The three constraints that decide everything

These are not preferences. They are properties of the system, and each one
removes a tool most food-app designs lean on.

**The accent colour belongs to the tenant.** Twelve presets plus a custom hex,
written onto the root element at runtime by `applyBrandColor`. A design whose
warmth comes from orange breaks for the Teal, Indigo, Forest and Slate
restaurants. So warmth has to live in the neutrals and the spacing.

**The typeface belongs to the tenant too.** Four body faces (Manrope, Inter,
Plus Jakarta Sans, Space Grotesk) plus DM Serif Display for headings only. So
personality cannot come from one chosen face either. It has to come from the
scale, the weights and the alignment, which hold across all five.

**The photography is weak, and will stay weak.** Bhagwati's dishes are mostly
Google thumbnails. Famous Chinese has none at all. Famous Fast Food wears a
stock photo of somebody else's table. Every competitor in this category is
built on big, beautiful food photography, and we do not have it. A design that
depends on it will look worse here, not better.

So: colour varies, type varies, photography is poor. **What is left to design
with is structure, type scale, and the menu itself** — which is the one thing
all three restaurants have in abundance.

## 3. The concept: the counter, not the catalogue

The menu is the product. Treat it as the hero, and treat the shop's own facts
as the frame around it.

Two things carry the identity, and both are specific to this market rather than
borrowed from a design trend:

**The veg mark becomes a first-class element.** The green and brown squares on
Indian packaging are a legally mandated system every customer here reads
instantly, and we already store `is_veg` on every item. Most clones shrink it to
a 10px icon. We make it the repeating structural unit that leads every row —
the thing that gives a long menu rhythm without a single hairline rule.

**Price is set with confidence.** These are ₹20 to ₹350 items. Price is the
information people are scanning for, not something to apologise for in grey
10px. Tabular numerals, aligned, readable at a glance.

## 4. Tokens

### Colour

The neutral is a pale green-grey rather than the warm cream that every generated
page reaches for. It is pulled from the veg mark, so it is the one colour this
product can claim honestly, and at this saturation it sits under all twelve
tenant accents without arguing with any of them.

| Token | Light | Dark | Role |
|---|---|---|---|
| `--paper` | `#F2F5F0` | `#121511` | the page |
| `--surface` | `#FFFFFF` | `#1A1E19` | anything raised off it |
| `--ink` | `#161A14` | `#F2F5F0` | primary text |
| `--ink-soft` | `#5B6356` | `#A8B0A3` | secondary text, measured to 4.5:1 on both |
| `--rule` | `#DCE2D8` | `#2B3129` | the few borders that survive |
| `--veg` | `#1F7A3D` | `#4FB873` | fixed, never themed |
| `--non-veg` | `#9A2A1F` | `#D4675A` | fixed, never themed |

The tenant accent keeps its existing token names and gains **one rule**: it is
only ever used for something you can act on. Buttons, active states, focus,
the item count on the cart. Never a background wash, never a heading, never a
divider. That single discipline is what makes twelve accents look deliberate
instead of twelve different websites.

### Type

Scale and weight do the work, because the face does not hold still. Ratio 1.25,
with a deliberately large jump between a dish name and its description so the
menu scans at arm's length.

```
--t-price   18px / 600 / tabular-nums
--t-name    17px / 600
--t-body    15px / 400 / 1.55
--t-meta    13px / 400
--t-section 22px / 700
--t-page    clamp(30px, 5vw, 44px) / 700
```

Rules that hold across all five faces: body copy never exceeds 68 characters;
every number that represents money uses tabular numerals; DM Serif Display only
ever sets `--t-page` and `--t-section`, never body.

### Motion

One orchestrated moment per screen, not an effect on every element. The brand
page already has its moment, the figures counting up. The menu gets none at
all — it has to stay fast, and that is a decision I had to make twice already.
`prefers-reduced-motion` is honoured throughout, as it is today.

## 5. Layouts

### Brand page — asymmetric, with the shop pinned

The facts stay visible while the story scrolls past them. On a phone the rail
collapses into a compact header.

```
┌──────────────────────────────────────────────────────┐
│ ◉ Bhagwati Bakery         Menu   About   Orders   🛍3 │
├────────────────────┬─────────────────────────────────┤
│                    │                                 │
│   BHAGWATI         │  Since 1999, on the corner      │
│   BAKERY           │  at Katargam.                   │
│                    │                                 │
│   Since 1999       │  [ 60ch of the owner's words ]  │
│   4.6  699 ratings │                                 │
│   Katargam, Surat  │  What people come for           │
│   12–2 · 6–11      │    Khari biscuit                │
│                    │    Butter toast                 │
│   [ Order now ]    │    Nankhatai                    │
│                    │                                 │
│   ↑ sticky         │  A few things on the menu       │
│                    │    ▢ Khari              ₹40     │
│                    │    ▢ Butter toast       ₹60     │
└────────────────────┴─────────────────────────────────┘
```

### Menu — dense rows, two columns, image optional

This is the biggest change and it solves two problems at once. 187 photo cards
is both the thing that made scrolling expensive and the thing that shows off our
worst asset. Rows are cheaper to paint, read faster, and degrade gracefully when
a dish has no photo — which is most of them.

```
┌──────────────────────────────────────────────────────┐
│  Bhagwati Bakery                    [ search ]   🛍3  │
│  Namkeen   Breads   Cookies   Farsan   Sweets        │
├──────────────────────────────────────────────────────┤
│  Namkeen & Sev                             14 items  │
│                                                      │
│  ▢ Sev Mamra            ▢ Chana Jor                  │
│    Light, salted  ₹40     Spiced, crisp  ₹50         │
│                                                      │
│  ▢ Bhavnagari Gathiya   ▣ Chicken Roll               │
│    —              ₹60     —              ₹180        │
└──────────────────────────────────────────────────────┘
```

A photo appears as a small square on the right of a row when the dish has a real
one, and is simply absent when it does not. No placeholder tile pretending to be
a photograph.

### Checkout

Already split into steps, so this is layout discipline rather than restructure:
the summary becomes the anchor on desktop, the card nesting drops by a level,
and the step heads stop competing with the field labels.

### Admin — one scope bar, denser tables

The panel's problem is not its finish, it is that every screen invents its own
restaurant picker and wraps everything in a card. Rework:

- **One persistent scope bar**: which restaurant, which branch, for the whole
  session. Replaces the separate pickers on AI Manager, Marketing, Kitchen Staff
  and Reports.
- **Tables lose their card wrapper** and gain density. They are the content.
- **The dashboard stops landing empty.** It currently shows zeros and "Not
  refreshed yet" until you press a button, and it is the first screen anyone
  sees in a demo.

## 6. Admin: no Tailwind, and why

There is a documented path for adding Tailwind to the admin safely, using layers
so its reset cannot touch the existing 15,000 lines. I do not think we should
take it.

The admin already has the design system the storefront lacked: a ten-step type
scale with 517 uses, a radius ladder with 269, a shadow ladder, inset tokens,
control heights, and badge inks that were each measured to 4.5:1. What this
redesign needs there is **layout** work — grid and flex changes in CSS that
already exists. Utility classes do not help with that, and the no-dependency
rule has survived every previous temptation with one documented exception.

So the admin is reworked in its own hand-written CSS. Vengeance UI components
cannot go there, and should not.

## 7. What must not break

Each of these is a guard that exists because something was wrong once.

| Guard | Protects |
|---|---|
| `e2e/mobile-layout.spec.ts` | 44px touch targets, no horizontal overflow at 393px |
| `e2e/scroll-lock.spec.ts` | `body { overflow: hidden }` under a dialog |
| `e2e/charges-breakdown.spec.ts` | the bill adds up and nothing clips it |
| `e2e/menu-rail.spec.ts` | the category rail tracks the scroll |
| `adminStyles.test.ts` | literal selector text — **never run a formatter over `legacy.css`** |
| `src/lib/fonts.test.ts` | a display serif never becomes the body face |
| `dish-motif.test.ts` | a dish keeps the same placeholder tile between visits |

Three more that no test covers:

- **`src/lib/stripe-appearance.ts` restates the palette** for the Stripe iframe,
  which cannot see our tokens. Any colour change must be mirrored there or the
  card form drifts out of the design silently.
- **Menu scroll performance.** `memo(DishCard)`, the cached section offsets and
  the absence of global smooth scrolling were all measured fixes. The row layout
  should improve on them; it must not regress them.
- **`polish.css` has no `overflow: hidden` on the order summary** any more, and
  must not get one back.

## 8. Things I deliberately rejected

Written down so they do not get reinvented later.

- **A warm cream page with a serif display and a terracotta accent.** It is the
  house style of generated design right now, and our default accent is already
  near that terracotta, so the whole thing would read as a template.
- **Hairline rules and zero radius, newspaper style.** Tempting for a menu, and
  it would have made the veg mark redundant.
- **A card for every piece of content.** That is most of what the current
  storefront does and it is why nothing on it has hierarchy.
- **All-caps eyebrow labels.** The storefront uses `.eyebrow` on nearly every
  section. They are decoration pretending to be structure, and they go.
- **Arrows appended to link text.** `See the full menu →` and friends.
- **Big hero food photography.** We do not have the photographs, and designing
  for photographs we do not have is how the current brand page ended up wearing
  a stock picture of someone else's lunch.

## 9. Order of work

Commercially, not alphabetically. Each step ships on its own and keeps the
suite green.

1. **Tokens** in `frontend-shared/tokens.css`, plus the accent discipline rule.
   Nothing visual yet; everything downstream depends on it.
2. **Menu page** — the row layout. Biggest win, biggest risk, do it while fresh.
3. **Brand page** — the asymmetric rail.
4. **Dish detail and cart.**
5. **Checkout**, presentation only. The payment call, half-and-half pricing and
   slot validation are not touched.
6. **Admin scope bar and table density.**
7. **Admin dashboard**, so it lands with data.

Verification after each: `npm run build` and `npm run test` in both apps, the
Playwright specs listed above, and a walk at 393px and desktop in both themes.
