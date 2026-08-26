import type { SuggestionCard } from "../../types/app";

/**
 * Money and discount formatting for suggestion cards.
 *
 * Split out from the component because the precision rule below is a
 * correctness rule, not a styling one, and it is worth testing directly.
 */

const whole = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const exact = new Intl.NumberFormat("en-IN", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export function rupees(amount: number, decimals = false): string {
  return `₹${(decimals ? exact : whole).format(amount)}`;
}

/**
 * Whether a card's prices need decimals to stay honest.
 *
 * Rounding each figure independently broke the arithmetic on screen: ₹31.57 and
 * ₹29.36 rendered as ₹32 and ₹29 above a saving of ₹2.21 rendered as "₹2", so
 * the card appeared to claim 32 − 29 = 2. If any figure in the triple has a
 * fractional part, all three get decimals and the subtraction reads correctly.
 */
export function needsDecimals(pricing: SuggestionCard["pricing"]): boolean {
  if (!pricing) {
    return false;
  }
  return [pricing.original, pricing.offered, pricing.saving].some(
    (value) => value !== null && !Number.isInteger(value),
  );
}

/** The discount in the words an owner uses, from the structured value. */
export function discountLabel(discount: SuggestionCard["discount"]): string | null {
  if (!discount) {
    return null;
  }
  if (discount.type === "PERCENTAGE") {
    // 20.00 reads as a price; 20% reads as a discount. At most one decimal, and
    // no trailing ".0" - the generator produces values like 9.03, which
    // `toFixed(1)` turned into the odd-looking "9.0% off".
    return `${Math.round(discount.value * 10) / 10}% off`;
  }
  if (discount.type === "FLAT") {
    return `${rupees(discount.value)} off`;
  }
  if (discount.type === "FREE_DELIVERY") {
    return "Free delivery";
  }
  // An unknown discount type says nothing rather than guessing at its shape.
  return null;
}
