/**
 * The decisions behind asking the server what an order costs.
 *
 * Pure, and separate from the hook that uses them, because they are the part
 * worth pinning down: when it is worth a paid lookup, what goes in the
 * request, and how a reply is read back. The hook around them owns only
 * timing and React state.
 *
 * All of it exists because the app used to price orders itself —
 * `restaurantLocation.delivery_fee` for the trip and `subtotal * 0.05` for
 * tax, both written into the cart screen. Measured against a real branch
 * (packaging 5.00, platform fee 17.98, food tax 5%, delivery tax 18%, flat
 * delivery 0.00), a 140.00 cart was displayed at 147.00 with "Free delivery"
 * and charged 229.23. Two implementations of one piece of arithmetic drift,
 * and when they disagree the customer is right to believe the screen.
 */

import type { DeliveryQuote } from '@/types/app';

/** What a screen knows, before it is turned into a request. */
export interface DeliveryQuoteInput {
  restaurantLocationId: string | null | undefined;
  deliveryAddress?: string;
  city?: string;
  state?: string;
  postalCode?: string;
  country?: string;
  /** A saved address the customer picked, priced from its stored coordinates. */
  savedAddressId?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  subtotal: number;
  discountAmount?: number;
}

/** The body `POST /orders/delivery-quote` expects. */
export interface DeliveryQuoteRequest {
  restaurant_location_id: string;
  delivery_address: string;
  city: string;
  state: string;
  postal_code: string;
  country: string;
  saved_address_id: string | null;
  latitude: number | null;
  longitude: number | null;
  subtotal: number;
  discount_amount: number;
}

/**
 * The shortest typed address worth sending to a geocoder.
 *
 * Below this every keystroke bills a lookup and the early ones are answered
 * with a city centroid — a coordinate, not an address, which then prices a
 * trip that does not exist.
 */
export const MIN_ADDRESS_LENGTH = 8;

/**
 * Whether there is enough here to price a trip.
 *
 * Coordinates and a saved address are always enough: both skip the geocoder
 * entirely, which is the whole reason a picked suggestion beats typed text.
 */
export function isQuotable(input: DeliveryQuoteInput): boolean {
  if (!input.restaurantLocationId) {
    return false;
  }
  if (input.savedAddressId) {
    return true;
  }
  if (input.latitude != null && input.longitude != null) {
    return true;
  }
  return (input.deliveryAddress ?? '').trim().length >= MIN_ADDRESS_LENGTH;
}

/**
 * The request body, with the subtotal and discount always included.
 *
 * The discount matters: food tax follows it, so sending the subtotal alone
 * over-taxes every customer who used an offer.
 */
export function buildQuoteRequest(
  input: DeliveryQuoteInput,
): DeliveryQuoteRequest {
  return {
    restaurant_location_id: input.restaurantLocationId as string,
    delivery_address: input.deliveryAddress ?? '',
    city: input.city ?? '',
    state: input.state ?? '',
    postal_code: input.postalCode ?? '',
    country: input.country ?? '',
    saved_address_id: input.savedAddressId ?? null,
    latitude: input.latitude ?? null,
    longitude: input.longitude ?? null,
    subtotal: input.subtotal,
    discount_amount: input.discountAmount ?? 0,
  };
}

/**
 * Every field the price depends on, as one string.
 *
 * Used to decide whether to ask again. Comparing the input object itself
 * re-asks on every render; comparing a hand-picked subset eventually misses a
 * field somebody adds, and the symptom is a stale fee beside a changed
 * address — which looks correct, and is the worst way to be wrong.
 */
export function quoteCacheKey(
  input: DeliveryQuoteInput,
  enabled: boolean,
): string {
  return JSON.stringify([buildQuoteRequest(input), enabled]);
}

/** What a screen shows where an amount goes, when there is not one yet. */
export function pendingAmountLabel(
  loading: boolean,
  error: string | null,
): string {
  if (loading) {
    return 'Working it out…';
  }
  return error ? 'Unavailable' : 'At checkout';
}

/**
 * The sentence under the delivery fee, or null.
 *
 * `fallback_reason` is the field that stops a checkout printing a number with
 * no provenance. Each case below is a different party's problem and says so:
 * the customer can retype an address, only the operator can place a branch,
 * and a restaurant's own flat rate is not a failure at all.
 */
export function deliveryFeeNote(quote: DeliveryQuote | null): string | null {
  if (!quote) {
    return null;
  }
  if (quote.fallback_reason === 'out_of_range') {
    // Slab pricing refuses an order past the branch's limit, so this is a
    // refusal rather than a fallback fee: say how far, and how far they go.
    const km = ((quote.distance_metres ?? 0) / 1000).toFixed(1);
    const limit = quote.max_distance_km ?? 10;
    return `This address is about ${km} km away and the restaurant delivers up to ${limit} km. Choose a closer address, or pickup.`;
  }
  if (quote.serviceable === false) {
    return "No courier will drive there right now — the restaurant's own fee applies.";
  }
  switch (quote.fallback_reason) {
    case 'address_unknown':
      return "We could not place that address on a map, so this is the restaurant's standard fee.";
    case 'branch_unknown':
      return "This restaurant has not pinned its branch yet, so this is their standard fee.";
    case 'unserviceable':
      return "No courier will drive there right now — the restaurant's own fee applies.";
    case 'currency_mismatch':
      return "The courier quoted in another currency, so the restaurant's own fee applies.";
    case 'no_courier':
      return null;
    default:
      return null;
  }
}

/** "0.9 km from the branch, priced by the courier", or null. */
export function deliveryDistanceNote(
  quote: DeliveryQuote | null,
): string | null {
  if (!quote || quote.distance_metres == null) {
    return null;
  }
  const km = (quote.distance_metres / 1000).toFixed(1);
  const priced = quote.source === 'courier' ? ', priced by the courier' : '';
  return `${km} km from the branch${priced}`;
}
