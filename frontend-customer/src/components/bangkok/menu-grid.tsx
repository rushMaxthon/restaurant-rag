import { useEffect, useMemo, useRef, useState } from "react";
import { Leaf, Search, SlidersHorizontal, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { MenuItem } from "@/lib/bangkok-data";
import { activeSection, buildSections, countItems } from "@/lib/menu-sections";
import { sortsFor } from "@/lib/menu-sorts";
import { useBangkokStore } from "@/lib/bangkok-store";
import { useMenuItems } from "@/lib/queries";
import { DishCard } from "./dish-card";

/**
 * How much of the top of the window the sticky chrome covers, and the two
 * offsets derived from it.
 *
 * **One number, in one place, because three things have to agree**: where a
 * jump leaves a heading, which section the rail calls current, and where the
 * chrome actually ends. They did not. The landing was left to CSS
 * (`scroll-margin-top: 132px` on the heading) and the highlight to a constant
 * in this file (136px) — and a global `scroll-padding-top: 80px` on the root
 * composes with the first of those, so a jump landed the heading at 217px:
 * 85px below the rail, and below the line that decides the highlight. The page
 * went to the right section and the rail named the one before it.
 *
 * Measured rather than reasoned: with the rail stuck, its bottom edge sits at
 * 132px on both a desktop window and a phone.
 */
const CHROME = 132;
/** A jump leaves the heading just clear of the rail. */
const LANDING = CHROME + 8;
/**
 * A section is current once its heading has reached here. Below the landing
 * point on purpose, so a jump always marks the section it just landed on —
 * the two being equal would make it a coin toss on a sub-pixel rounding.
 */
const ACTIVE_LINE = CHROME + 56;

/**
 * Put a section's heading just below the chrome, and HOLD it there until the
 * page stops arguing.
 *
 * Four things here were each arrived at by measuring a failure.
 *
 * **Scrolled explicitly, not with `scrollIntoView`.** That way the landing
 * offset and `ACTIVE_LINE` come from one constant, rather than from a
 * `scroll-margin-top` that silently composes with a global
 * `scroll-padding-top` — which is how a jump came to land 85px below the rail
 * while the highlight named the previous section.
 *
 * **Animated here rather than with `behavior: "smooth"`.** The browser
 * animates towards an offset computed when the animation BEGINS, and content
 * arriving above the target moves it, so the animation ends early. Measured
 * on a 6,000px jump: native smooth stopped 2,281px short.
 *
 * So the travel is tweened in this loop, which re-measures the heading every
 * frame and eases towards wherever it is NOW. That is what makes it both
 * smooth and correct on a page that is still growing — the target moving
 * under the animation is the normal case here, not the edge one.
 *
 * Two phases, deliberately. The TRAVEL is eased, because it is a journey a
 * reader follows with their eye. What comes after is CORRECTION — the webfont
 * swapping and re-measuring every dish name, the router restoring a saved
 * position — and those are instant, because a correction that animates reads
 * as the page drifting on its own.
 *
 * **Corrected every frame, by the remaining distance.** One scroll is not
 * enough, because two different things disturb it and they are not the same
 * problem. The page GROWS — this menu is 187 dishes, 36,000px in a desktop
 * window and 87,000px on a phone, and it keeps getting taller after it is
 * interactive as the webfont swaps and re-measures every dish name and images
 * resolve. And the position is RESET — the router is created with
 * `scrollRestoration`, and its restore for the incoming location can land
 * after the jump. Watching only for growth misses the reset, because a reset
 * changes no heights; watching for a fixed number of frames misses whichever
 * one is late, and which one is late depends on a cold cache. Both were tried,
 * and each passed on a warm run and failed on a cold one.
 *
 * Comparing the heading against where it should be, every frame, asks the only
 * question that matters and does not care which disturbance it is answering.
 *
 * **It yields to the reader.** The first wheel, touch or key press ends it —
 * correcting the scroll under somebody who has started reading would be far
 * worse than landing slightly off.
 */
/**
 * How long the eased travel lasts.
 *
 * Distance-aware, because one duration cannot serve both ends of a 36,000px
 * menu: a flat 520ms made the jump to the next section along feel unhurried
 * and the jump to the last one feel like a teleport. Scaled by the distance
 * and clamped at both ends, so a short hop stays brisk and a long one stays
 * followable — the eye has to see which way the page went, or the landing
 * reads as a different page rather than a different part of this one.
 */
const TRAVEL_MIN_MS = 380;
const TRAVEL_MAX_MS = 620;
const travelFor = (distance: number) =>
  Math.min(TRAVEL_MAX_MS, Math.max(TRAVEL_MIN_MS, Math.abs(distance) * 0.45));

/**
 * How much of the journey is actually animated, as a multiple of the screen.
 *
 * Everything beyond this is covered instantly first, and only the final
 * approach eases. That is not a shortcut, it is the fix for what animating the
 * whole distance caused: this menu is 36,000px of lazily-loaded photographs,
 * and easing across 13,000px of it drags the viewport through section after
 * section whose images have not loaded. Measured on one jump — five of the six
 * images on screen unloaded at once, fifteen frames with three or more — so
 * every card drew its motif, then swapped to a photograph, the whole way past.
 * That stream of swaps is the blinking.
 *
 * A screen and a bit is enough to see which way the page went, which is the
 * only thing the travel was ever for.
 */
const APPROACH_SCREENS = 1.15;

/** Decelerating: quick off the mark, settling into the landing. */
const easeOut = (t: number) => 1 - Math.pow(1 - t, 3);

function jumpToSection(slug: string): () => void {
  let abandoned = false;
  let frame = 0;
  let quiet = 0;
  let passes = 0;

  // Somebody who has asked their system to stop moving things gets the
  // landing without the journey — not a faster journey.
  // Start the destination's photographs fetching at the moment of the click.
  //
  // A jump lands on a section whose images are still lazy, so they begin
  // loading only once they are near the viewport — and each one draws its
  // motif first and swaps to the photograph a moment later. Arriving on a
  // screenful of those swaps is the blink.
  //
  // The eased approach below takes about 400ms, and this spends it: the
  // images are told to load now rather than on arrival, so most of them are
  // decoded by the time anybody is looking at them. It cannot help where the
  // network is slower than the animation, which is why the motif underneath
  // them stays — it is a considered placeholder rather than a blank.
  const preload = (slugged: HTMLElement | null) => {
    const section = slugged?.closest(".menu-section");
    if (!section) return;
    for (const image of section.querySelectorAll("img")) {
      image.loading = "eager";
      // Ahead of anything else still queued for a page this long.
      image.fetchPriority = "high";
    }
  };

  // Cover the distance beyond the final approach in one go, before anything
  // is animated, so the eased part never drags the viewport through content
  // that has not loaded.
  const first = typeof document !== "undefined" ? document.getElementById(slug) : null;
  preload(first);
  if (first && typeof window !== "undefined") {
    const whole = first.getBoundingClientRect().top - LANDING;
    const approach = window.innerHeight * APPROACH_SCREENS;
    if (Math.abs(whole) > approach) {
      window.scrollBy({ top: whole - Math.sign(whole) * approach, behavior: "instant" });
    }
  }

  const startedAt = typeof performance !== "undefined" ? performance.now() : 0;
  // Read AFTER the instant leg, so the tween eases from where it really is.
  const from = typeof window !== "undefined" ? window.scrollY : 0;
  const travelMs =
    typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
      ? 0
      : travelFor(first ? first.getBoundingClientRect().top - LANDING : 0);

  const stop = () => {
    if (abandoned) return;
    abandoned = true;
    if (frame) cancelAnimationFrame(frame);
    for (const event of ["wheel", "touchstart", "keydown"] as const) {
      window.removeEventListener(event, stop);
    }
  };

  const step = () => {
    if (abandoned) return;
    const node = document.getElementById(slug);
    if (!node) return stop();

    const remaining = node.getBoundingClientRect().top - LANDING;
    const elapsed = performance.now() - startedAt;

    if (elapsed < travelMs) {
      // Still travelling. The destination is re-measured every frame, so a
      // page growing above the target pulls the whole curve with it instead
      // of leaving the animation short.
      const target = window.scrollY + remaining;
      const eased = easeOut(elapsed / travelMs);
      window.scrollTo({ top: from + (target - from) * eased, behavior: "instant" });
      quiet = 0;
    } else if (Math.abs(remaining) > 2) {
      // Arrived, and something moved underneath it. By the REMAINING
      // distance, so it converges instead of recomputing an absolute
      // position that keeps going stale.
      window.scrollBy({ top: remaining, behavior: "instant" });
      quiet = 0;
    } else {
      quiet += 1;
    }

    passes += 1;
    // Held for a second and a half after it last had to move, not half a
    // second. The extra second is for one specific late arrival: open /menu,
    // then follow a link to /menu?category=X in the same tab, and the router
    // has a saved scroll entry for that path — it restores it, at zero, a
    // beat after the jump has already landed and gone quiet. A cold load
    // straight to the same link never shows it, because there is no saved
    // entry to restore. Ten seconds remains the hard ceiling, so nothing can
    // pin a storefront whose images never finish arriving.
    if (quiet < 90 && passes < 600) frame = requestAnimationFrame(step);
    else stop();
  };

  for (const event of ["wheel", "touchstart", "keydown"] as const) {
    window.addEventListener(event, stop, { passive: true, once: true });
  }
  step();
  return stop;
}

type Sort = "recommended" | "price-asc" | "price-desc" | "rating";

const SORTS: { value: Sort; label: string }[] = [
  { value: "recommended", label: "Recommended" },
  { value: "price-asc", label: "Price: low to high" },
  { value: "price-desc", label: "Price: high to low" },
  { value: "rating", label: "Top rated" },
];

/** Bestsellers first, then rating — the order the menu arrives in is arbitrary. */
function compare(sort: Sort, a: MenuItem, b: MenuItem): number {
  if (sort === "price-asc") return Number(a.price) - Number(b.price);
  if (sort === "price-desc") return Number(b.price) - Number(a.price);
  if (sort === "rating") return Number(b.rating ?? 0) - Number(a.rating ?? 0);
  if (a.is_bestseller !== b.is_bestseller) return a.is_bestseller ? -1 : 1;
  return Number(b.rating ?? 0) - Number(a.rating ?? 0);
}

/**
 * Placeholder shaped like a DishCard — image, meta line, title, two lines of
 * description, price and button — so the swap to real content is a crossfade
 * rather than a jump from a tinted rectangle to a card twice its height.
 */
export function DishSkeleton() {
  return (
    <div className="skeleton-card" aria-hidden="true">
      <div className="skeleton skeleton-img" />
      <div className="skeleton-body">
        <div className="skeleton skeleton-line skeleton-line--meta" />
        <div className="skeleton skeleton-line skeleton-line--title" />
        <div className="skeleton skeleton-line" />
        <div className="skeleton skeleton-line skeleton-line--short" />
        <div className="skeleton-row">
          <div className="skeleton skeleton-price" />
          <div className="skeleton skeleton-btn" />
        </div>
      </div>
    </div>
  );
}

/**
 * The whole menu, in the kitchen's own sections, with a rail that jumps.
 *
 * **This used to show one category at a time.** The rail of chips was a
 * filter: pick "Starters" and the twenty other sections vanished. It is a
 * reasonable control and it made a bad menu — the only way to see what a
 * kitchen does was to click through twenty-one chips in turn, and the shape of
 * the menu, which is half of what a menu communicates, was never visible at
 * all. No food site anybody uses works that way, and no paper menu ever has.
 *
 * So the sections are all rendered, in order, and the rail became navigation:
 * a chip scrolls to its heading and the highlight follows the scroll back. The
 * two controls that genuinely subtract — search and veg-only — still subtract,
 * because "which dishes qualify" is a different question from "where do I want
 * to look".
 *
 * Three details that are easy to get wrong and are deliberate here:
 *
 * **The chosen section stays in the URL.** It is a jump target rather than a
 * filter now, but /menu?category=Sweets must still land on the sweets — that
 * is what the home page's section links are, and what somebody shares.
 *
 * **The highlight is driven by an observer, not by the click.** Clicking a chip
 * scrolls; what is highlighted is whatever section is actually on screen when
 * the scrolling stops. Tracking the click instead would leave the rail
 * confidently pointing at a section the customer scrolled away from.
 *
 * **The rail does not write to the URL as you scroll.** It would mean a history
 * entry, or at least a URL rewrite, per section passed.
 */
export function MenuGrid({
  category,
  onCategoryChange,
}: {
  /**
   * The section to jump to, owned by the route so it can live in the URL.
   *
   * It was local state, which meant a menu of 21 sections could not be linked
   * to, shared, or returned to with the back button — and the home page had
   * no way to send somebody to one.
   */
  category: string;
  onCategoryChange: (next: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [vegOnly, setVegOnly] = useState(false);
  const [sort, setSort] = useState<Sort>("recommended");
  /** Which section the rail is pointing at — see the note above. */
  const [active, setActive] = useState<string | null>(null);
  const railRef = useRef<HTMLDivElement | null>(null);

  const { restaurantId, branchId, isRestaurantLoading, isRestaurantError } = useBangkokStore();
  const menuQuery = useMenuItems(restaurantId, branchId || undefined);
  // `?? []` alone builds a fresh array on every render, so every memo below
  // would recompute every time and the memoisation would buy nothing.
  const items = useMemo(() => menuQuery.data ?? [], [menuQuery.data]);
  // "Top rated" was offered whatever the data held, and not one dish on this
  // menu has a rating — so choosing it compared 0 against 0 for every pair and
  // reordered nothing. A control that promises an ordering the data cannot
  // provide is worse than one fewer control.
  const sorts = useMemo(() => sortsFor(SORTS, items), [items]);

  const sections = useMemo(
    () => buildSections(items, { query, vegOnly, compare: (a, b) => compare(sort, a, b) }),
    [items, query, vegOnly, sort],
  );
  const total = countItems(sections);

  const loading = isRestaurantLoading || menuQuery.isLoading;
  // A request that never happened is not an empty menu. When /app-config fails
  // the menu query is disabled, so it reports neither loading nor error and the
  // screen used to say "Nothing matches that" — telling the customer something
  // false about the restaurant instead of that we could not reach it.
  const failed = isRestaurantError || menuQuery.isError;
  const filtered = vegOnly || query.trim().length > 0;

  /**
   * Land on the section the address asked for.
   *
   * Keyed on the category and on whether the sections have arrived, so it runs
   * once per deep link rather than on every render. `instant` on the first run
   * for a reason: a smooth scroll from the top of a long menu takes about a
   * second, during which the page is visibly travelling past dishes the
   * customer did not ask to see.
   */
  const landed = useRef<string | null>(null);
  const cancelJump = useRef<(() => void) | null>(null);

  // Cancelled on unmount ONLY — see below for why it is not the effect's own
  // cleanup.
  useEffect(() => () => cancelJump.current?.(), []);

  useEffect(() => {
    if (!category || category === "All" || sections.length === 0) return;
    if (landed.current === category) return;
    const target = sections.find((section) => section.category === category);
    if (!target) return;
    landed.current = category;
    cancelJump.current?.();
    // **Held in a ref rather than returned as this effect's cleanup**, and
    // that distinction is the whole bug it fixes. `sections` is a memo over
    // the query's data, so it takes a new identity whenever TanStack Query
    // hands back a new array — a background refetch is enough. React runs the
    // previous cleanup before re-running the effect, so returning the
    // canceller meant any such refetch killed the correction mid-flight; and
    // because `landed.current` was already set, the early return above then
    // declined to start another. The jump died silently and the page stayed
    // where it was.
    //
    // It presented as a deep link that worked on a warm run and did nothing on
    // a cold one, which sent two rounds of tuning after the frame budget
    // instead. The clue that should have been read sooner: clicking a chip,
    // which calls `jumpToSection` directly and registers no cleanup, never
    // once failed.
    cancelJump.current = jumpToSection(target.slug);
  }, [category, sections]);

  /**
   * Which section is on screen, for the rail.
   *
   * Measured on scroll rather than watched with an IntersectionObserver, for
   * two reasons set out in full on `activeSection`: an observer sampling
   * frames jumps straight over a section heading on any normal flick, and it
   * delivers nothing at all while the tab is in the background, which makes
   * it unverifiable.
   *
   * **The positions are cached, and the scroll handler does no layout.** It
   * used to read nineteen `getBoundingClientRect()` inside every animation
   * frame, and a rect read after any style change forces the browser to lay
   * the page out there and then — nineteen forced layouts per frame, over
   * 5,000 nodes, for the whole time somebody is scrolling. It never showed up
   * as a long task because no single one crossed 50ms; it showed up as the
   * page absorbing 85% of a wheel instead of 100%, and reading as a stutter
   * at every section boundary.
   *
   * Now each heading's position is measured once into `tops`, and the
   * handler only subtracts `scrollY` from numbers it already has — which
   * costs nothing and reads no layout at all.
   *
   * The cache has to be right, and the page is not still: the webfont swaps
   * and re-measures every dish name, images resolve, the grid reflows. A
   * `ResizeObserver` on the grid invalidates it whenever any of that changes
   * a height, which is the event that actually matters rather than a guess at
   * how long it takes.
   *
   * `ACTIVE_LINE` is derived from the measured chrome at the top of this
   * file, which is also what the jump uses — see the note there for why they
   * have to come from one number.
   */
  useEffect(() => {
    if (sections.length === 0) return;
    let frame = 0;
    let tops: number[] = [];

    // Absolute document positions, so they stay valid as the page scrolls.
    const remeasure = () => {
      tops = sections.map((section) => {
        const node = document.getElementById(section.slug);
        return node ? node.getBoundingClientRect().top + window.scrollY : Number.POSITIVE_INFINITY;
      });
    };

    const apply = () => {
      frame = 0;
      // `activeSection` takes viewport-relative tops, and is tested that way.
      setActive(
        activeSection(
          sections,
          tops.map((top) => top - window.scrollY),
          ACTIVE_LINE,
        ),
      );
    };

    const onScroll = () => {
      // Still coalesced to one update per frame: a wheel fires far faster
      // than the page repaints.
      if (frame === 0) frame = requestAnimationFrame(apply);
    };

    const onResize = () => {
      remeasure();
      onScroll();
    };

    remeasure();
    apply();

    // Whatever changes a height invalidates the cache — the font swapping,
    // an image resolving, the grid reflowing at a breakpoint.
    const grid = document.querySelector(".menu-grid");
    const observer =
      typeof ResizeObserver !== "undefined" && grid
        ? new ResizeObserver(() => {
            remeasure();
            onScroll();
          })
        : null;
    observer?.observe(grid as Element);

    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onResize, { passive: true });
    return () => {
      if (frame !== 0) cancelAnimationFrame(frame);
      observer?.disconnect();
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onResize);
    };
  }, [sections]);

  /**
   * Keep the highlighted chip in view inside the rail.
   *
   * The rail scrolls horizontally and a long menu's chips run well past the
   * right edge, so without this the highlight is frequently off-screen and the
   * rail looks like it is doing nothing. `nearest` rather than `center` so it
   * only moves when it has to.
   */
  useEffect(() => {
    if (!active || !railRef.current) return;
    const chip = railRef.current.querySelector<HTMLElement>(`[data-slug="${active}"]`);
    chip?.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "nearest" });
  }, [active]);

  function reset() {
    onCategoryChange("All");
    setVegOnly(false);
    setQuery("");
  }

  function jumpTo(section: { category: string; slug: string }) {
    // The URL first, so the address reflects where the page is about to be and
    // a reload or a share lands in the same place.
    onCategoryChange(section.category);
    landed.current = section.category;
    jumpToSection(section.slug);
  }

  return (
    <div>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative min-w-0 flex-1">
          <Search className="absolute left-3 top-1/2 size-5 -translate-y-1/2 text-muted" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search a dish, an ingredient, a category…"
            className="h-12 bg-surface pl-10"
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery("")}
              aria-label="Clear search"
              className="absolute right-2 top-1/2 grid size-8 -translate-y-1/2 place-items-center rounded-full text-muted transition-colors hover:bg-surface-alt hover:text-foreground"
            >
              <X className="size-4" />
            </button>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            onClick={() => setVegOnly((v) => !v)}
            aria-pressed={vegOnly}
            className="filter-toggle"
            data-on={vegOnly}
          >
            <Leaf className="size-4" />
            Veg only
          </button>
          {/* A styled listbox rather than a bare <select>.
              The native control opens the operating system's own menu, which on
              Windows is a grey list in a different typeface, different radius
              and different colours to everything around it — the one place the
              app stopped looking like itself. Radix renders the list in the
              page, so it inherits the design, and it keeps the keyboard and
              screen-reader behaviour a hand-rolled menu would lose. */}
          <Select value={sort} onValueChange={(value) => setSort(value as Sort)}>
            <SelectTrigger className="sort-select" aria-label="Sort dishes">
              <SlidersHorizontal className="size-4 shrink-0 text-muted" />
              <SelectValue />
            </SelectTrigger>
            <SelectContent align="end">
              {sorts.map((s) => (
                <SelectItem value={s.value} key={s.value}>
                  {s.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Sticky, because its job is to be reachable from the middle of a long
          menu — a rail that scrolls away with the page is a table of contents
          you have to go back to the top to use. Below the site header, hence
          the offset in the stylesheet rather than top-0 here. */}
      {!loading && !failed && sections.length > 1 && (
        <div className="section-rail" ref={railRef}>
          <nav className="section-rail__track" aria-label="Menu sections">
            {sections.map((section) => (
              <button
                key={section.slug}
                type="button"
                data-slug={section.slug}
                onClick={() => jumpTo(section)}
                aria-current={section.slug === active ? "true" : undefined}
                className={section.slug === active ? "category-pill active" : "category-pill"}
              >
                {section.category}
                <span className="category-pill__count">{section.items.length}</span>
              </button>
            ))}
          </nav>
        </div>
      )}

      {!loading && !failed && (
        <div className="mb-5 mt-4 flex flex-wrap items-center gap-3">
          <p className="result-count text-sm font-semibold text-muted" key={total}>
            {total} {total === 1 ? "dish" : "dishes"}
            {sections.length > 1 && ` across ${sections.length} sections`}
          </p>
          {filtered && (
            <button type="button" onClick={reset} className="clear-filters text-sm">
              Clear filters
            </button>
          )}
        </div>
      )}

      {loading && (
        <div className="menu-grid mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <DishSkeleton key={i} />
          ))}
        </div>
      )}

      {!loading && failed && (
        <div className="state-panel elevated-panel px-6 py-16 text-center">
          <h3 className="font-display text-xl font-extrabold">The menu didn't load</h3>
          <p className="mx-auto mt-2 max-w-sm text-muted">
            We couldn't load the menu right now. Please try again shortly.
          </p>
        </div>
      )}

      {!loading && !failed && sections.length > 0 && (
        <div className="menu-sections">
          {sections.map((section) => (
            <section className="menu-section" key={section.slug}>
              {/* The id is on the heading, not the section, so an anchor lands
                  with the heading at the top of the viewport rather than with
                  the section's top padding filling it. */}
              <h2 className="menu-section__head" id={section.slug}>
                <span className="font-display menu-section__name">{section.category}</span>
                <span className="menu-section__count">
                  {section.items.length} {section.items.length === 1 ? "dish" : "dishes"}
                </span>
              </h2>
              <div className="menu-grid grid gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
                {section.items.map((item, i) => (
                  <div
                    className="rise-in"
                    // Capped at 11 so a section of eighty dishes does not
                    // stagger the last one in four seconds late.
                    style={{ "--i": Math.min(i, 11) } as React.CSSProperties}
                    key={item.id}
                  >
                    <DishCard item={item} />
                  </div>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}

      {!loading && !failed && sections.length === 0 && (
        <div className="state-panel elevated-panel px-6 py-20 text-center">
          <h3 className="font-display text-2xl font-extrabold">Nothing matches that</h3>
          <p className="mx-auto mt-2 max-w-sm text-muted">
            Try a different word, or clear the filters to see the whole menu.
          </p>
          {filtered && (
            <button type="button" onClick={reset} className="clear-filters mt-5">
              Clear filters
            </button>
          )}
        </div>
      )}
    </div>
  );
}
