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
 * What the prompt says, chosen by `basis` and nothing else.
 *
 * The client does not get to invent a reason. A mined pairing has evidence
 * behind it and may say so; a category default is a guess and must read like
 * one. Wording them alike would present a guess as a measurement.
 */
export function suggestionCopy(suggestion: SellSuggestion, itemName: string): string {
  switch (suggestion.basis) {
    case "co_occurrence":
      return `Often ordered with what you've got — ${itemName}?`;
    case "category_default":
      return `Most people add ${itemName}.`;
    case "combo_upgrade":
      return `Make it the ${itemName} and save ${suggestion.saving ?? ""}.`;
    case "size_upgrade":
      return `Go large on the ${itemName}? ${suggestion.extra_cost ?? ""} more.`;
    case "add_on":
      return `Add ${itemName}?`;
    default:
      // A basis this build does not know about still has to render something
      // a person can read, rather than "undefined".
      return `${itemName}?`;
  }
}
