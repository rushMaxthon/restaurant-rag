# Customer Storefront — Photo-Led Visual Redesign

**Status:** approved in conversation, 2026-09-13
**Surface:** `frontend-customer` only
**Builds on:** the typography and token work of `2026-09-13-customer-typography-and-tokens.md`

---

## Why

The storefront is not unattractive because it lacks decoration. It is unattractive
because every dish card is half grey box. Eight identical placeholder rectangles
with a generic bag icon, on a flat dark surface, with no motion anywhere.

The previous pass chose "fast and utilitarian" and stripped decoration. That was
the wrong medicine for this patient: utilitarian works when photography does the
selling, and here nothing was. This redesign chooses **clean and confident** —
the Deliveroo/Uber Eats register — where photography carries the page and
restraint reads as premium rather than as absence.

Three of the changes below explicitly reverse decisions made in the previous
pass. They are marked. They are not mistakes being hidden; they are a different
brief producing a different answer.

## What this is not

- Not a colour redesign. Colour belongs to the tenant (see Constraints).
- Not a rebuild of the CSS architecture. That was considered and rejected as too
  much unreviewable surface for a 27-test suite.
- Not an upload pipeline. See "Product gap" below.

---

## Constraints

These bind every decision in this document.

**Zero runtime dependencies.** `frontend-customer` ships exactly `react` and
`react-dom`. No Framer Motion, no GSAP, no UI kit. All motion is CSS transitions,
keyframes, and native `IntersectionObserver`. Test tooling in `devDependencies`
is fine.

**Colour is the tenant's, not ours.** One brand colour per restaurant is
hue-rotated into the entire palette across 12 presets, in light and dark, by
`src/theme/palette.ts`. A design that only looks right in the default orange is
a defect. Beauty must come from photography, space, type and motion.

**44px minimum touch targets.** Density is bought from spacing, never from hit
areas.

**Only `transform` and `opacity` are animated.** Both are compositor properties.
Animating `height`, `top` or `width` causes layout thrash and is what makes a
page feel cheap on the mid-range Android hardware most of these users are on.

**`prefers-reduced-motion` is honoured globally**, by one blanket rule rather
than per-component opt-in.

**Comments explain why, not what** — matching `backend/app/config/settings.py`,
which states the measurement or incident behind each decision.

---

## How images actually work

Established by reading the code, and it shapes everything:

- The admin menu editor has a plain **text input** labelled "Image URL"
  (`placeholder="https://..."`). An owner pastes a link.
- It is stored as `varchar(500)` and the customer app hotlinks it directly:
  `src={item.image_url}`.
- **There is no upload pipeline anywhere in the codebase** — no `UploadFile`, no
  `FormData`, no presigned URLs, no object storage. Confirmed by search across
  `backend/app`, `frontend-admin/src` and `frontend-customer/src`.

Four consequences, all of which the design must absorb:

1. **Broken images are a lifecycle, not an edge case.** Hotlinked URLs rot: the
   source reorganises, expires the file, or starts blocking hotlinking. A
   percentage of dishes will end up permanently in the fallback state. It is
   therefore a first-class designed state.
2. **No control over dimensions or weight.** A 5MB 4000px PNG and a 90px
   thumbnail are both valid inputs. A fixed `aspect-ratio` box with
   `object-fit: cover` is mandatory, not stylistic.
3. **No blur-up, no `srcset`, no WebP.** All require controlling the asset. A
   reserved box plus a skeleton cross-fade is the best available technique.
4. **Mixed aspect ratios are guaranteed** in a single grid.

### Product gap (out of scope, recorded)

Requiring owners to self-host images means most restaurant owners cannot add one
at all. This is the likeliest reason the seed data has none. A real upload
pipeline — Supabase Storage is already provisioned — would plausibly do more for
perceived quality than this entire redesign. Not proposed here; recorded so the
decision is deliberate.

---

## Section 1 — Imagery

### Three designed states

