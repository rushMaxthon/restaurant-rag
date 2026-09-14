import type {
  CustomizationGroup,
  CustomizationOption,
  MenuItem,
  MenuSize,
} from "@/lib/bangkok-data";

/**
 * The rules for sized and customisable items, in one place.
 *
 * `MENU_ITEM_CUSTOMIZATION_FLOW.md` is the authority and the backend
 * (`services/menu_item_customizations.py`) enforces it. Everything here mirrors
 * that deliberately rather than inventing a second set of rules: when the two
 * disagree the customer sees one number and is charged another, which is the
 * bug this module exists to stop.
 *
 * What was wrong before:
 *
 *  - the size price was ADDED to the item price instead of replacing it, so a
 *    $12 bowl with a $15 Large read $27 all the way to the Pay button while
 *    Stripe charged $15;
 *  - sizes and options the owner had switched off were rendered and selectable;
 *  - groups scoped to one size were shown against every size, which looked like
 *    duplicates;
 *  - a group marked "not required" with `min_selection: 1` was treated as
 *    optional by the screen and required by the server.
 */

/** Sizes the customer may actually pick. */
export function activeSizes(item: MenuItem | undefined): MenuSize[] {
  return (item?.sizes ?? []).filter((size) => size.is_active);
}

/** Options the customer may actually pick. */
export function activeOptions(group: CustomizationGroup): CustomizationOption[] {
  return (group.options ?? []).filter((option) => option.is_active);
}

/**
 * The groups that apply to this item with this size selected.
 *
 * Mirrors `_get_active_customization_groups`: item-level groups are those with
 * no `menu_item_size_id`, plus the selected size's own groups, deduped by id.
 * Without the size filter a group belonging to Large showed up under Regular
 * too, and a group listed in both places appeared twice.
 */
export function visibleGroups(
  item: MenuItem | undefined,
  selectedSize: MenuSize | undefined,
): CustomizationGroup[] {
  if (!item) return [];
  const itemLevel = (item.customization_groups ?? []).filter(
    (group) => !group.menu_item_size_id && group.is_active,
  );
  const sizeLevel = (selectedSize?.customization_groups ?? []).filter((group) => group.is_active);

  const seen = new Set<string>();
  const out: CustomizationGroup[] = [];
  for (const group of [...itemLevel, ...sizeLevel]) {
    if (seen.has(group.id)) continue;
    seen.add(group.id);
    out.push(group);
  }
  return out;
}

/**
 * Whether this group must be answered before the item can be ordered.
 *
 * `is_required` OR a minimum above zero. The minimum is what the server
 * actually enforces, so a group flagged "not required" with `min_selection: 1`
 * is required in practice — and labelling it optional only means the customer
 * discovers that at the end.
 */
export function requiresChoosing(group: CustomizationGroup): boolean {
  return group.is_required || group.min_selection > 0;
}

/** The price of one unit, given a size and the chosen option ids. */
export function unitPriceFor(
  item: MenuItem | undefined,
  selectedSize: MenuSize | undefined,
  selectedOptionIds: string[],
): number {
  if (!item) return 0;
  // The size price REPLACES the item price. Adding them is the bug.
  const base = Number(selectedSize?.price ?? item.price);

  const chosen = new Set(selectedOptionIds);
  const extras = visibleGroups(item, selectedSize)
    .flatMap((group) => activeOptions(group))
    .filter((option) => chosen.has(option.id))
    .reduce((sum, option) => sum + Number(option.extra_price ?? 0), 0);

  return (Number.isFinite(base) ? base : 0) + extras;
}

/**
 * Why this item cannot be added yet, phrased for the customer, or null.
 *
 * One function rather than a boolean so the screen can SAY what is missing.
 * "Add to cart" that is simply greyed out is the dead end this codebase keeps
 * finding.
 */
export function selectionProblem(
  item: MenuItem | undefined,
  selectedSize: MenuSize | undefined,
  selected: Record<string, string[]>,
): string | null {
  if (!item) return null;

  if (activeSizes(item).length > 0 && !selectedSize) {
    return "Choose a size to continue.";
  }

  for (const group of visibleGroups(item, selectedSize)) {
    const available = activeOptions(group).length;
    const count = (selected[group.id] ?? []).length;

    // Bad data, not a bad customer. A minimum no number of options can satisfy
    // makes the item unorderable, and telling someone to "choose 3" from a list
    // of one just leaves them clicking.
    if (group.min_selection > available) {
      return `"${group.title}" cannot be ordered right now — please pick another item.`;
    }

    if (requiresChoosing(group) && count < Math.max(group.min_selection, 1)) {
      const needed = Math.max(group.min_selection, 1);
      return needed > 1
        ? `Choose ${needed} from "${group.title}".`
        : `Choose an option from "${group.title}".`;
    }

    if (group.max_selection > 0 && count > group.max_selection) {
      return `Choose at most ${group.max_selection} from "${group.title}".`;
    }
  }

  return null;
}
