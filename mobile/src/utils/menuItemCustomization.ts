import type {
  CartSelectedOption,
  CartSelectedSize,
  DecimalValue,
  MenuItem,
  MenuItemCustomizationGroup,
  MenuItemCustomizationOption,
  MenuItemPortion,
  MenuItemSize,
} from '@/types/app';

/**
 * Half-and-half rules, mirroring `frontend-customer/src/lib/customization.ts`
 * and the backend that enforces them (`services/menu_item_customizations.py`).
 *
 * Deliberately a copy of the web rules rather than a second set: when the two
 * disagree the customer sees one number and is charged another. The rules the
 * three of them share:
 *
 *  - only a group the owner marked `supports_halves` may be split at all;
 *  - a half costs half the listed extra, quantized to two places;
 *  - a group is split OR the same all over, never both;
 *  - a lone half is not an order — both sides must be described;
 *  - the group's maximum counts on EACH half, not across the pair.
 */

export function toNumber(value: DecimalValue): number {
  return typeof value === 'number' ? value : Number(value);
}

export function isCustomizableMenuItem(menuItem: MenuItem): boolean {
  return menuItem.has_sizes || menuItem.has_customizations;
}

export function getActiveSizes(menuItem: MenuItem): MenuItemSize[] {
  return (menuItem.sizes ?? []).filter(size => size.is_active);
}

export function getDefaultSelectedSize(menuItem: MenuItem): CartSelectedSize | null {
  const size = getActiveSizes(menuItem)[0];
  if (!size) {
    return null;
  }
  return {
    id: size.id,
    name: size.name,
    price: size.price,
  };
}

export function getActiveCustomizationGroups(
  menuItem: MenuItem,
  selectedSizeId: string | null,
): MenuItemCustomizationGroup[] {
  if (menuItem.has_sizes) {
    const size = (menuItem.sizes ?? []).find(
      entry => entry.id === selectedSizeId && entry.is_active,
    );
    return [
      ...(menuItem.customization_groups ?? []),
      ...(size?.customization_groups ?? []),
    ].filter(group => group.is_active);
  }
  return (menuItem.customization_groups ?? []).filter(group => group.is_active);
}

/** Whether this group may be split across two halves at all. */
export function groupSupportsHalves(
  group: MenuItemCustomizationGroup,
): boolean {
  // MULTI only: splitting a single-choice group would mean two answers to a
  // question that takes one, which is what the web control does too.
  return Boolean(group.supports_halves) && group.selection_type === 'MULTI';
}

/** The portion a selection is on, treating a missing value as the whole item. */
export function portionOf(option: CartSelectedOption): MenuItemPortion {
  return option.portion ?? 'WHOLE';
}

/** "Left half", for a customer rather than for a database. */
export function portionLabel(portion: MenuItemPortion): string {
  if (portion === 'LEFT') return 'Left half';
  if (portion === 'RIGHT') return 'Right half';
  return 'Whole';
}