1. **Photo present.** `aspect-ratio: 4/3` box reserved before load so nothing
   shifts, `loading="lazy"`, `decoding="async"`, `object-fit: cover`. The image
   **cross-fades over the skeleton** rather than replacing it. Today the swap is
   instantaneous and hard; that single transition is a large part of what reads
   as cheap.
2. **No photo.** The branded placeholder from `createPlaceholderImage()` in
   `services/api.ts` — dish initials on a ground tinted from the tenant's
   `--primary`, at 420×260 so it is not crop-scaled. Upgraded with a subtle
   two-tone gradient so a grid of placeholders varies instead of repeating one
   flat swatch. Deterministic from the dish name: the same dish always renders
   the same placeholder.
3. **Photo fails to load.** `onError` falls through to state 2, never a broken
   frame.

**Regression being corrected:** `createPlaceholderImage()` already existed and
was used by `MenuItemCard`. When `MenuItemCard` and `DishCard` were consolidated
into `DishRow`, `DishCard`'s grey-bag fallback was kept and the branded
placeholder was silently dropped. That is why every card currently shows a grey
box — the app already had a better answer than what is on screen.

### Seed data

`seed.py` never sets `image_url`, so a photo-led design cannot be evaluated
against it. Seed dishes get **remote image URLs**, because that mirrors exactly
how production works. Committing local JPEGs was considered and rejected: it
would make the seed behave better than the real app, and the design would be
validated against a fiction.

---

## Section 2 — The dish card

### Grid variant

Image is dominant: a full-width `4/3` box at the top of the card, body beneath.

**On the image, two things only:**
- **Veg / non-veg marker**, top-left, always. A market requirement, not
  decoration; it is never the element dropped for aesthetics.
- **Favourite control**, top-right, on a soft scrim so it survives a light or
  busy photograph.

**Everything else moves to the body.** The New/Popular badge currently competes
with the veg marker for the top-left; it moves beside the category. The existing
"at most one badge" rule is kept — two stacked labels stop being a signal.

**Body:** name (max 2 lines) → meta line `rating · category` → a baseline row
carrying price and the Add control. Internal padding 10px → 14px.

### Reversals of the previous pass — deliberate

- **Card padding and grid gap increase.** The previous pass tightened them for
  density. "Clean and confident" wants air. Density and calm pull in opposite
  directions and this brief chose calm.
- **Minimum column width 190px → 260px.** Fewer dishes per row, each
  substantially larger; roughly 5 across at 1568px instead of 7. A photograph at
  190px is a stamp, not an appetite cue.

### Rejected

- **Price overlaid on the image.** Common in the Swiggy register, but white text
  over arbitrary owner photography is a contrast lottery that cannot be won
  without controlling the asset.
- **Per-image aspect-ratio adaptation.** Every image gets the same `4/3` box.
  A ragged grid reads as broken; a consistent crop reads as intentional.

### Compact variant

Same three image states and the same press feedback. Thumbnail 76px → 88px.
Used in lists, cart lines, and chat suggestion results.

---

## Section 3 — Motion

### Tokens

Defined in `index.css` beside the other tokens; every animation references them,
so the whole feel retunes from one place.

```
--motion-fast: 120ms    press, tap feedback
--motion-base: 200ms    hover, colour, cross-fade
--motion-slow: 320ms    section reveals
--ease-out:   cubic-bezier(0.2, 0, 0, 1)      things arriving
--ease-inout: cubic-bezier(0.4, 0, 0.2, 1)    things moving in place
```

### The complete inventory — four motions

1. **Hover / press.** Card lifts with a softening shadow; the image scales 1.03
   inside its clipped box so the photo breathes while the card stays put; press
   scales to 0.98. Pure CSS.
2. **Section reveal.** Native `IntersectionObserver` adds a class as a section
   enters; CSS fades and rises it ~12px. Grid children stagger at 40ms
   intervals, **capped at 6 children** — an uncapped stagger on a 50-dish grid
   takes two seconds and reads as broken.
3. **Skeleton → content cross-fade.** From Section 1.
4. **Add to cart.** The Add control morphs to the stepper with a quick scale;
   the header cart badge bumps with its new count.

