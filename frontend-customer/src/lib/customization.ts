import type {
  CustomizationGroup,
  CustomizationOption,
  MenuItem,
  MenuSize,
} from "@/lib/bangkok-data";
import type { OptionPortion } from "@/lib/bangkok-store";

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

/** Two decimal places, rounded the way the server rounds. */
function money(value: number): number {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

/** "Left half", for a customer rather than for a database. */
export function portionLabel(portion: OptionPortion): string {
  if (portion === "LEFT") return "Left half";
  if (portion === "RIGHT") return "Right half";
  return "Whole";
}

/**
 * What one selected option costs, given which part of the item it covers.
 *
 * Mirrors `ResolvedCustomizationOption.charged_extra_price`: a half costs half,
 * quantized to two places. The GROUP's flag decides, not the stored portion —
 * a stale "LEFT" on a group the owner never made splittable must not quietly
 * halve a topping the kitchen will apply in full.
 */
function chargedExtra(
  group: CustomizationGroup,
  option: CustomizationOption,
  portion: OptionPortion,
): number {
  const listed = Number(option.extra_price ?? 0);
  if (!Number.isFinite(listed)) return 0;
  const split = group.supports_halves && portion !== "WHOLE";
  return money(split ? listed / 2 : listed);
}

/** The price of one unit, given a size, the chosen options and their portions. */
export function unitPriceFor(
  item: MenuItem | undefined,
  selectedSize: MenuSize | undefined,
  selectedOptionIds: string[],
  portions: Record<string, OptionPortion> = {},
): number {
  if (!item) return 0;
  // The size price REPLACES the item price. Adding them is the bug.
  const base = Number(selectedSize?.price ?? item.price);

  const chosen = new Set(selectedOptionIds);
  let extras = 0;
  for (const group of visibleGroups(item, selectedSize)) {
    for (const option of activeOptions(group)) {
      if (!chosen.has(option.id)) continue;
      extras += chargedExtra(group, option, portions[option.id] ?? "WHOLE");
    }
  }

  return money((Number.isFinite(base) ? base : 0) + extras);
}

/**
 * The pizza read back as two halves, so the customer can check it at a glance.
 *
 * Names rather than ids: this is for the screen and for the line in the cart,
 * and "Left: Pepperoni · Right: Mushroom" is the thing someone is trying to
 * confirm before paying.
 */
export function splitSummary(
  item: MenuItem | undefined,
  selectedSize: MenuSize | undefined,
  selectedOptionIds: string[],
  portions: Record<string, OptionPortion> = {},
): { left: string[]; right: string[]; whole: string[] } {
  const chosen = new Set(selectedOptionIds);
  const out = { left: [] as string[], right: [] as string[], whole: [] as string[] };
  for (const group of visibleGroups(item, selectedSize)) {
    for (const option of activeOptions(group)) {
      if (!chosen.has(option.id)) continue;
      const portion = group.supports_halves ? (portions[option.id] ?? "WHOLE") : "WHOLE";
      if (portion === "LEFT") out.left.push(option.name);
      else if (portion === "RIGHT") out.right.push(option.name);
      else out.whole.push(option.name);
    }
  }
  return out;
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

/**
 * The group's selection rule, in one sentence, with both numbers in it.
 *
 * The owner sets a minimum and a maximum and the customer used to see neither
 * together: a badge said "Choose 2" and the line under it said "Choose up to
 * 4" — one rule told twice, in two places, agreeing with itself only by
 * accident. An owner who caps toppings at four has said something the customer
 * needs before they pick a fifth, not after.
 */
export function selectionHint(group: CustomizationGroup): string {
  // A single-choice group is one, whatever its stored maximum says; the admin
  // forces max to 1 there, but older rows predate that rule.
  if (group.selection_type === "SINGLE") return "Choose 1";

  const min = Math.max(0, Number(group.min_selection) || 0);
  const max = Math.max(0, Number(group.max_selection) || 0);
  if (min > 0 && max > 0) {
    return min === max ? `Choose exactly ${min}` : `Choose ${min} to ${max}`;
  }
  if (max > 0) return `Choose up to ${max}`;
  if (min > 0) return `Choose at least ${min}`;
  return "Choose any";
}

/**
 * Is there room for another option in this group?
 *
 * Used to stop the customer picking a sixth topping in a group capped at five.
 * The cap was validated only at the Add button before, which let someone build
 * something the kitchen would not make and told them so at the end.
 *
 * A SINGLE group always has room: tapping another option replaces the one
 * chosen rather than adding to it, so a ceiling would lock the group after the
 * first tap.
 */
export function canPickMore(group: CustomizationGroup, chosen: number): boolean {
  if (group.selection_type === "SINGLE") return true;
  const max = Math.max(0, Number(group.max_selection) || 0);
  return max === 0 || chosen < max;
}
