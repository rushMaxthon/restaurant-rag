import type { PersonalizedOfferCard } from '@/types/app';

/**
 * Offer-card helpers shared by `CartScreen` and its section components.
 *
 * Extracted verbatim from `CartScreen` when the offer palette moved into its
 * own component; the logic is unchanged.
 */
export function formatOfferEndsLabel(expiresAt: string | null): string | null {
  if (!expiresAt) {
    return null;
  }
  return `Ends ${new Intl.DateTimeFormat('en-IN', {
    day: 'numeric',
    month: 'short',
  }).format(new Date(expiresAt))}`;
}

export function getOfferIconName(offer: PersonalizedOfferCard): string {
  if (offer.discount_type === 'FREE_DELIVERY') {
    return 'bicycle-outline';
  }
  if (offer.discount_type === 'FLAT') {
    return 'cash-outline';
  }
  return 'pricetag-outline';
}

export function hexToRgba(hex: string, alpha: number): string {
  const normalized = hex.replace('#', '');
  const safeHex =
    normalized.length === 3
      ? normalized
          .split('')
          .map(char => `${char}${char}`)
          .join('')
      : normalized;
  const value = Number.parseInt(safeHex, 16);
  const r = (value >> 16) & 255;
  const g = (value >> 8) & 255;
  const b = value & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

export function toAppliedOffer(offer: PersonalizedOfferCard) {
  return {
    generatedOfferId: offer.generated_offer_id,
    generatedOfferUserMatchId: offer.generated_offer_user_match_id,
    offerId: offer.offer_id,
    offerName: offer.offer_name,
    offerType: offer.offer_type,
    audienceType: offer.audience_type,
    targetType: offer.target_type,
    restaurantId: offer.restaurant_id,
    restaurantName: offer.restaurant_name,
    restaurantLocationId: offer.restaurant_location_id,
    restaurantLocationName: offer.restaurant_location_name,
    offerRestaurantLocationId: offer.offer_restaurant_location_id,
    menuItemId: offer.menu_item_id,
    generatedComboId: offer.generated_combo_id,
    cuisineType: offer.cuisine_type,
    title: offer.title,
    ctaLabel: offer.cta_label,
    discountType: offer.discount_type,
    discountValue: offer.discount_value,
    discountLabel: offer.discount_label,
    maxDiscountAmount: offer.max_discount_amount,
    minimumOrderAmount: offer.minimum_order_amount,
    termsLabel: offer.terms_label,
    expiresAt: offer.expires_at,
  };
}

export function matchesAppliedOffer(
  offer: PersonalizedOfferCard,
  applied: ReturnType<typeof toAppliedOffer> | null,
): boolean {
  if (!applied) {
    return false;
  }
  return (
    offer.offer_id === applied.offerId &&
    offer.generated_offer_id === applied.generatedOfferId &&
    offer.generated_offer_user_match_id === applied.generatedOfferUserMatchId
  );
}
