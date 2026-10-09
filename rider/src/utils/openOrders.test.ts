import {
  claimErrorMessage,
  minutesLeftLabel,
  takeBlockedReason,
} from './openOrders';

describe('claimErrorMessage', () => {
  it('says plainly that someone was quicker', () => {
    expect(claimErrorMessage('order_taken')).toBe(
      'Another rider took this one first.',
    );
  });
  it('tells an offline rider what to do', () => {
    expect(claimErrorMessage('rider_offline')).toBe(
      'Go online to take orders.',
    );
  });
  it('tells a rider mid-trip to finish first', () => {
    expect(claimErrorMessage('rider_busy')).toBe(
      'Finish your current delivery first.',
    );
  });
  it('falls back to a retry for anything else', () => {
    expect(claimErrorMessage(undefined)).toBe(
      'Could not take this order. Try again.',
    );
  });
});

describe('minutesLeftLabel', () => {
  it('counts down to the courier', () => {
    expect(minutesLeftLabel(4)).toBe('4 min left');
    expect(minutesLeftLabel(1)).toBe('Last minute');
  });
});

describe('takeBlockedReason', () => {
  // A disabled button says why (house rule): the board is visible to
  // everyone, Take is only for a rider who is online and free.
  it('is null for a rider who is online and free', () => {
    expect(takeBlockedReason('ONLINE', false)).toBeNull();
  });
  it('asks an offline rider to go online', () => {
    expect(takeBlockedReason('OFFLINE', false)).toBe(
      'Go online to take orders',
    );
    expect(takeBlockedReason(undefined, false)).toBe(
      'Go online to take orders',
    );
  });
  it('asks a rider mid-trip to finish first', () => {
    expect(takeBlockedReason('ON_TRIP', true)).toBe(
      'Finish your current delivery first',
    );
    expect(takeBlockedReason('ONLINE', true)).toBe(
      'Finish your current delivery first',
    );
  });
});
