/**
 * What an order costs, and the ways this app used to get it wrong.
 *
 * Until these rules existed the app priced orders itself: the cart read
 * `restaurantLocation.delivery_fee` for the trip and added `subtotal * 0.05`
 * for tax, both written into the screen. Against a real branch — packaging
 * 5.00, platform fee 17.98, food tax 5%, delivery tax 18%, and a flat
 * `delivery_fee` of 0.00 because that branch quotes per address — a 140.00
 * cart was displayed at 147.00 with "Free delivery" and charged 229.23.
 *
 * An 82.23 gap on a 140 order, and the screen was the wrong one. The figures
 * below are that branch's, taken from the server's own reply, so a change that
 * reintroduces local arithmetic has to disagree with a real response to pass.
 */

import type { DeliveryQuote } from '@/types/app';
import {
  buildQuoteRequest,
  deliveryDistanceNote,
  deliveryFeeNote,
  isQuotable,
  pendingAmountLabel,
  quoteCacheKey,
  type DeliveryQuoteInput,
} from '@utils/deliveryQuote';

const BRANCH = '811b2f34-1e42-450d-b23e-7fedb9685d8a';

function input(over: Partial<DeliveryQuoteInput> = {}): DeliveryQuoteInput {
  return {
    restaurantLocationId: BRANCH,
    deliveryAddress: 'A-31, Rangdarshan Soc, Near Dhanmora, Katargam',
    city: 'Surat',
    subtotal: 140,
    ...over,
  };
}

/** The server's actual reply for that branch and address. */
function quote(over: Partial<DeliveryQuote> = {}): DeliveryQuote {
  return {
    delivery_fee: '50.00',
    currency: 'INR',
    source: 'courier',
    fallback_reason: '',
    serviceable: true,
    distance_metres: 868,
    assign_seconds: 690,
    travel_seconds: 209,
    exact_location: false,
    located_by: 'geocoder',
    matched_address: 'Rangdarshan Society, Katargam, Surat, Gujarat, India',
    charges: {
      total: '39.23',
      lines: [
        {key: 'packaging', label: 'Restaurant packaging', amount: '5.00', note: 'x'},
        {key: 'platform_fee', label: 'Platform fee', amount: '17.98', note: 'x'},
        {key: 'food_tax', label: 'Restaurant GST', amount: '7.25', note: 'x'},
        {key: 'delivery_tax', label: 'GST on delivery fee', amount: '9.00', note: 'x'},
      ],
    },
    total_amount: '229.23',
    ...over,
  };
}

describe('when it is worth asking', () => {
  it('asks once there is enough address to place', () => {
    expect(isQuotable(input())).toBe(true);
  });

  it('does not bill a lookup for the first few letters', () => {
    // A geocoder never refuses: given "A-3" it answers with a city centroid
    // and the trip gets priced from the middle of Surat.
    expect(isQuotable(input({deliveryAddress: 'A-3'}))).toBe(false);
  });

  it('asks immediately when the customer picked a point off the map', () => {
    // Coordinates skip the geocoder entirely, so the length rule does not
    // apply — this is the whole reason a picked suggestion beats typed text.
    expect(
      isQuotable(input({deliveryAddress: '', latitude: 21.22, longitude: 72.81})),
    ).toBe(true);
  });

  it('asks immediately for a saved address', () => {
    expect(
      isQuotable(input({deliveryAddress: '', savedAddressId: 'abc'})),
    ).toBe(true);
  });

  it('cannot ask without a branch to price from', () => {
    expect(isQuotable(input({restaurantLocationId: null}))).toBe(false);
  });
});

