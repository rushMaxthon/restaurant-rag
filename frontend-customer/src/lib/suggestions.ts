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
