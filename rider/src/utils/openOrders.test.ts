import { claimErrorMessage, minutesLeftLabel } from './openOrders';

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
