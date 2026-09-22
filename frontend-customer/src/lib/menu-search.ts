import type { MenuItem } from "@/lib/bangkok-data";

/**
 * Does this dish match what somebody typed into the menu search?
 *
 * Extracted from `MenuGrid` because of how it failed there. The predicate read
 * `item.description.toLowerCase()`, the type claimed `description: string`,
 * and the column has always been nullable — so on a menu where 720 of 816
 * rows have no description, typing a single letter threw
 *
 *     TypeError: Cannot read properties of null (reading 'toLowerCase')
 *
 * which took the whole grid down and left the customer looking at the error
 * boundary's empty page. Nothing about that was visible to the compiler, and
 * nothing tested it, because it lived inside a `useMemo` inside a component
 * that needs a store, a query client and a router to render at all.
 *
 * Name, description and category are all searched: "something with peanuts"
 * is the kind of thing people type into a food search, and it is in the
 * description or nowhere.
 */
export function matchesQuery(
  item: Pick<MenuItem, "name" | "description" | "category">,
  needle: string,
): boolean {
  const wanted = needle.trim().toLowerCase();
  if (!wanted) {
    return true;
  }
  // Every field is coalesced, not just the one that was null in the data we
  // happened to have: a menu row is a database row, and any of its text
  // columns can arrive empty.
  return [item.name, item.description, item.category].some((field) =>
    (field ?? "").toLowerCase().includes(wanted),
  );
}
