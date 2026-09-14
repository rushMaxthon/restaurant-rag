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
  portions: Record<string, OptionPortion> = {},
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

    // Counted on each half when the item is split, the same way the server
    // counts it and the same way the options disable themselves. Counting the
    // group's total here let the page offer one topping per half and then
    // refuse to add them: "choose at most 1" about two halves of one pizza.
    const chosen = selected[group.id] ?? [];
    const counts = sideCounts(chosen, portions);
    const isSplit = group.supports_halves && counts.LEFT + counts.RIGHT > 0;
    if (group.max_selection > 0) {
      if (isSplit) {
        if (counts.LEFT > group.max_selection || counts.RIGHT > group.max_selection) {
          return `Choose at most ${group.max_selection} on each half from "${group.title}".`;
        }
      } else if (count > group.max_selection) {
        return `Choose at most ${group.max_selection} from "${group.title}".`;
      }
    }

    // Both halves, or neither. Mirrors the server, which refuses a lone half
    // — the UI will not usually let it get this far, but the UI is a UI.
    if (group.supports_halves) {
      const missing = missingHalf(selected[group.id] ?? [], portions);
      if (missing) {
        return `Choose something for the ${missing} half from "${group.title}", or put it on the whole item.`;
      }
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

/** What a splittable group is currently doing. */
export type PortionMode = "NONE" | "WHOLE" | "SPLIT";

/**
 * Whole, split, or not yet decided.
 *
 * The owner's rule is that a group is one or the other: pick a topping for the
 * whole item and there is nothing left to say about halves; start naming sides
 * and "all of it" stops being one of the two sides.
 *
 * Reads only the options that are actually chosen. Unticking a topping leaves
 * its portion behind in state, and a leftover "LEFT" must not hold the group
 * in split mode by itself.
 */
export function portionMode(
  chosenOptionIds: string[],
  portions: Record<string, OptionPortion>,
): PortionMode {
  if (chosenOptionIds.length === 0) return "NONE";
  const anySplit = chosenOptionIds.some((id) => (portions[id] ?? "WHOLE") !== "WHOLE");
  return anySplit ? "SPLIT" : "WHOLE";
}

/**
 * The half that was left undescribed, or null.
 *
 * Half a pizza and silence about the other half is not an order: the kitchen
 * can read it two ways — bare, or the same as the named side — and the
 * customer meant one of them.
 */
export function missingHalf(
  chosenOptionIds: string[],
  portions: Record<string, OptionPortion>,
): "left" | "right" | null {
  const sides = new Set(
    chosenOptionIds.map((id) => portions[id] ?? "WHOLE").filter((p) => p !== "WHOLE"),
  );
  if (sides.size !== 1) return null;
  return sides.has("LEFT") ? "right" : "left";
}

/** How many chosen options sit on each half, and how many cover all of it. */
export type SideCounts = Record<OptionPortion, number>;

export function sideCounts(
  chosenOptionIds: string[],
  portions: Record<string, OptionPortion>,
): SideCounts {
  const counts: SideCounts = { LEFT: 0, RIGHT: 0, WHOLE: 0 };
  for (const id of chosenOptionIds) counts[portions[id] ?? "WHOLE"] += 1;
  return counts;
}

/**
 * Is there room for one more on this side?
 *
 * The owner's maximum counts on EACH half. "Up to two toppings" on a split
 * pizza means two on the left and two on the right: the halves are two orders
 * of the same size sharing a base, and counting the cap across both sold one
 * topping per side under a cap of two.
 *
 * Set the maximum to 1 and this is exactly "half this, half that, nothing
 * else" — which is the point: the number is the owner's, not the app's, and
 * changing it in admin changes the menu.
 */
export function roomOnSide(
  group: CustomizationGroup,
  counts: SideCounts,
  side: OptionPortion,
): boolean {
  const max = Math.max(0, Number(group.max_selection) || 0);
  return max === 0 || counts[side] < max;
}

/**
 * Which half a newly chosen option should land on.
 *
 * The bare half first: that is the one the customer must fill before the order
 * will go at all. After that, whichever side still has room under the owner's
 * cap — always answering "left" blocked toppings the right half had room for,
 * which is what a cap of two looked like from the outside: two on the left,
 * one on the right, and everything after that refused.
 *
 * When both sides are full it answers left anyway, and the caller refuses the
 * option rather than putting it somewhere it does not fit.
 */
export function nextSideFor(
  group: CustomizationGroup,
  chosenOptionIds: string[],
  portions: Record<string, OptionPortion>,
): OptionPortion {
  const counts = sideCounts(chosenOptionIds, portions);
  if (counts.LEFT === 0 && counts.RIGHT > 0) return "LEFT";
  if (counts.RIGHT === 0 && counts.LEFT > 0) return "RIGHT";
  if (roomOnSide(group, counts, "LEFT")) return "LEFT";
  if (roomOnSide(group, counts, "RIGHT")) return "RIGHT";
  return "LEFT";
}

/**
 * The group's choices, re-expressed for the mode it is switching into.
 *
 * The two modes describe different things, so the choices cannot simply carry
 * over. Reported: one topping on the whole pizza, switch to halves, add a
 * second there, switch back — and BOTH sat on the whole pizza at once, two
 * chosen under a cap of one. Toppings picked for opposite halves have no
 * meaning as a whole-pizza order, and merging them invented one the customer
 * never asked for and the kitchen could not make.
 *
 * So the choices are re-rationed against the cap for the mode being entered,
 * and anything that no longer fits is dropped rather than left over the limit.
 * Dropping is visible — the topping simply unticks — which is the honest
 * outcome: the customer can see what did not survive and put it back.
 */
export function regroupForMode(
  group: CustomizationGroup,
  chosenOptionIds: string[],
  toSplit: boolean,
): { chosen: string[]; portions: Record<string, OptionPortion> } {
  const cap = Math.max(0, Number(group.max_selection) || 0);
  const room = cap === 0 ? Number.POSITIVE_INFINITY : cap;
  const portions: Record<string, OptionPortion> = {};

  if (!toSplit) {
    const chosen = chosenOptionIds.slice(0, room === Infinity ? undefined : room);
    for (const id of chosen) portions[id] = "WHOLE";
    return { chosen, portions };
  }

  // Left first, then right: the left is where a split starts, and filling it
  // before the right keeps "one each" the shape a cap of one produces.
  const chosen: string[] = [];
  let left = 0;
  let right = 0;
  for (const id of chosenOptionIds) {
    if (left < room) {
      portions[id] = "LEFT";
      left += 1;
    } else if (right < room) {
      portions[id] = "RIGHT";
      right += 1;
    } else {
      continue;
    }
    chosen.push(id);
  }
  return { chosen, portions };
}

/**
 * A cart line's chosen options, each labelled with the half it goes on.
 *
 * The cart and the checkout summary listed names alone, so "half pepperoni,
 * half mushroom" and "pepperoni and mushroom all over" looked identical — two
 * different pizzas, at two different prices, shown the same way on the last
 * screens before paying.
 *
 * Ids and names are stored as parallel lists; anything past the end of either
 * is dropped rather than rendered as "undefined", because carts saved before
 * portions existed are still in people's browsers.
 */
export function chosenLabels(
  optionIds: string[],
  optionNames: string[],
  portions: Record<string, OptionPortion> = {},
): string[] {
  return optionNames.slice(0, optionIds.length).map((name, index) => {
    const portion = portions[optionIds[index] as string] ?? "WHOLE";
    return portion === "WHOLE" ? name : `${name} · ${portion === "LEFT" ? "left" : "right"} half`;
  });
}
