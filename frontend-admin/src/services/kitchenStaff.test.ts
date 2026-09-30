/**
 * The kitchen staff form rules.
 *
 * Two of these are here because getting them wrong is silent rather than
 * loud: an edit that sends a password field the server refuses, and a branch
 * being cleared with `null` instead of the flag the server actually reads —
 * which looks like a successful save that changed nothing.
 */

import { describe, expect, it } from 'vitest';

import {
  EMPTY_STAFF_FORM,
  branchLabel,
  buildStaffUpdate,
  hasErrors,
  validateStaffForm,
} from './kitchenStaff';
import type { KitchenStaff } from '../types/app';

function staff(overrides: Partial<KitchenStaff> = {}): KitchenStaff {
  return {
    id: 'staff-1',
    full_name: 'Night Cook',
    email: 'cook@example.com',
    phone_number: null,
    is_active: true,
    restaurant_id: 'restaurant-1',
    restaurant_location_id: 'branch-1',
    branch_name: 'Ellisbridge',
    created_at: '2026-09-22T10:00:00Z',
    ...overrides,
  };
}

const VALID = {
  ...EMPTY_STAFF_FORM,
  full_name: 'Night Cook',
  email: 'cook@example.com',
  password: 'kitchen-pass-1',
};

describe('creating', () => {
  it('accepts a complete form', () => {
    expect(hasErrors(validateStaffForm(VALID, 'create'))).toBe(false);
  });

  it('requires a name, an email and a password', () => {
    const errors = validateStaffForm(EMPTY_STAFF_FORM, 'create');
    expect(errors.full_name).toBeTruthy();
    expect(errors.email).toBeTruthy();
    expect(errors.password).toBeTruthy();
  });

  it('enforces the server’s password minimum', () => {
    // Eight is `Field(min_length=8)` in the backend schema. Catching it here
    // is the difference between a field-level message and a 422 after submit.
    expect(validateStaffForm({ ...VALID, password: 'short' }, 'create').password).toBeTruthy();
    expect(validateStaffForm({ ...VALID, password: '12345678' }, 'create').password).toBeUndefined();
  });

  it('rejects an obvious non-address', () => {
    expect(validateStaffForm({ ...VALID, email: 'not-an-email' }, 'create').email).toBeTruthy();
  });

  it('treats a blank branch as a real choice, not an omission', () => {
    // '' means every branch of the restaurant. Requiring one would make a
    // single-branch restaurant fill in a field that says nothing.
    const errors = validateStaffForm({ ...VALID, restaurant_location_id: '' }, 'create');
    expect(errors.restaurant_location_id).toBeUndefined();
  });

  it('bounds a phone number only once one is typed', () => {
    expect(validateStaffForm({ ...VALID, phone_number: '' }, 'create').phone_number).toBeUndefined();
    expect(validateStaffForm({ ...VALID, phone_number: '123' }, 'create').phone_number).toBeTruthy();
  });
});

describe('editing', () => {
  it('does not ask for a password', () => {
    // The backend refuses to change either, so asking would be a field whose
    // value is discarded.
    const errors = validateStaffForm({ ...EMPTY_STAFF_FORM, full_name: 'Day Cook' }, 'edit');
    expect(errors.password).toBeUndefined();
    expect(errors.email).toBeUndefined();
  });

  it('still requires a usable name', () => {
    expect(validateStaffForm({ ...EMPTY_STAFF_FORM, full_name: 'A' }, 'edit').full_name).toBeTruthy();
  });
});

describe('building the update', () => {
  it('sends nothing when nothing changed', () => {
    // An empty patch is skipped by the caller — a no-op request would bump
    // token_version and sign the cook out of a board they are standing at.
    const payload = buildStaffUpdate(staff(), {
      full_name: 'Night Cook',
      restaurant_location_id: 'branch-1',
    });
    expect(payload).toEqual({});
  });

  it('sends only the renamed field', () => {
    const payload = buildStaffUpdate(staff(), {
      full_name: 'Day Cook',
      restaurant_location_id: 'branch-1',
    });
    expect(payload).toEqual({ full_name: 'Day Cook' });
  });

  it('moves a cook to another branch', () => {
    const payload = buildStaffUpdate(staff(), {
      full_name: 'Night Cook',
      restaurant_location_id: 'branch-2',
    });
    expect(payload).toEqual({ restaurant_location_id: 'branch-2' });
  });

  it('clears a branch with the flag, never a bare null', () => {
    // `restaurant_location_id: null` is indistinguishable from "not sent" on
    // the wire, so the server would leave the pin in place and the owner
    // would watch a successful save change nothing.
    const payload = buildStaffUpdate(staff(), {
      full_name: 'Night Cook',
      restaurant_location_id: '',
    });
    expect(payload).toEqual({ clear_restaurant_location: true });
    expect('restaurant_location_id' in payload).toBe(false);
  });

  it('pins an all-branches account to one branch', () => {
    const payload = buildStaffUpdate(
      staff({ restaurant_location_id: null, branch_name: null }),
      { full_name: 'Night Cook', restaurant_location_id: 'branch-2' },
    );
    expect(payload).toEqual({ restaurant_location_id: 'branch-2' });
  });
});

describe('reading a row', () => {
  it('names the branch when there is one', () => {
    expect(branchLabel(staff())).toBe('Ellisbridge');
  });

  it('says all branches rather than leaving a blank', () => {
    expect(branchLabel(staff({ restaurant_location_id: null, branch_name: null }))).toBe(
      'All branches',
    );
  });
});
