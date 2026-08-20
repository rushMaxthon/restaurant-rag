import type { PersonalizedOfferCard } from '@/types/app';

export function getRestaurantScopedOffers(
  offers: PersonalizedOfferCard[],
  restaurantId: string | null | undefined,
  restaurantLocationId: string | null | undefined,
): PersonalizedOfferCard[] {
  if (!restaurantId) {
    return [];
  }

  return offers.filter(offer => {
    if (offer.restaurant_id !== restaurantId) {
      return false;
    }
    if (
      offer.offer_restaurant_location_id &&
      offer.offer_restaurant_location_id !== restaurantLocationId
    ) {
      return false;
    }
    return true;
  });
}
