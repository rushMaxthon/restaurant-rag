import { describe, expect, it } from 'vitest';

import {
  branchScopeLabel,
  emptyRiderDraft,
  lastSeenLabel,
  payExample,
  payFormError,
  riderFormErrors,
  reassignErrorMessage,
  tenDigits,
  toggleBranch,
} from './riders';

describe('rider form', () => {
  it('needs a name, a 10-digit mobile and an 8-character password to create', () => {
    const errors = riderFormErrors({ ...emptyRiderDraft(), full_name: ' ', phone: '98765', password: 'short' }, 'create');
    expect(errors.full_name).toBeTruthy();
    expect(errors.phone).toBeTruthy();
    expect(errors.password).toBeTruthy();
  });

  it('accepts a complete rider', () => {
    const draft = { ...emptyRiderDraft(), full_name: 'Ravi', phone: '98765 43210', password: 'rider1234' };
    expect(riderFormErrors(draft, 'create')).toEqual({});
  });

  it('allows an empty password when editing (unchanged)', () => {
    const draft = { ...emptyRiderDraft(), full_name: 'Ravi', phone: '9876543210', password: '' };
    expect(riderFormErrors(draft, 'edit')).toEqual({});
  });

  it('keeps the last ten digits of whatever was typed', () => {
    expect(tenDigits('+91 98765-43210')).toBe('9876543210');
  });
});

describe('pay settings', () => {
  it('refuses a rate that pays nothing', () => {
    expect(payFormError({ base: '0', per_km: '0', minimum: '0' })).toBeTruthy();
  });

  it('refuses something that is not a number', () => {
    expect(payFormError({ base: 'abc', per_km: '6', minimum: '30' })).toBeTruthy();
  });

  it('shows what a 4 km trip pays, never under the minimum', () => {
    expect(payExample({ base: '25', per_km: '6', minimum: '30' }, 4)).toBe(49);
    expect(payExample({ base: '10', per_km: '2', minimum: '30' }, 1)).toBe(30);
  });
});

describe('lastSeenLabel', () => {
  const now = new Date('2026-10-08T12:00:00Z');
  it('says never when there is no location', () => {
    expect(lastSeenLabel(null, now)).toBe('Never');
  });
  it('reads minutes and hours', () => {
    expect(lastSeenLabel('2026-10-08T11:59:40Z', now)).toBe('Just now');
    expect(lastSeenLabel('2026-10-08T11:55:00Z', now)).toBe('5 min ago');
    expect(lastSeenLabel('2026-10-08T09:00:00Z', now)).toBe('3 h ago');
  });
});

describe('reassignErrorMessage', () => {
  it('says plainly why an order cannot move to another rider', () => {
    expect(reassignErrorMessage('rider_has_it')).toBe(
      'Another rider has this order and is still active. It can only move if they go silent before pickup.',
    );
    expect(reassignErrorMessage('food_picked_up')).toBe(
      'The rider has already picked up the food, so it stays with them.',
    );
    expect(reassignErrorMessage('rider_busy')).toBe('That rider is already answering another order.');
  });

  it('falls back to the server message for anything else', () => {
    expect(reassignErrorMessage('something_new', 'Server said no')).toBe('Server said no');
  });
});

describe('the branch allowlist', () => {
  const branches = [
    { id: 'a', restaurant_name: 'Bhagwati', branch_name: 'Main', city: 'Surat', delivery_enabled: true },
    { id: 'b', restaurant_name: 'Bhagwati', branch_name: 'Adajan', city: 'Surat', delivery_enabled: true },
  ];

  it('adds and removes a branch, keeping the list in one order', () => {
    expect(toggleBranch(['b'], 'a')).toEqual(['a', 'b']);
    expect(toggleBranch(['a', 'b'], 'a')).toEqual(['b']);
  });

  it('says an empty list means every branch, not none', () => {
    expect(branchScopeLabel([], branches)).toBe('Every branch');
  });

  it('counts the named branches, ignoring ids that no longer exist', () => {
    expect(branchScopeLabel(['a'], branches)).toBe('1 of 2 branches');
    expect(branchScopeLabel(['a', 'gone'], branches)).toBe('1 of 2 branches');
  });
});
