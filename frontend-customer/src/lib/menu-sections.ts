import type { MenuItem } from "@/lib/bangkok-data";
import { matchesQuery } from "@/lib/menu-search";

/**
 * A menu as a sequence of sections rather than one filtered list.
 *
 * **Why this replaced filtering by category.** The grid used to show exactly
 * one category at a time, chosen from a rail of chips. That is a fine control
 * and a poor menu: a customer could not see what the kitchen does without
 * clicking through twenty-one chips one at a time, and the shape of the menu —
 * that there are four biryanis and thirty sweets — was invisible. A paper menu
 * has never worked that way, and neither does any food site anybody actually
 * uses: the sections are all there, in order, and the category rail JUMPS to
 * one rather than hiding the rest.
 *
 * So the rail became navigation and the sections became the content. Search
 * and the veg filter still subtract — they are questions about which dishes
 * qualify, which is a different thing from where you want to look.
 *
 * Pure and here rather than inside the component for the reason the search
 * predicate moved out before it: a `useMemo` inside a component that needs a
 * store, a query client and a router cannot be tested, and the last rule that
 * lived there crashed the whole grid on a null description.
 */
export type MenuSection = {
  category: string;
  /** Stable DOM id, so the rail can scroll to the heading. */
  slug: string;
  items: MenuItem[];
};

/**
 * A category name as a DOM id.
 *
 * Deliberately not just a slugified name: two different categories can
 * slugify to the same string ("Thali / Combo" and "Thali & Combo" both become
 * `thali-combo`), and a duplicate id means the rail scrolls to whichever came
 * first. The prefix makes these ids obviously ours, so they cannot collide
 * with anything else on the page; `dedupe` below handles the rest.
 */
export function sectionSlug(category: string): string {
  const base = category
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return `menu-${base || "section"}`;
}

/** Appends -2, -3 … to any slug already taken, in order. */
function dedupe(slugs: string[]): string[] {
  const seen = new Map<string, number>();
  return slugs.map((slug) => {
    const count = (seen.get(slug) ?? 0) + 1;
    seen.set(slug, count);
    return count === 1 ? slug : `${slug}-${count}`;
  });
}

export type SectionOptions = {
  /** Free text; matched against name, category and description. */
  query?: string;
  vegOnly?: boolean;
  /** Within a section. Section ORDER is always the kitchen's own. */
  compare?: (a: MenuItem, b: MenuItem) => number;
};

/**
 * The menu, grouped into the sections the kitchen put it in.
 *
 * Section order is the order the categories first appear in the menu payload,
 * which is the kitchen's own ordering — starters before mains because that is
 * how it was entered. Sorting the sections alphabetically would be tidier and
 * wrong: it would put Desserts above Mains on every menu on the platform.
 *
 * **A section with nothing left in it is dropped, not shown empty.** Searching
 * "paneer" on a twenty-one section menu otherwise produces nineteen headings
 * with nothing under them, and the three results are somewhere in the middle
 * of it.
 */
export function buildSections(items: MenuItem[], options: SectionOptions = {}): MenuSection[] {
  const needle = (options.query ?? "").trim().toLowerCase();
  const order: string[] = [];
  const grouped = new Map<string, MenuItem[]>();

  for (const item of items) {
    if (options.vegOnly && !item.is_veg) continue;
    if (!matchesQuery(item, needle)) continue;
    const category = item.category;
    let bucket = grouped.get(category);
    if (!bucket) {
      bucket = [];
      grouped.set(category, bucket);
      order.push(category);
    }
    bucket.push(item);
  }

  const slugs = dedupe(order.map(sectionSlug));
  return order.map((category, index) => {
    const bucket = grouped.get(category) ?? [];
    return {
      category,
      slug: slugs[index]!,
      // Copied before sorting: `bucket` holds references into the query's
      // cached array, and sorting in place would reorder TanStack Query's own
      // data — which other screens read.
      items: options.compare ? [...bucket].sort(options.compare) : bucket,
    };
  });
}

/** Every dish across the sections, for a count that matches what is on screen. */
export function countItems(sections: MenuSection[]): number {
  return sections.reduce((total, section) => total + section.items.length, 0);
}

/**
 * Which section a rail chip should mark as current.
 *
 * Takes each section's distance from the top of the VIEWPORT — what
 * `getBoundingClientRect().top` returns — and the line below the sticky
 * chrome. The answer is the last section that has already passed that line,
 * which is the one filling the screen under it.
 *
 * **This was an IntersectionObserver first, and it was wrong twice.** Observing
 * the HEADINGS meant a normal wheel flick moved the page further between
 * sampled frames than a 50px heading is tall, so the detection band jumped
 * clean over every one of them and the rail never moved — it looked exactly
 * like a dead control. Observing the sections instead fixed that, and left a
 * second problem that is worse: an observer only delivers while the tab is
 * rendering, so the behaviour cannot be verified in a background tab and a
 * reader has to take the rootMargin arithmetic on trust.
 *
 * Reading positions is neither. It cannot skip a section, because it does not
 * depend on catching one mid-flight; and it is a pure function of numbers,
 * which is why the cases below are tested rather than argued about. Nineteen
 * rect reads inside one rAF is not the cost an observer was protecting us from.
 *
 * Returns null when nothing has passed the line yet — the top of the page,
 * before the first section — rather than pretending the first one is current.
 */
export function activeSection(
  sections: MenuSection[],
  /** Viewport-relative top of each section, in the same order as `sections`. */
  tops: number[],
  /** Where the sticky header and rail stop covering the page. */
  line: number,
): string | null {
  let found: string | null = null;
  for (let index = 0; index < sections.length; index += 1) {
    const top = tops[index];
    if (top === undefined) continue;
    // `<=` so a section whose heading is exactly on the line counts as
    // current rather than as still-to-come.
    if (top <= line) found = sections[index]!.slug;
    // Sections are in document order, so the first one still below the line
    // means every later one is too.
    else break;
  }
  return found;
}
