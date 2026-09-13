# Customer Storefront — Photo-Led Visual Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the customer storefront from a grid of grey placeholder boxes into a photo-led, calmly-animated ordering experience in the Deliveroo/Uber Eats register.

**Architecture:** Three layers, built bottom-up so each is independently reviewable. First the image pipeline (three designed states, seed photography), then the dish card rebuilt around the image, then a motion system of four named animations driven by CSS tokens and one native `IntersectionObserver` hook. Screens are adjusted last, once the components they compose already look right.

**Tech Stack:** React 19, Vite 8, hand-written CSS, Vitest 3 + jsdom + @testing-library/react, native `IntersectionObserver`. No new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-09-13-customer-visual-redesign-design.md` — read it before Task 1. It records why three decisions from the previous pass are deliberately reversed, and the four consequences of images being hotlinked URLs with no upload pipeline.

## Global Constraints

- **Zero runtime dependencies.** `frontend-customer`'s `dependencies` stays exactly `react` + `react-dom`. No Framer Motion, no GSAP, no UI kit. Test tooling in `devDependencies` is fine.
- **Colour belongs to the tenant.** One brand colour is hue-rotated into the whole palette across 12 presets in light and dark by `src/theme/palette.ts`. Never hardcode a colour. A design that only works in the default orange is a defect.
- **44px minimum touch targets.** Density comes from spacing, never from hit areas.
- **Animate only `transform` and `opacity`.** Both are compositor properties. Animating `height`, `top`, `width` or `margin` causes layout thrash on the mid-range Android hardware most of these users have.
- **`prefers-reduced-motion` honoured by one global rule**, never per-component opt-in.
- **Comments explain why, not what** — match `backend/app/config/settings.py`, which states the measurement or incident behind each decision.
- **Gate before every commit:** `npm test`, `npx tsc -b --noEmit`, `npm run build`, all from `frontend-customer/`. Backend tasks additionally run `backend/.venv/Scripts/python.exe -m compileall app seed.py`.
- **Frontend working directory:** `frontend-customer/`. Backend interpreter is `backend/.venv/Scripts/python.exe` — the system `python` is 3.10 and cannot run this backend.

## File Structure

| File | Responsibility |
|---|---|
| `backend/seed.py` | Modify — add remote `image_url` values to seeded dishes |
| `src/services/api.ts` | Modify — upgrade `createPlaceholderImage()` with a two-tone gradient |
| `src/components/app/DishMedia.tsx` | **Create** — the three image states in one component, used by every dish surface |
| `src/components/app/DishMedia.test.tsx` | **Create** — tests for those three states |
| `src/components/app/DishRow.tsx` | Modify — consume `DishMedia`, restructure the body |
| `src/styles/dish-row.css` | Modify — photo-led card layout, new spacing, hover/press |
| `src/index.css` | Modify — motion tokens, global reduced-motion rule |
| `src/styles/motion.css` | **Create** — reveal and cross-fade keyframes/transitions |
| `src/hooks/useRevealOnScroll.ts` | **Create** — `IntersectionObserver` wrapper that fails visible |
| `src/hooks/useRevealOnScroll.test.ts` | **Create** — tests against a mocked observer |
| `src/pages/HomePage.tsx` | Modify — slim hero, reveals |
| `src/pages/RestaurantPage.tsx` | Modify — sticky category rail |
| `src/pages/MenuItemDetail.tsx` | Modify — large photo, sticky action bar |
| `src/pages/CartPage.tsx` | Modify — compact rows with thumbnails, sticky bar |

---

### Task 1: Seed photography

Without images in the seed, a photo-led design cannot be evaluated — that is the trap the current UI is already in. This lands first so every later task can be judged against real photographs.

**Files:**
- Modify: `backend/seed.py` (the `make_menu_seed(...)` call sites)

**Interfaces:**
- Consumes: nothing.
- Produces: seeded `menu_items` rows whose `image_url` is a live remote URL. Later tasks assume most dishes have one and some do not.

- [ ] **Step 1: Read the existing helper**

`make_menu_seed` at `backend/seed.py:113` already accepts `image_url: str | None = None` as a keyword argument. No signature change is needed — only call sites pass a value.

- [ ] **Step 2: Add a module-level image map**

Add near the other seed constants, above `RESTAURANT_SEED_DATA`:

```python
# Dish photography for the seed.
#
# Remote URLs rather than committed files, deliberately: production has NO
# upload pipeline — an owner pastes a link into a text field in the admin and
# the customer app hotlinks it directly. Committing local JPEGs would make the
# seed behave better than the real product, and the photo-led card would then
# be validated against a fiction.
#
# The consequence is the one production has too: these links can rot. That is
# not a flaw in the fixture, it is the behaviour the fallback state exists for,
# so a dead link here is exercising the design rather than breaking it.
#
# Keyed on dish name because the same dish appears at several branches with
# different prices, and all of them should show the same photograph.
DISH_IMAGE_URLS: dict[str, str] = {
    "Pad Thai Veg": "https://images.unsplash.com/photo-1559314809-0d155014e29e?w=800&q=80",
    "Green Curry Chicken": "https://images.unsplash.com/photo-1455619452474-d2be8b1e70cd?w=800&q=80",
    "Thai Basil Chicken": "https://images.unsplash.com/photo-1569562211093-4ed0d0758f12?w=800&q=80",
    "Thai Iced Tea": "https://images.unsplash.com/photo-1558857563-b371033873b8?w=800&q=80",
    "Coconut Cooler": "https://images.unsplash.com/photo-1536511132770-e5058c7e8c46?w=800&q=80",
    "Red Curry Tofu": "https://images.unsplash.com/photo-1548943487-a2e4e43b4853?w=800&q=80",
    "Thai Chilli Basil Rice": "https://images.unsplash.com/photo-1512058564366-18510be2db19?w=800&q=80",
    "Coconut Pandan Pudding": "https://images.unsplash.com/photo-1488477181946-6428a0291777?w=800&q=80",
}
```

- [ ] **Step 3: Apply the map where menu items are built**

In `build_branch_menu_items`, after `next_item = dict(base_item)`, set the image when the map knows the dish:

```python
        # Left as None when the map has no entry. That is deliberate coverage,
        # not an oversight: a seeded menu where EVERY dish has a photograph
        # would never exercise the placeholder state, which is the state a real
        # menu spends much of its life in.
        image_url = DISH_IMAGE_URLS.get(base_item["name"])
        if image_url:
            next_item["image_url"] = image_url
