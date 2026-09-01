import type { IconName } from '../AppIcon';

/**
 * `mobile/src/components/home/CategoryCarousel.tsx`.
 *
 * The tiles are the phone's, but what fills them is not. The marketplace app
 * ships a fixed list — Pizza, Burgers, Chinese — because it is choosing between
 * restaurants. A single-restaurant app is choosing between sections of one
 * kitchen's menu, so the categories are read off the menu itself: Bangkok Bowl
 * offers Curry, Noodles and Soup, and a "Pizza" chip that matched nothing would
 * be worse than no chip at all.
 */
export interface HomeCategory {
  id: string;
  label: string;
  icon: IconName;
  /** The chip's glyph. Emoji, because a menu section is a food, and the app's
      line-icon set has no drawing of a bowl of curry — a "receipt" standing in
      for Noodles told the reader nothing. */
  emoji: string;
}

/** A glyph per menu section, falling back to a neutral one. */
const CATEGORY_ICONS: Array<[RegExp, IconName]> = [
  [/dessert|sweet|ice/i, 'ticket'],
  [/bever|drink|juice|tea|coffee|shake/i, 'card'],
  [/curry|gravy/i, 'home'],
  [/noodle|pasta|rice|biryani/i, 'receipt'],
  [/soup|broth/i, 'time'],
  [/salad|healthy|veg/i, 'heart'],
  [/combo|meal|thali/i, 'bag'],
  [/starter|appetiz|snack|side/i, 'star'],
];

function iconFor(label: string): IconName {
  return CATEGORY_ICONS.find(([pattern]) => pattern.test(label))?.[1] ?? 'options';
}

/** The same table, read as food. Order matters: the first match wins, so the
    narrow patterns are listed before the ones that would swallow them. */
const CATEGORY_EMOJI: Array<[RegExp, string]> = [
  [/dessert|sweet|ice ?cream|pudding|cake/i, '\u{1F368}'],
  [/coffee|latte|espresso/i, '\u{2615}'],
  [/tea|chai/i, '\u{1F375}'],
  [/shake|smoothie|lassi/i, '\u{1F964}'],
  [/bever|drink|juice|soda|mocktail/i, '\u{1F379}'],
  [/curry|gravy|masala/i, '\u{1F35B}'],
  [/noodle|pasta|hakka|chow/i, '\u{1F35C}'],
  [/rice|biryani|fried ?rice/i, '\u{1F35A}'],
  [/soup|broth/i, '\u{1F372}'],
  [/salad|healthy/i, '\u{1F957}'],
  [/combo|thali|meal ?box/i, '\u{1F371}'],
  [/main ?course|entree/i, '\u{1F37D}\u{FE0F}'],
  [/starter|appetiz|snack|side/i, '\u{1F359}'],
  [/pizza/i, '\u{1F355}'],
  [/burger|sandwich|roll|wrap/i, '\u{1F354}'],
  [/veg/i, '\u{1F966}'],
  [/chicken|meat|non.?veg|seafood|fish|prawn/i, '\u{1F357}'],
  [/bread|naan|roti/i, '\u{1F956}'],
];

function emojiFor(label: string): string {
  return CATEGORY_EMOJI.find(([pattern]) => pattern.test(label))?.[1] ?? '\u{1F37D}\u{FE0F}';
}

/**
 * Build the rail from what the kitchen actually serves, commonest section
 * first, with "All" pinned in front the way the phone pins it.
 */
export function buildMenuCategories(
  items: Array<{ category?: string | null }>,
): HomeCategory[] {
  const counts = new Map<string, number>();
  for (const item of items) {
    const label = (item.category ?? '').trim();
    if (!label) {
      continue;
    }
    // Seeded data mixes casing ("Curry" and "manchurian"), so sections are
    // keyed case-insensitively and displayed with the first spelling seen.
    const key = label.toLowerCase();
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }

  const labels = new Map<string, string>();
  for (const item of items) {
    const label = (item.category ?? '').trim();
    if (label && !labels.has(label.toLowerCase())) {
      labels.set(label.toLowerCase(), label.replace(/^./, (c) => c.toUpperCase()));
    }
  }

  const sections = [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([key]) => ({
      id: key,
      label: labels.get(key) ?? key,
      icon: iconFor(key),
      emoji: emojiFor(key),
    }));

  return [{ id: 'all', label: 'All', icon: 'sparkles', emoji: '\u{2728}' }, ...sections];
}

