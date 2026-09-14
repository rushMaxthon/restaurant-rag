import type { CartLine } from "@/lib/bangkok-store";

export type SellSuggestion = {
  kind: string;
  basis: string;
  menu_item_id?: string | null;
  combo_id?: string | null;
  size_id?: string | null;
  customization_option_id?: string | null;
  saving?: string | null;
  extra_cost?: string | null;
};

export type CartLineRequest = {
  menu_item_id: string;
  quantity: number;
  size_id: string | undefined;
  customization_option_ids: string[];
};

/**
 * Identifiers only.
 *
 * Sending names or prices would give the reply a second source of truth for
 * both, and the one that disagrees with the menu page is always the one the
 * customer notices.
 */
export function cartLinesForRequest(cart: CartLine[]): CartLineRequest[] {
  return cart.map((line) => ({
    menu_item_id: line.itemId,
    quantity: line.quantity,
    size_id: line.sizeId,
    customization_option_ids: line.optionIds,
  }));
}

/**
 * Maps category names to natural nouns for category-level claims.
 *
 * Used only in `category_default` to make the popularity claim sit on the
 * category ("drink") rather than the specific item ("Thai Iced Tea"), since
 * a fallback was chosen by absence of evidence, not by evidence that people
 * specifically want that item.
 */
function categoryNoun(category: string | null | undefined): string | null {
  const map: Record<string, string> = {
    "Beverages": "drink",
    "Dessert": "something sweet",
  };
  return (category && map[category]) ?? null;
}

/**
 * What the prompt says, chosen by `basis` and nothing else.
 *
 * The client does not get to invent a reason. A mined pairing has evidence
 * behind it and may say so; a category default is a guess and must read like
 * one. Wording them alike would present a guess as a measurement.
 *
 * For `category_default`, the popularity claim sits on the category, not the
 * item, because the item was chosen by absence of evidence (fallback), not by
 * evidence that people want it. If the category cannot be named naturally,
 * omit the popularity claim entirely.
 */
export function suggestionCopy(
  suggestion: SellSuggestion,
  itemName: string,
  category?: string | null,
): string {
  switch (suggestion.basis) {
    case "co_occurrence":
      return `Often ordered with what you've got — ${itemName}?`;
    case "category_default": {
      const noun = categoryNoun(category);
      return noun ? `Most people add a ${noun} — ${itemName}?` : `${itemName}?`;
    }
    case "combo_upgrade": {
      const saving = suggestion.saving?.trim();
      return saving ? `Make it the ${itemName} and save ${saving}.` : `Make it the ${itemName}.`;
    }
    case "size_upgrade": {
      const cost = suggestion.extra_cost?.trim();
      return cost ? `Would you like a bigger size? ${cost} more for the ${itemName}.` : `Would you like a bigger size of the ${itemName}?`;
    }
    case "add_on":
      return `Add ${itemName}?`;
    default:
      // A basis this build does not know about still has to render something
      // a person can read, rather than "undefined".
      return `${itemName}?`;
  }
}

/** The only two fields `suggestionNeedsChoice` needs from a menu item. */
export type MenuItemChoiceFlags = {
  has_sizes: boolean;
  has_customizations: boolean;
};

/**
 * Whether a one-line prompt can honour this suggestion with a plain "Add", or
 * has to send the customer to the dish page instead.
 *
 * Two separate reasons land on the same answer, and both trace back to the
 * rule `dish-card.tsx` already states: a card has nothing to choose a size or
 * an add-on with, so adding blind means guessing, and a guess here is either
 * wrong or a silent default the customer never agreed to.
 *
 *  - `size_upgrade` and `add_on` are not "add this item" at all — the item is
 *    already in the cart, and the suggestion IS the size or the customization
 *    option to change it to. Those live in `size_id` / `customization_option_id`
 *    on the suggestion, not on a menu item `addItem` knows how to read, so
 *    there is no blind `addItem` that could ever be correct for these bases.
 *  - `co_occurrence` and `category_default` name a plain second item — but if
 *    THAT item itself has sizes or customizations, adding it blind is the
 *    exact same silent default `dish-card.tsx` refuses to make, just reached
 *    from a different basis.
 */
export function suggestionNeedsChoice(
  suggestion: Pick<SellSuggestion, "basis">,
  item: MenuItemChoiceFlags,
): boolean {
  if (suggestion.basis === "size_upgrade" || suggestion.basis === "add_on") return true;
  return item.has_sizes || item.has_customizations;
}