```

- [ ] **Step 4: Compile-check**

Run from `backend/`: `./.venv/Scripts/python.exe -m compileall -q app seed.py`
Expected: exit 0, no output.

- [ ] **Step 5: Re-seed and verify rows actually carry URLs**

Run from `backend/`: `./.venv/Scripts/python.exe seed.py`

Then confirm against the database — seeding is append-style and idempotent, so existing rows are UPDATED only where the seeder writes them. If the count below is 0, the images did not reach the database and the rest of this plan cannot be evaluated:

```sql
SELECT count(*) FROM menu_items WHERE image_url IS NOT NULL;
```

Expected: greater than 0. Record the number in your report.

- [ ] **Step 6: Commit**

```bash
git add backend/seed.py
git commit -m "feat(seed): give seeded dishes real photography"
```

---

### Task 2: `DishMedia` — the three image states

Every dish surface (grid card, compact row, item detail, chat suggestion) needs identical image behaviour. One component owns it, so the states cannot drift apart the way the two card components did.

**Files:**
- Create: `src/components/app/DishMedia.tsx`
- Create: `src/components/app/DishMedia.test.tsx`
- Modify: `src/services/api.ts` (`createPlaceholderImage`, currently at line 758)

**Interfaces:**
- Consumes: `createPlaceholderImage(seed: string): string` from `../../services/api`.
- Produces: `DishMedia({ name, imageUrl, variant }: { name: string; imageUrl: string | null; variant: 'grid' | 'compact' | 'detail' })`. Tasks 3 and 6 render it.

- [ ] **Step 1: Write the failing test**

Create `src/components/app/DishMedia.test.tsx`:

```tsx
/**
 * The three image states, which exist because production has no upload
 * pipeline: an owner pastes a URL and the app hotlinks it. Links rot, so the
 * placeholder is not a rare fallback — it is where a share of dishes
 * permanently live, and it has to look deliberate rather than broken.
 */

import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { DishMedia } from './DishMedia';

