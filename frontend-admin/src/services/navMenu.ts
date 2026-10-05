/**
 * The sidebar's behaviour, apart from the sidebar so it can be tested.
 *
 * Two smart things the old flat list could not do: find a page by typing,
 * and fold away the groups somebody is not using - without ever folding away
 * the group they are standing in.
 */
import type { NavGroup, NavItem, NavSection } from "../routes";

function normalise(text: string): string {
  return text.toLowerCase().replace(/\s+/g, " ").trim();
}

/**
 * How well an item answers a search, or 0 for not at all.
 *
 * The label beats a keyword, and the start of a word beats the middle of
 * one: "or" should put Orders above Storefront content.
 */
export function matchScore(item: NavItem, query: string): number {
  const wanted = normalise(query);
  if (!wanted) return 1;
  const label = normalise(item.label);
  if (label.startsWith(wanted)) return 4;
  if (label.split(" ").some((word) => word.startsWith(wanted))) return 3;
  if (label.includes(wanted)) return 2;
  return item.keywords.some((word) => normalise(word).includes(wanted)) ? 1 : 0;
}

/** The groups, with only what matches the search, and nothing empty. */
export function filterNav(groups: NavGroup[], query: string): NavGroup[] {
  if (!normalise(query)) return groups;
  return groups
    .map((group) => ({
      ...group,
      items: group.items
        .map((item) => ({ item, score: matchScore(item, query) }))
        .filter((entry) => entry.score > 0)
        .sort((a, b) => b.score - a.score)
        .map((entry) => entry.item),
    }))
    .filter((group) => group.items.length > 0);
}

/** The best match across every group: where Enter in the search box goes. */
export function bestMatch(groups: NavGroup[], query: string): NavItem | null {
  let best: { item: NavItem; score: number } | null = null;
  for (const group of groups) {
    for (const item of group.items) {
      const score = matchScore(item, query);
      if (score > 0 && (!best || score > best.score)) best = { item, score };
    }
  }
  return best?.item ?? null;
}

/**
 * Whether a group is shown open.
 *
 * Always open while searching (the results are the point), always open when
 * it holds the current page (a highlighted item inside a closed group is a
 * page you cannot see where you are on), and otherwise whatever the person
 * last chose - open, if they never chose.
 */
export function isGroupOpen(
  section: NavSection,
  {
    closed,
    activeSection,
    searching,
  }: { closed: ReadonlySet<NavSection>; activeSection: NavSection | null; searching: boolean },
): boolean {
  if (searching || section === activeSection) return true;
  return !closed.has(section);
}

const STORAGE_KEY = "admin-nav-closed";

export function readClosedGroups(): Set<NavSection> {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return new Set(raw ? (JSON.parse(raw) as NavSection[]) : []);
  } catch {
    return new Set();
  }
}

export function writeClosedGroups(closed: ReadonlySet<NavSection>): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify([...closed]));
  } catch {
    // Private mode: groups simply open again next visit.
  }
}