### Rejected: fly-to-cart

The item-flies-into-the-cart animation needs live element coordinates and breaks
when the page scrolls mid-flight, when the cart icon is offscreen on mobile, or
when the item sits in a horizontally-scrolled rail. It is the flashiest option
and the most fragile. The badge bump communicates the same event and cannot
break.

### Reveals must fail visible

The conventional implementation hides elements in CSS and reveals them on
intersect — so if JS fails, the observer never fires, or support is absent, the
page is **permanently blank**. Elements are therefore visible by default, and a
`js-motion` class set on `<html>` at boot opts into the hidden-then-revealed
behaviour. No JS, no observer, no support renders plain visible content.

### Reduced motion

One global rule, so a forgotten component cannot break the promise:

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 1ms !important;
    transition-duration: 1ms !important;
    scroll-behavior: auto !important;
  }
}
```

### Testing

Meaningfully testable: that motion tokens resolve (the existing token guard
covers it), and that the reveal hook adds and removes its class correctly
against a mocked `IntersectionObserver`. Tests asserting a transition "looks
smooth" pass regardless of the code and will not be written.

---

## Section 4 — Screens

### Home

The hero currently occupies a full viewport before any dish appears. It becomes
a **slim banded hero**: headline, the real branch chips already wired up
(`Open now · Thai · ₹2.69 delivery · Min ₹15.00 · 3 branches`), and the search
bar — roughly 40% of its current height, so the menu is visible without
scrolling. The letterform watermark stays at its current 108px as brand texture,
receding rather than leading.

Below: Categories rail, then the dish grid at the new 260px column width. Each
section reveals as it enters.

### Restaurant page

Structure is sound. It receives the new cards, the new spacing, and one addition:
the **category rail becomes sticky** on scroll. On a 100-dish menu, scrolling
back up to change category is the most annoying thing in the current flow.

### Item detail

Best bones, least payoff today — a large media area showing nothing. Becomes:
large `16/9` photo → title and price → the existing stat tiles (Price · Rating ·
Prep time) → description → customisation groups → "Goes well with this" as
compact rows.

The "Ready to order" bar becomes **sticky to the viewport bottom**. On a dish
with several customisation groups the Add button currently falls below the fold,
so the user configures their order and then hunts for the button. The mobile app
already does this; the web does not.

### Cart

Line items become compact rows with thumbnails — a text-only cart of five items
is hard to scan. Summary gains hierarchy: subtotal and fees quiet, **total
prominent**. Place-order becomes a sticky bottom bar, matching item detail.

### Chat

Message bubbles gain a gentle rise on arrival; suggestion results render as
compact dish rows so an AI suggestion is visibly the same object as any other
dish. Otherwise unchanged — it is the least broken screen.

### Out of scope

Auth and profile screens (they inherit tokens and motion for free), and the
search page. Keeping the diff reviewable.

---

## Risks

**Sticky bars versus the mobile tab bar.** Item detail and cart both gain sticky
bottom bars, and a mobile tab bar already exists at `--tab-bar-height: 58px`.
Stacked wrongly the action bar hides behind the tab bar, or both stack and eat
the viewport. Must be verified on a real narrow viewport, not assumed.

**Remote seed images are a network dependency.** Dev and CI environments will
fetch from a third-party CDN, and those URLs can rot. Accepted because it
mirrors production; the fallback state is designed precisely because this
happens.

**Larger cards mean fewer dishes above the fold.** Deliberate, and the direct
consequence of choosing calm over density. If it proves wrong, the column
minimum is a one-token change.

**This reverses recent decisions.** Three of them, marked above. Anyone reading
the git history will see density tightened and then loosened within the same
day. The spec is the record of why.

---

## Success criteria

- A dish card with a photograph looks like it belongs in a modern delivery app.
- A dish card *without* a photograph looks deliberate, not broken.
- No animation ever delays a tap, and every one is disabled under
  `prefers-reduced-motion`.
- The design holds in all 12 tenant presets, in light and dark.
- Nothing animates a layout property.