describe('DishMedia', () => {
  it('renders the photograph when the dish has one', () => {
    render(<DishMedia imageUrl="https://example.com/pad-thai.jpg" name="Pad Thai" variant="grid" />);

    expect(screen.getByRole('img')).toHaveAttribute('src', 'https://example.com/pad-thai.jpg');
  });

  it('falls back to the branded placeholder when the dish has no photograph', () => {
    render(<DishMedia imageUrl={null} name="Pad Thai" variant="grid" />);

    expect(screen.getByRole('img').getAttribute('src')).toMatch(/^data:image\/svg\+xml/);
  });

  /**
   * The case that made this component worth extracting: a URL that 404s must
   * land on the SAME designed placeholder, never a broken-image frame.
   */
  it('falls back to the placeholder when the photograph fails to load', () => {
    render(<DishMedia imageUrl="https://example.com/gone.jpg" name="Pad Thai" variant="grid" />);

    fireEvent.error(screen.getByRole('img'));

    expect(screen.getByRole('img').getAttribute('src')).toMatch(/^data:image\/svg\+xml/);
  });

  it('derives the placeholder from the dish name, so the same dish looks the same', () => {
    const { unmount } = render(<DishMedia imageUrl={null} name="Pad Thai" variant="grid" />);
    const first = screen.getByRole('img').getAttribute('src');
    unmount();

    render(<DishMedia imageUrl={null} name="Pad Thai" variant="grid" />);

    expect(screen.getByRole('img').getAttribute('src')).toBe(first);
  });

  it('gives different dishes different placeholders', () => {
    const { unmount } = render(<DishMedia imageUrl={null} name="Pad Thai" variant="grid" />);
    const first = screen.getByRole('img').getAttribute('src');
    unmount();

    render(<DishMedia imageUrl={null} name="Green Curry" variant="grid" />);

    expect(screen.getByRole('img').getAttribute('src')).not.toBe(first);
  });

  /**
   * Lazy loading and async decoding are not decoration here: an owner can
   * paste a 5MB 4000px PNG and nothing resizes it, so a grid of them must not
   * block first paint.
   */
  it('loads lazily and decodes off the main thread', () => {
    render(<DishMedia imageUrl="https://example.com/pad-thai.jpg" name="Pad Thai" variant="grid" />);

    const img = screen.getByRole('img');
    expect(img).toHaveAttribute('loading', 'lazy');
    expect(img).toHaveAttribute('decoding', 'async');
  });

  it('marks the image decorative, because the dish name is already adjacent text', () => {
    render(<DishMedia imageUrl="https://example.com/pad-thai.jpg" name="Pad Thai" variant="grid" />);

    expect(screen.getByRole('img')).toHaveAttribute('alt', '');
  });
});
```

Note: `getByRole('img')` matches an `<img>` with `alt=""` in testing-library's default configuration because the element still exposes the `img` role; if your version excludes it, switch these queries to `container.querySelector('img')`.

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- src/components/app/DishMedia.test.tsx`
Expected: FAIL — `Failed to resolve import "./DishMedia"`. Create a stub returning `null` and re-run so the tests fail on missing behaviour rather than on module resolution.

- [ ] **Step 3: Upgrade the placeholder generator**

In `src/services/api.ts`, replace the `svg` template inside `createPlaceholderImage` (line ~767) with a two-tone version. Keep the function signature and the 420×260 viewBox exactly as they are — the size comment there explains why square sources got crop-scaled:

```ts
  // Two-tone rather than flat: a grid of placeholders was one repeated swatch,
  // which read as "unstyled" rather than "no photo yet". The gradient angle is
  // derived from the dish name so neighbouring cards differ, while the same
  // dish always renders identically.
  const angle = [...seed].reduce((total, character) => total + character.charCodeAt(0), 0) % 360;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 420 260">
<defs><linearGradient id="g" gradientTransform="rotate(${angle} 0.5 0.5)">
<stop offset="0%" stop-color="${ground}"/>
<stop offset="100%" stop-color="${ink}" stop-opacity="0.14"/>
</linearGradient></defs>
<rect width="420" height="260" fill="url(#g)"/>
<circle cx="210" cy="130" r="46" fill="${ink}" opacity="0.10"/>
<text x="210" y="130" fill="${ink}" font-family="system-ui, sans-serif" font-size="30" font-weight="800" letter-spacing="1" text-anchor="middle" dominant-baseline="central">${initials}</text>
</svg>`;
```

- [ ] **Step 4: Write `DishMedia`**

Create `src/components/app/DishMedia.tsx`:

```tsx
import { useState } from 'react';

import { createPlaceholderImage } from '../../services/api';

