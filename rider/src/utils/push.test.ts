import { foregroundAction, offerAlertMs, parsePush, screenFor } from './push';

describe('parsePush', () => {
  it('reads an offer the backend sent (notify.offer_made)', () => {
    expect(
      parsePush({
        type: 'rider_offer',
        offer_id: 'o1',
        expires_at: '2026-10-08T12:00:45Z',
        channel: 'rider-offers',
      }),
    ).toEqual({
      kind: 'offer',
      offerId: 'o1',
      expiresAt: '2026-10-08T12:00:45Z',
    });
  });

  it('reads a cancelled trip (notify.trip_cancelled)', () => {
    expect(parsePush({ type: 'rider_trip_cancelled', trip_id: 't1' })).toEqual({
      kind: 'trip_cancelled',
      tripId: 't1',
    });
  });

  it('reads an application decision (notify.application_decided)', () => {
    expect(
      parsePush({ type: 'rider_application', status: 'APPROVED' }),
    ).toEqual({
      kind: 'application',
      status: 'APPROVED',
    });
  });

  it('ignores anything else, including a message with no data', () => {
    expect(parsePush({ type: 'marketing' })).toBeNull();
    expect(parsePush(undefined)).toBeNull();
    expect(parsePush({ type: 'rider_offer' })).toBeNull();
  });
});

describe('screenFor', () => {
  it('opens the offer for an offer, and Home for a cancelled trip (the trip is gone)', () => {
    expect(screenFor({ kind: 'offer', offerId: 'o', expiresAt: '' })).toBe(
      'Offer',
    );
    expect(screenFor({ kind: 'trip_cancelled', tripId: 't' })).toBe('Home');
  });
});

describe('offerAlertMs', () => {
  const now = new Date('2026-10-08T12:00:00Z');
  it('keeps the alert up exactly until the offer expires', () => {
    expect(offerAlertMs('2026-10-08T12:00:40Z', now)).toBe(40_000);
  });
  it('says not to show an offer that has already expired', () => {
    expect(offerAlertMs('2026-10-08T11:59:59Z', now)).toBeNull();
    expect(offerAlertMs('not a date', now)).toBeNull();
  });
});

describe('shift ended (notify.shift_ended)', () => {
  it('reads the push sent when a quiet phone is taken off shift, and opens Home', () => {
    const push = parsePush({ type: 'rider_shift_ended' });
    expect(push).toEqual({ kind: 'shift_ended' });
    expect(screenFor(push!)).toBe('Home');
  });
});

describe('referral (notify.queue_referral_push)', () => {
  it('reads each referral event and opens Refer & earn', () => {
    const push = parsePush({
      type: 'rider_referral',
      event: 'earned',
      amount: '100.00',
      name: 'Ravi K.',
    });
    expect(push).toEqual({
      kind: 'referral',
      event: 'earned',
      name: 'Ravi K.',
      amount: '100.00',
      deliveries: '',
      days: '',
    });
    expect(screenFor(push!)).toBe('Referral');
    expect(
      parsePush({ type: 'rider_referral', event: 'joined', name: 'Ravi K.' })
        ?.kind,
    ).toBe('referral');
  });
  it('ignores an event it does not know', () => {
    expect(
      parsePush({ type: 'rider_referral', event: 'something' }),
    ).toBeNull();
  });
});

describe('foregroundAction', () => {
  it('shows a referral notice even with the app open - the rider caused it by delivering', () => {
    expect(
      foregroundAction(
        parsePush({ type: 'rider_referral', event: 'earned', name: 'x' }),
      ),
    ).toBe('show_referral');
  });
  it('refetches the application, else checks the offer', () => {
    expect(
      foregroundAction(
        parsePush({ type: 'rider_application', status: 'APPROVED' }),
      ),
    ).toBe('application');
    expect(
      foregroundAction(
        parsePush({ type: 'rider_offer', offer_id: '1', expires_at: 'x' }),
      ),
    ).toBe('refresh_offer');
    expect(foregroundAction(null)).toBe('refresh_offer');
  });
});