describe('what goes in the request', () => {
  it('always sends the subtotal, so the server prices the whole bill', () => {
    expect(buildQuoteRequest(input()).subtotal).toBe(140);
  });

  it('sends the discount, because food tax follows it', () => {
    // Taxing the pre-discount subtotal overcharges every customer who ever
    // uses an offer.
    expect(buildQuoteRequest(input({discountAmount: 40})).discount_amount).toBe(40);
  });

  it('sends zero rather than nothing when there is no discount', () => {
    expect(buildQuoteRequest(input()).discount_amount).toBe(0);
  });

  it('passes picked coordinates through', () => {
    const body = buildQuoteRequest(input({latitude: 21.2243, longitude: 72.8197}));
    expect(body.latitude).toBe(21.2243);
    expect(body.longitude).toBe(72.8197);
  });

  it('sends nulls, not undefined, for the parts it does not have', () => {
    // `undefined` drops out of a JSON body entirely, which reads server-side
    // as "not sent" rather than "not known" for a field that has a default.
    const body = buildQuoteRequest(input());
    expect(body.saved_address_id).toBeNull();
    expect(body.latitude).toBeNull();
    expect(body.longitude).toBeNull();
  });
});

describe('when to ask again', () => {
  it('re-asks when the address changes', () => {
    expect(quoteCacheKey(input(), true)).not.toBe(
      quoteCacheKey(input({deliveryAddress: 'Plot 9, Adajan, Surat'}), true),
    );
  });

  it('re-asks when the subtotal changes, because the tax does too', () => {
    expect(quoteCacheKey(input(), true)).not.toBe(
      quoteCacheKey(input({subtotal: 260}), true),
    );
  });

  it('re-asks when an offer is applied', () => {
    expect(quoteCacheKey(input(), true)).not.toBe(
      quoteCacheKey(input({discountAmount: 40}), true),
    );
  });

  it('does not re-ask when nothing that affects the price moved', () => {
    expect(quoteCacheKey(input(), true)).toBe(quoteCacheKey(input(), true));
  });
});

describe('what a screen shows instead of an amount', () => {
  it('never offers a number', () => {
    // Every one of these is where a 0 used to go, and a 0 in a delivery row
    // reads as "free".
    expect(pendingAmountLabel(true, null)).not.toMatch(/\d/);
    expect(pendingAmountLabel(false, null)).not.toMatch(/\d/);
    expect(pendingAmountLabel(false, 'network down')).not.toMatch(/\d/);
  });

  it('says it is working while it is', () => {
    expect(pendingAmountLabel(true, null)).toMatch(/working/i);
  });

  it('distinguishes a failure from a wait', () => {
    expect(pendingAmountLabel(false, 'network down')).not.toBe(
      pendingAmountLabel(false, null),
    );
  });
});

describe('where the fee came from', () => {
  it('says nothing when a courier priced the trip', () => {
    expect(deliveryFeeNote(quote())).toBeNull();
  });

  it('says nothing when the restaurant simply has a flat rate', () => {
    // Not a failure: it is the restaurant's own policy and the fee is correct.
    expect(deliveryFeeNote(quote({source: 'branch', fallback_reason: 'no_courier'}))).toBeNull();
  });

  it('tells the customer when the address is the thing that failed', () => {
    const note = deliveryFeeNote(
      quote({source: 'branch', fallback_reason: 'address_unknown'}),
    );
    expect(note).toMatch(/address/i);
  });

  it('does not blame the customer for a branch nobody pinned', () => {
    const note = deliveryFeeNote(
      quote({source: 'branch', fallback_reason: 'branch_unknown'}),
    );
    expect(note).toMatch(/restaurant/i);
    expect(note).not.toMatch(/your address/i);
  });

  it('says so when no courier will drive there', () => {
    expect(deliveryFeeNote(quote({serviceable: false}))).toMatch(/courier/i);
  });

  it('has nothing to say about a quote that does not exist', () => {
    expect(deliveryFeeNote(null)).toBeNull();
  });
});

describe('the distance line', () => {
  it('reads in kilometres, to one place', () => {
    expect(deliveryDistanceNote(quote())).toMatch(/^0\.9 km/);
  });

  it('says so when a courier measured it', () => {
    expect(deliveryDistanceNote(quote())).toMatch(/priced by the courier/);
  });

  it('claims nothing when the courier did not measure', () => {
    expect(
      deliveryDistanceNote(quote({source: 'branch', distance_metres: null})),
    ).toBeNull();
  });
});