/**
 * A dish's picture, in the three states it actually occurs in.
 *
 * Extracted rather than left inline because four surfaces render a dish image
 * and they must not drift: consolidating two card components previously kept
 * one's grey-box fallback and silently dropped the other's branded
 * placeholder, which is why every card showed a grey box.
 *
 * Production has no upload pipeline — an owner pastes a URL into a text field
 * and this hotlinks it. So the failure path is ordinary, not exceptional: the
 * link rots, the host blocks hotlinking, and the dish spends the rest of its
 * life in the placeholder state. It is designed for that, not patched for it.
 *
 * The box reserves its aspect ratio in CSS before the image loads, because
 * nothing controls the source dimensions and an unreserved box makes the whole
 * grid jump as photographs arrive.
 */
export function DishMedia({
  name,
  imageUrl,
  variant = 'grid',
}: {
  name: string;
  imageUrl: string | null;
  variant?: 'grid' | 'compact' | 'detail';
}) {
  const [failed, setFailed] = useState(false);
  const src = !imageUrl || failed ? createPlaceholderImage(name) : imageUrl;

  return (
    <span className={`dish-media dish-media--${variant}`}>
      <img
        alt=""
        decoding="async"
        loading="lazy"
        onError={() => setFailed(true)}
        src={src}
      />
    </span>
  );
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `npm test -- src/components/app/DishMedia.test.tsx`
Expected: PASS, 7 tests.

- [ ] **Step 6: Run the full gate**

```bash
npm test
npx tsc -b --noEmit
npm run build
```

- [ ] **Step 7: Commit**

```bash
git add src/components/app/DishMedia.tsx src/components/app/DishMedia.test.tsx src/services/api.ts
git commit -m "feat(customer): one component for a dish photo and its two fallbacks"
```

---

### Task 3: The photo-led card

**Files:**
- Modify: `src/components/app/DishRow.tsx`
- Modify: `src/styles/dish-row.css`

**Interfaces:**
- Consumes: `DishMedia` from Task 2.
- Produces: the same `DishRow` props as today — no call site changes. Emits `.dish-media` inside `.dish-row__media`.

- [ ] **Step 1: Replace the inline image block**

In `DishRow.tsx`, delete the `imageFailed` state and the `showFallbackArt` conditional (lines ~53-80), and render `DishMedia` inside the existing media button. Keep the veg marker and the favourite exactly where they are. Remove the now-unused `useState` and `AppIcon` imports if nothing else uses them.

- [ ] **Step 2: Move the badge out of the image**

The New/Popular badge currently sits in `.dish-row__badges` over the image, competing with the veg marker for the top-left. Move that element into `.dish-row__meta`, after the category. Keep the existing "at most one badge" logic untouched — `is_new` still wins over `is_bestseller`.

- [ ] **Step 3: Rewrite the card CSS**

In `src/styles/dish-row.css`:

Grid columns (lines 25 and 31) change from `minmax(180px, 1fr)` / `minmax(190px, 1fr)` to `minmax(260px, 1fr)`, with this comment:

```css
/* 260px, up from 190px. A photograph at 190px is a stamp rather than an
   appetite cue, and this design makes the picture do the selling. The cost is
   fewer dishes above the fold — roughly five across instead of seven at
   1568px — which is the deliberate trade of density for calm. */
```

Then: card body padding 10px → 14px; grid `gap` → `var(--space-md)`; `.dish-media--grid` gets `aspect-ratio: 4 / 3`; `.dish-media--compact` 88px square; `.dish-media img` gets `width:100%; height:100%; object-fit:cover; display:block`.

Add hover and press, animating only compositor properties:

```css
.dish-row--grid {
  transition: transform var(--motion-base) var(--ease-out),
              box-shadow var(--motion-base) var(--ease-out);
}

.dish-row--grid:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
}

/* The photograph scales inside its clipped box while the card stays put, so
   the image breathes without the layout moving a pixel. */
.dish-row__media { overflow: hidden; }
.dish-row--grid .dish-media img {
  transition: transform var(--motion-slow) var(--ease-out);
}
.dish-row--grid:hover .dish-media img { transform: scale(1.03); }

.dish-row--grid:active { transform: scale(0.98); }
```

These reference tokens Task 4 defines. Task 4 must land before this renders correctly; if you are running tasks in order, add the tokens now as part of Task 4 and do not duplicate them here.

- [ ] **Step 4: Run the full gate**

```bash
npm test
npx tsc -b --noEmit
npm run build
```

Expected: all pass. `tokens.test.ts` will FAIL if `--motion-base`, `--ease-out` or `--motion-slow` are not yet defined — that is the guard working. Land Task 4's token block before committing this task.

- [ ] **Step 5: Verify in a browser**

Start `npm run dev -- --port 5173 --strictPort`, open `http://localhost:5173/`, and confirm: dishes show photographs; a dish with no photograph shows a tinted placeholder with its initials, not a grey box; hovering a card lifts it and scales the photo; the grid shows about five across at full width.

- [ ] **Step 6: Commit**

```bash
git add src/components/app/DishRow.tsx src/styles/dish-row.css
git commit -m "feat(customer): rebuild the dish card around its photograph"
```

---

### Task 4: Motion tokens and reduced motion

**Files:**
- Modify: `src/index.css`
- Create: `src/styles/motion.css`
- Modify: `src/main.tsx` (import `motion.css` after `dish-row.css`)

**Interfaces:**
- Consumes: nothing.
- Produces: `--motion-fast`, `--motion-base`, `--motion-slow`, `--ease-out`, `--ease-inout`; the classes `.reveal`, `.reveal--visible`, `.dish-media--loading`.

- [ ] **Step 1: Add the tokens**

In `src/index.css`, directly after the type scale block:

```css
  /* --- motion --------------------------------------------------------------
     Three durations and two curves, referenced by every animation in the app,
     so the whole feel retunes from one place rather than from magic numbers
     scattered across four stylesheets.

     Only `transform` and `opacity` are ever animated against these. Both are
     compositor properties; animating `height`, `top` or `width` forces layout
     on every frame, which is what makes a page feel cheap on the mid-range
     Android hardware most of these customers are using. */
  --motion-fast: 120ms;
  --motion-base: 200ms;
  --motion-slow: 320ms;
  --ease-out: cubic-bezier(0.2, 0, 0, 1);
  --ease-inout: cubic-bezier(0.4, 0, 0.2, 1);
```

- [ ] **Step 2: Create the motion stylesheet**

Create `src/styles/motion.css`:

```css
/* --- motion ------------------------------------------------------------------
   Reveals fail VISIBLE.

   The conventional implementation hides an element in CSS and reveals it when
   an IntersectionObserver fires. If JS fails to boot, the observer never fires,
   or support is absent, that leaves the page permanently blank — a silent
   failure of exactly the kind this codebase has been bitten by repeatedly.

   So the hidden state is scoped to `.js-motion`, a class `main.tsx` sets on
   <html> at boot. No JS, no observer, no support: content simply shows.
*/
.js-motion .reveal {
  opacity: 0;
  transform: translateY(12px);
}

.js-motion .reveal--visible {
  opacity: 1;
  transform: none;
  transition: opacity var(--motion-slow) var(--ease-out),
              transform var(--motion-slow) var(--ease-out);
}

/* Stagger, capped at six. An uncapped ramp across a fifty-dish grid takes two
   seconds to finish and reads as the page being broken rather than as polish. */
.js-motion .reveal--visible:nth-child(1) { transition-delay: 0ms; }
.js-motion .reveal--visible:nth-child(2) { transition-delay: 40ms; }
.js-motion .reveal--visible:nth-child(3) { transition-delay: 80ms; }
.js-motion .reveal--visible:nth-child(4) { transition-delay: 120ms; }
.js-motion .reveal--visible:nth-child(5) { transition-delay: 160ms; }
.js-motion .reveal--visible:nth-child(n + 6) { transition-delay: 200ms; }

/* Content cross-fades over its skeleton rather than replacing it. The hard swap
   is a large part of what currently reads as cheap. */
.dish-media img {
  animation: dish-media-in var(--motion-base) var(--ease-out);
}

@keyframes dish-media-in {
  from { opacity: 0; }
  to { opacity: 1; }
}

/* One global rule rather than per-component opt-in, so a component nobody
   remembered cannot break the promise. Scroll-triggered motion is genuinely
   unpleasant for people with vestibular disorders. */
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 1ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 1ms !important;
    scroll-behavior: auto !important;
  }
}
```

- [ ] **Step 3: Import it and set the boot class**

In `src/main.tsx`, after the `dish-row.css` import:

```ts
// After the component layers: motion decorates what they lay out, and its
// reduced-motion rule must be able to override any transition they declare.
import './styles/motion.css';

// Opts into hidden-then-revealed. Set here rather than in the HTML so that a
// JS bundle which never boots leaves every reveal target visible.
document.documentElement.classList.add('js-motion');
```

- [ ] **Step 4: Run the full gate**

```bash
npm test
npx tsc -b --noEmit
npm run build
```

Expected: all pass, including `tokens.test.ts` now that the motion tokens exist.

- [ ] **Step 5: Verify reduced motion actually applies**

In Chrome DevTools → Rendering → "Emulate CSS prefers-reduced-motion: reduce", reload, and confirm hovering a card no longer animates. Report what you observed.

- [ ] **Step 6: Commit**

```bash
git add src/index.css src/styles/motion.css src/main.tsx
git commit -m "feat(customer): motion tokens, reveal styles, and a global reduced-motion rule"
```

---

### Task 5: `useRevealOnScroll`

**Files:**
- Create: `src/hooks/useRevealOnScroll.ts`
- Create: `src/hooks/useRevealOnScroll.test.ts`

**Interfaces:**
- Consumes: `.reveal` / `.reveal--visible` from Task 4.
- Produces: `useRevealOnScroll<T extends HTMLElement>(): RefObject<T | null>` — attach the returned ref to an element that already carries `className="reveal"`.

- [ ] **Step 1: Write the failing test**

Create `src/hooks/useRevealOnScroll.test.ts`:

```ts
/**
 * The hook adds one class when its element enters the viewport, and then stops
 * observing. Tested against a mocked IntersectionObserver because jsdom has
 * none — which is also the reason the CSS keeps content visible unless
 * `.js-motion` is set: a browser without support must still show the page.
 */

import { renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useRevealOnScroll } from './useRevealOnScroll';

let triggerIntersect: ((entries: Partial<IntersectionObserverEntry>[]) => void) | null = null;
const disconnect = vi.fn();

beforeEach(() => {
  disconnect.mockClear();
  vi.stubGlobal(
    'IntersectionObserver',
    class {
      constructor(callback: (entries: Partial<IntersectionObserverEntry>[]) => void) {
        triggerIntersect = callback;
      }
      observe() {}
      disconnect = disconnect;
      unobserve() {}
    },
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  triggerIntersect = null;
});

describe('useRevealOnScroll', () => {
  it('returns a ref that starts empty', () => {
    const { result } = renderHook(() => useRevealOnScroll<HTMLDivElement>());

    expect(result.current.current).toBeNull();
  });

  it('adds the visible class once the element intersects', () => {
    const element = document.createElement('div');
    element.className = 'reveal';
    const { result } = renderHook(() => useRevealOnScroll<HTMLDivElement>());
    result.current.current = element;

    triggerIntersect?.([{ isIntersecting: true, target: element }]);

    expect(element.classList.contains('reveal--visible')).toBe(true);
  });

  it('does not add the class while the element is outside the viewport', () => {
    const element = document.createElement('div');
    element.className = 'reveal';
    const { result } = renderHook(() => useRevealOnScroll<HTMLDivElement>());
    result.current.current = element;

    triggerIntersect?.([{ isIntersecting: false, target: element }]);

    expect(element.classList.contains('reveal--visible')).toBe(false);
  });

  /**
   * A reveal is a one-shot. Without this the element re-hides when scrolled
   * past and re-animates on the way back, which reads as flickering.
   */
  it('stops observing after the first reveal', () => {
    const element = document.createElement('div');
    element.className = 'reveal';
    const { result } = renderHook(() => useRevealOnScroll<HTMLDivElement>());
    result.current.current = element;

    triggerIntersect?.([{ isIntersecting: true, target: element }]);

    expect(disconnect).toHaveBeenCalled();
  });

  it('disconnects on unmount so a removed element is not held', () => {
    const { unmount } = renderHook(() => useRevealOnScroll<HTMLDivElement>());

    unmount();

    expect(disconnect).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- src/hooks/useRevealOnScroll.test.ts`
Expected: FAIL — module not found. Stub the file returning `useRef(null)` and re-run so failures are behavioural.

- [ ] **Step 3: Implement the hook**

Create `src/hooks/useRevealOnScroll.ts`:

```ts
import { useEffect, useRef, type RefObject } from 'react';

/**
 * Reveals one element the first time it enters the viewport.
 *
 * Deliberately does nothing when `IntersectionObserver` is absent. The CSS
 * keeps `.reveal` elements visible unless `<html>` carries `.js-motion`, so a
 * browser without support — or a bundle that never booted — shows plain
 * content rather than a blank page. A reveal that hides content when its
 * machinery fails is worse than no reveal at all.
 *
 * One-shot: it disconnects on first intersection. Left observing, an element
 * re-hides when scrolled past and re-animates on the way back, which reads as
 * flicker rather than as polish.
 */
export function useRevealOnScroll<T extends HTMLElement>(): RefObject<T | null> {
  const ref = useRef<T | null>(null);

  useEffect(() => {
    const element = ref.current;
    if (!element || typeof IntersectionObserver === 'undefined') {
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            (entry.target as HTMLElement).classList.add('reveal--visible');
            observer.disconnect();
          }
        }
      },
      // Fires slightly before the element reaches the fold, so the transition
      // is already underway by the time it is actually looked at.
      { rootMargin: '0px 0px -10% 0px', threshold: 0.05 },
    );

    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  return ref;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm test -- src/hooks/useRevealOnScroll.test.ts`
Expected: PASS, 5 tests.

- [ ] **Step 5: Run the full gate**

```bash
npm test
npx tsc -b --noEmit
npm run build
```

- [ ] **Step 6: Commit**

```bash
git add src/hooks/useRevealOnScroll.ts src/hooks/useRevealOnScroll.test.ts
git commit -m "feat(customer): a scroll reveal hook that fails visible"
```

---

### Task 6: Home and Restaurant screens

**Files:**
- Modify: `src/pages/HomePage.tsx`
- Modify: `src/styles/home.css`
- Modify: `src/pages/RestaurantPage.tsx`
- Modify: `src/styles/screens.css`

**Interfaces:**
- Consumes: `useRevealOnScroll` (Task 5), the `.reveal` class (Task 4), the new card (Task 3).
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Slim the hero**

In `src/styles/home.css`, reduce the hero's vertical padding so it occupies roughly 40% of its current height, with this comment:

```css
/* The hero used to fill a viewport before a single dish appeared, which on a
   food app is a screen of brand where the customer wanted a menu. It keeps the
   headline, the real branch chips and the search bar; it loses the height. */
```

Leave `.home-hero__art-fallback` at `font-size: 108px` — it is deliberately off the type scale as brand texture.

- [ ] **Step 2: Reveal the home sections**

In `HomePage.tsx`, for each of the Explore Menu, AI prompt, Personalized Picks, combos and offers sections: call `const ref = useRevealOnScroll<HTMLElement>()` once per section (hooks must be called unconditionally at the top level, never in a loop or condition), attach `ref={ref}` and add `reveal` to the section's existing `className`.

- [ ] **Step 3: Make the restaurant category rail sticky**

In `src/styles/screens.css`, on the restaurant page's category rail container:

```css
/* Sticky, because on a hundred-dish menu the alternative is scrolling all the
   way back up to change category — the single most irritating thing in the
   current browse flow. Offset by the header so it parks below it, not under it. */
.restaurant-page .category-rail {
  position: sticky;
  top: var(--app-header-height);
  z-index: 5;
  background: var(--bg);
}
```

- [ ] **Step 4: Run the full gate**

```bash
npm test
npx tsc -b --noEmit
npm run build
```

- [ ] **Step 5: Verify in a browser**

Load Home: the menu should be visible with little or no scrolling; sections should fade and rise as you scroll to them, once each. Load a restaurant page and scroll: the category chips should stick below the header. Then narrow the window to ~400px and confirm the sticky rail does not cover content or collide with the header.

- [ ] **Step 6: Commit**

```bash
git add src/pages/HomePage.tsx src/styles/home.css src/pages/RestaurantPage.tsx src/styles/screens.css
git commit -m "feat(customer): slim the hero, reveal sections, stick the category rail"
```

---

### Task 7: Item detail and Cart

**Files:**
- Modify: `src/pages/MenuItemDetail.tsx`
- Modify: `src/pages/CartPage.tsx`
- Modify: `src/styles/screens.css`

**Interfaces:**
- Consumes: `DishMedia` (Task 2), `DishRow` compact variant (Task 3), motion tokens (Task 4).
- Produces: nothing.

- [ ] **Step 1: Give item detail a real photograph**

In `MenuItemDetail.tsx`, render `<DishMedia imageUrl={item.image_url} name={item.name} variant="detail" />` in the hero media slot. In `screens.css`, `.dish-media--detail { aspect-ratio: 16 / 9; width: 100%; }`.

- [ ] **Step 2: Stick both action bars**

Add to `screens.css`:

```css
/* Sticky, because a dish with several customisation groups pushes the Add
   button below the fold: the customer configures their order and then has to
   go looking for the button. The phone app already does this; the web did not.
   `--tab-bar-height` is added to the bottom offset so the bar parks ABOVE the
   mobile tab bar rather than behind it. */
.menu-detail-page__action-bar,
.cart-page__action-bar {
  position: sticky;
  bottom: calc(var(--tab-bar-height) + var(--space-xs));
  z-index: 6;
  background: var(--surface-raised);
  border: 1px solid var(--border);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-lg);
}

@media (min-width: 960px) {
  /* No tab bar at site width, so the extra offset would just float the bar. */
  .menu-detail-page__action-bar,
  .cart-page__action-bar {
    bottom: var(--space-md);
  }
}
```

Apply the matching class to the existing "Ready to order" bar in `MenuItemDetail.tsx` and the place-order bar in `CartPage.tsx`.

- [ ] **Step 3: Give cart lines thumbnails**

In `CartPage.tsx`, render each line item's image with `<DishMedia imageUrl={line.image_url ?? null} name={line.name} variant="compact" />`. If the cart line type carries no image field, pass `null` — the placeholder handles it, and say so in your report rather than inventing a field.

- [ ] **Step 4: Give the cart summary hierarchy**

In `screens.css`, make subtotal and fee rows `color: var(--muted); font-size: var(--text-sm)`, and the total row `font-size: var(--text-xl); font-weight: 700; color: var(--text)`.

- [ ] **Step 5: Run the full gate**

```bash
npm test
npx tsc -b --noEmit
npm run build
```

- [ ] **Step 6: Verify the sticky-bar risk on a narrow viewport**

This is the plan's highest-risk change. At ~400px width, on both item detail and cart: the action bar must sit **above** the mobile tab bar, must not cover the last line of content, and must not double-stack. Report exactly what you saw at 400px and at 1400px.

- [ ] **Step 7: Commit**

```bash
git add src/pages/MenuItemDetail.tsx src/pages/CartPage.tsx src/styles/screens.css
git commit -m "feat(customer): photo-led item detail, scannable cart, sticky actions"
```

---

### Task 8: Verify across tenants and modes

Every change above is brand-neutral by construction. "By construction" is not evidence, and the highest-consequence failure here — a design that only looks right in the default orange — is invisible on the default theme.

**Files:** none. Verification only.

- [ ] **Step 1: Switch the seeded restaurant to a cold preset**

```sql
UPDATE restaurants SET theme = '{"preset": "indigo", "primary_color": "#4338CA"}'::jsonb
WHERE slug = 'bangkok-bowl';
```

- [ ] **Step 2: Inspect in light mode**

Reload. Confirm: no element is still orange; the branded placeholder has picked up indigo; photographs are unaffected; text is legible on every surface; hover and reveal still behave.

- [ ] **Step 3: Inspect in dark mode**

Switch via `/profile` appearance (the preference is stored under `restaurant-rag-customer-theme-preference`), reload, re-inspect. Pay attention to the scrim behind the favourite control — it must hold against both a light photograph and a dark surface.

- [ ] **Step 4: Restore**

```sql
UPDATE restaurants SET theme = '{"preset": "sunset", "primary_color": "#FF5200"}'::jsonb
WHERE slug = 'bangkok-bowl';
```

- [ ] **Step 5: Record the result**

Append to `.claude/worklog.md`: which presets and modes were checked, what was observed, and explicitly what was NOT covered (the other ten presets, and screens beyond those inspected). If anything looked wrong, write down what and stop rather than reporting success.

---

## Self-Review

**Spec coverage.** Section 1 (imagery) → Tasks 1, 2. Section 2 (card) → Task 3. Section 3 (motion) → Tasks 4, 5. Section 4 (screens) → Tasks 6, 7; Chat is the one screen the spec names that has **no task** — its changes are message-bubble motion and compact suggestion rows, both of which it inherits from Tasks 4 and 3 without page-level work, so no task is needed. Constraints → Global Constraints plus Task 8. The "product gap" (no upload pipeline) is explicitly out of scope in the spec and correctly has no task.

**Placeholder scan.** No TBDs. Every code step carries literal content. Task 6 Step 2 is rule-driven rather than a fixed diff because the section list differs per page; the hooks rule makes it deterministic.

**Type consistency.** `DishMedia`'s props (`name`, `imageUrl`, `variant`) are identical in Task 2's definition and its uses in Tasks 3 and 7. `useRevealOnScroll<T>(): RefObject<T | null>` matches its use in Task 6. The `.dish-media--{grid,compact,detail}` variants defined in Task 2 all receive CSS in Tasks 3 and 7.

**Known risks.** Tasks 3, 6 and 7 have no automated test proving the visual result — CSS values are not meaningfully unit-testable, so each carries an explicit browser verification step instead. Task 7's sticky bars against `--tab-bar-height` is the highest-risk change and has a dedicated narrow-viewport check. Task 1 depends on remote URLs that can rot; that is accepted in the spec and is the reason Task 2's fallback exists.