/** Two decimal places, rounded the way the server rounds. */
function money(value: number): number {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

/**
 * What one selected option costs, given which part of the item it covers.
 *
 * Mirrors `ResolvedCustomizationOption.charged_extra_price`. The GROUP's flag
 * decides, not the stored portion — a stale 'LEFT' on a group the owner never
 * made splittable must not quietly halve a topping applied in full.
 */
export function chargedExtraPrice(
  group: MenuItemCustomizationGroup | null,
  extraPrice: DecimalValue,
  portion: MenuItemPortion,
): number {
  const listed = toNumber(extraPrice);
  if (!Number.isFinite(listed)) {
    return 0;
  }
  const split =
    group != null && Boolean(group.supports_halves) && portion !== 'WHOLE';
  return money(split ? listed / 2 : listed);
}

/** How many chosen options sit on each half, and how many cover all of it. */
export type SideCounts = Record<MenuItemPortion, number>;

export function getSideCounts(selections: CartSelectedOption[]): SideCounts {
  const counts: SideCounts = { LEFT: 0, RIGHT: 0, WHOLE: 0 };
  for (const selection of selections) {
    counts[portionOf(selection)] += 1;
  }
  return counts;
}

/**
 * Is there room for one more on this side?
 *
 * The owner's maximum counts on EACH half. "Up to two toppings" on a split
 * item means two on the left and two on the right: the halves are two orders
 * of the same size sharing a base, and counting the cap across both sold one
 * topping per side under a cap of two.
 */
export function roomOnSide(
  group: MenuItemCustomizationGroup,
  counts: SideCounts,
  side: MenuItemPortion,
): boolean {
  const max = Math.max(0, Number(group.max_selection) || 0);
  return max === 0 || counts[side] < max;
}

/**
 * Which half a newly chosen option should land on.
 *
 * The bare half first: that is the one the customer must fill before the order
 * will go at all. After that, whichever side still has room under the owner's
 * cap — always answering LEFT blocked toppings the right half had room for.
 *
 * When both sides are full it answers LEFT anyway, and the caller refuses the
 * option rather than putting it somewhere it does not fit.
 */
export function nextSideFor(
  group: MenuItemCustomizationGroup,
  selections: CartSelectedOption[],
): MenuItemPortion {
  const counts = getSideCounts(selections);
  if (counts.LEFT === 0 && counts.RIGHT > 0) return 'LEFT';
  if (counts.RIGHT === 0 && counts.LEFT > 0) return 'RIGHT';
  if (roomOnSide(group, counts, 'LEFT')) return 'LEFT';
  if (roomOnSide(group, counts, 'RIGHT')) return 'RIGHT';
  return 'LEFT';
}

/**
 * The half that was left undescribed, or null.
 *
 * Half an item and silence about the other half is not an order: the kitchen
 * can read it two ways — bare, or the same as the named side — and the
 * customer meant one of them.
 */
export function missingHalf(
  selections: CartSelectedOption[],
): 'left' | 'right' | null {
  const sides = new Set(
    selections.map(portionOf).filter(portion => portion !== 'WHOLE'),
  );
  if (sides.size !== 1) return null;
  return sides.has('LEFT') ? 'right' : 'left';
}

/** Whether this group is currently split across halves. */
export function isGroupSplit(selections: CartSelectedOption[]): boolean {
  return selections.some(selection => portionOf(selection) !== 'WHOLE');
}

/**
 * The group's choices, re-expressed for the mode it is switching into.
 *
 * The two modes describe different things, so the choices cannot simply carry
 * over. One topping on the whole item, switch to halves, add a second there,
 * switch back — and BOTH would sit on the whole item at once, two chosen under
 * a cap of one. So the choices are re-rationed against the cap for the mode
 * being entered, and anything that no longer fits is dropped rather than left
 * over the limit. Dropping is visible — the topping simply unticks.
 */
export function regroupForMode(
  group: MenuItemCustomizationGroup,
  selections: CartSelectedOption[],
  toSplit: boolean,
): CartSelectedOption[] {
  const cap = Math.max(0, Number(group.max_selection) || 0);
  const room = cap === 0 ? Number.POSITIVE_INFINITY : cap;

  if (!toSplit) {
    const kept =
      room === Number.POSITIVE_INFINITY
        ? selections
        : selections.slice(0, room);
    return kept.map(selection => ({ ...selection, portion: 'WHOLE' as const }));
  }

  // Left first, then right: the left is where a split starts, and filling it
  // before the right keeps "one each" the shape a cap of one produces.
  const out: CartSelectedOption[] = [];
  let left = 0;
  let right = 0;
  for (const selection of selections) {
    if (left < room) {
      out.push({ ...selection, portion: 'LEFT' });
      left += 1;
    } else if (right < room) {
      out.push({ ...selection, portion: 'RIGHT' });
      right += 1;
    }
  }
  return out;
}

/**
 * The item read back as two halves, so the customer can check it at a glance.
 *
 * Names rather than ids: this is for the screen and for the line in the cart,
 * and "Left: Pepperoni · Right: Mushroom" is the thing someone is trying to
 * confirm before paying.
 */
export function splitSummary(selectedOptions: CartSelectedOption[]): {
  left: string[];
  right: string[];
  whole: string[];
} {
  const out = {
    left: [] as string[],
    right: [] as string[],
    whole: [] as string[],
  };
  for (const selection of selectedOptions) {
    const portion = portionOf(selection);
    if (portion === 'LEFT') out.left.push(selection.optionName);
    else if (portion === 'RIGHT') out.right.push(selection.optionName);
    else out.whole.push(selection.optionName);
  }
  return out;
}

export function findCustomizationOption(
  menuItem: MenuItem,
  selectedSizeId: string | null,
  optionId: string,
): {group: MenuItemCustomizationGroup; option: MenuItemCustomizationOption} | null {
  const groups = getActiveCustomizationGroups(menuItem, selectedSizeId);
  for (const group of groups) {
    const option = group.options.find(entry => entry.id === optionId && entry.is_active);
    if (option) {
      return {group, option};
    }
  }
  return null;
}

export function buildLineItemId(input: {
  menuItemId: string;
  selectedSizeId: string | null;
  selectedOptions: CartSelectedOption[];
}): string {
  // The portion is part of what makes a line distinct: half pepperoni and
  // whole pepperoni are two different pizzas, and without it the second would
  // silently increment the quantity of the first.
  //
  // Appended only when it is NOT whole, so every line built before halves
  // existed keeps the exact id it was persisted under — a changed id would
  // orphan the cart already on someone's phone.
  const optionSignature = [...input.selectedOptions]
    .sort((left, right) => left.optionId.localeCompare(right.optionId))
    .map(option => {
      const portion = portionOf(option);
      const base = `${option.optionId}:${option.quantity}`;
      return portion === 'WHOLE' ? base : `${base}:${portion}`;
    })
    .join('|');
  return `${input.menuItemId}::${input.selectedSizeId ?? 'default'}::${optionSignature}`;
}

export function calculateUnitPrice(input: {
  menuItem: MenuItem;
  selectedSize: CartSelectedSize | null;
  selectedOptions: CartSelectedOption[];
}): number {
  const basePrice = input.selectedSize
    ? toNumber(input.selectedSize.price)
    : toNumber(input.menuItem.price);
  // Resolved from the live item rather than from the cart line, so a group the
  // owner has since stopped splitting stops being charged at half price here
  // the same moment it does on the server.
  const groupsById = new Map(
    getActiveCustomizationGroups(
      input.menuItem,
      input.selectedSize?.id ?? null,
    ).map(group => [group.id, group]),
  );
  const optionTotal = input.selectedOptions.reduce(
    (total, option) =>
      total +
      chargedExtraPrice(
        groupsById.get(option.groupId) ?? null,
        option.extraPrice,
        portionOf(option),
      ) *
        option.quantity,
    0,
  );
  return Number((basePrice + optionTotal).toFixed(2));
}

export function formatCustomizationSummary(
  selectedSize: CartSelectedSize | null,
  selectedOptions: CartSelectedOption[],
): string[] {
  const lines: string[] = [];
  if (selectedSize) {
    lines.push(selectedSize.name);
  }
  for (const option of selectedOptions) {
    // "Pepperoni · left half" rather than "Pepperoni": half-and-half and the
    // same-all-over version of one item are two different orders at two
    // different prices, and the cart used to show them identically.
    const portion = portionOf(option);
    const name =
      option.quantity > 1
        ? `${option.optionName} x${option.quantity}`
        : option.optionName;
    lines.push(
      portion === 'WHOLE'
        ? name
        : `${name} · ${portion === 'LEFT' ? 'left' : 'right'} half`,
    );
  }
  return lines;
}

export function validateCustomizationSelection(input: {
  menuItem: MenuItem;
  selectedSize: CartSelectedSize | null;
  selectedOptions: CartSelectedOption[];
}): string | null {
  if (input.menuItem.has_sizes && !input.selectedSize) {
    return 'Please select a size.';
  }

  const groups = getActiveCustomizationGroups(
    input.menuItem,
    input.selectedSize?.id ?? null,
  );
  const optionsByGroup = new Map<string, CartSelectedOption[]>();
  for (const option of input.selectedOptions) {
    const current = optionsByGroup.get(option.groupId) ?? [];
    current.push(option);
    optionsByGroup.set(option.groupId, current);
    if (option.quantity < 1) {
      return `${option.optionName} quantity must be at least 1.`;
    }
    if (!option.isCountable && option.quantity !== 1) {
      return `${option.optionName} cannot use a quantity higher than 1.`;
    }
  }

  for (const group of groups) {
    const selections = optionsByGroup.get(group.id) ?? [];
    const count = selections.length;
    const counts = getSideCounts(selections);
    const split = counts.LEFT + counts.RIGHT > 0;

    // A portion on a group the owner never made splittable is refused by the
    // server, so refuse it here rather than at the end of checkout.
    if (split && !group.supports_halves) {
      return `${group.title} cannot be applied to half of this item.`;
    }
    // Once something covers the whole item there is nothing left to decide
    // about halves, and once it is being split, "all of it" is not one of the
    // two sides.
    if (split && counts.WHOLE > 0) {
      return `${group.title} is either split across halves or the same on all of it — not both.`;
    }
    // Half an item and silence about the other half. The kitchen can read that
    // two ways and the customer meant one of them.
    const missing = missingHalf(selections);
    if (missing) {
      return `Choose something for the ${missing} half from ${group.title}, or put it on the whole item.`;
    }

    if (group.selection_type === 'SINGLE' && count > 1) {
      return `${group.title} allows only one selection.`;
    }
    if (group.is_required && count < Math.max(group.min_selection, 1)) {
      return `${group.title} requires at least one selection.`;
    }
    if (count < group.min_selection) {
      return `${group.title} requires at least ${group.min_selection} selections.`;
    }
    // Counted on each half when the item is split, the same way the server
    // counts it: a cap of two on a split item means two per side, and counting
    // it across both sold one topping per side.
    if (split) {
      if (
        counts.LEFT > group.max_selection ||
        counts.RIGHT > group.max_selection
      ) {
        return `${group.title} allows at most ${group.max_selection} on each half.`;
      }
    } else if (count > group.max_selection) {
      return `${group.title} allows at most ${group.max_selection} selections.`;
    }
  }
  return null;
}
