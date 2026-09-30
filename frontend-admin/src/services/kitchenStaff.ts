/**
 * The rules for a kitchen staff form, kept out of the component.
 *
 * Every limit here mirrors `KitchenStaffCreate` in
 * `backend/app/schemas/kitchen_staff.py`. The server is still the authority —
 * it validates independently and this panel never decides who may be created.
 * The point of restating the limits is that a 422 arriving after the request
 * cannot say which field is wrong next to the field itself, and "Create" is
 * the wrong moment to learn a password was one character short.
 *
 * Pure, so the rules can be checked without rendering a form.
 */

import type { KitchenStaff, KitchenStaffUpdatePayload } from '../types/app';

/** Mirrors the Pydantic `Field(...)` bounds exactly. */
export const NAME_MIN = 2;
export const NAME_MAX = 255;
export const PASSWORD_MIN = 8;
export const PASSWORD_MAX = 128;
export const PHONE_MIN = 8;
export const PHONE_MAX = 20;

export interface StaffFormValues {
  full_name: string;
  email: string;
  password: string;
  phone_number: string;
  /** '' means every branch of the restaurant, which is a real choice. */
  restaurant_location_id: string;
}

export type StaffFormErrors = Partial<Record<keyof StaffFormValues, string>>;

export const EMPTY_STAFF_FORM: StaffFormValues = {
  full_name: '',
  email: '',
  password: '',
  phone_number: '',
  restaurant_location_id: '',
};

/**
 * Good enough to catch a typo, deliberately not an RFC 5322 parser.
 *
 * `EmailStr` on the server is the real check and it rejects things this
 * accepts — notably the `.local` TLD, which is reserved. Being stricter here
 * than the server would reject addresses the platform would have taken.
 */
function looksLikeEmail(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}

/**
 * What is wrong with this form, by field.
 *
 * `mode` matters for one field only: an edit cannot change the password or the
 * email, because the backend refuses both — re-pointing a live login at a
 * different person is how a revoked account quietly comes back.
 */
export function validateStaffForm(
  values: StaffFormValues,
  mode: 'create' | 'edit',
): StaffFormErrors {
  const errors: StaffFormErrors = {};

  const name = values.full_name.trim();
  if (!name) {
    errors.full_name = 'Enter the person’s name.';
  } else if (name.length < NAME_MIN) {
    errors.full_name = `At least ${NAME_MIN} characters.`;
  } else if (name.length > NAME_MAX) {
    errors.full_name = `At most ${NAME_MAX} characters.`;
  }

  if (mode === 'create') {
    const email = values.email.trim();
    if (!email) {
      errors.email = 'Enter an email address to sign in with.';
    } else if (!looksLikeEmail(email)) {
      errors.email = 'That does not look like an email address.';
    }

    if (!values.password) {
      errors.password = 'Set a password for this screen.';
    } else if (values.password.length < PASSWORD_MIN) {
      errors.password = `At least ${PASSWORD_MIN} characters.`;
    } else if (values.password.length > PASSWORD_MAX) {
      errors.password = `At most ${PASSWORD_MAX} characters.`;
    }
  }

  // Optional, but the server's bounds apply the moment anything is typed.
  const phone = values.phone_number.trim();
  if (phone && (phone.length < PHONE_MIN || phone.length > PHONE_MAX)) {
    errors.phone_number = `Between ${PHONE_MIN} and ${PHONE_MAX} characters, or leave blank.`;
  }

  return errors;
}

export function hasErrors(errors: StaffFormErrors): boolean {
  return Object.keys(errors).length > 0;
}

/**
 * Only what actually changed, in the shape the PATCH expects.
 *
 * Clearing the branch is the case that needs care: `null` and "not sent" are
 * different intentions and JSON cannot distinguish them, so the backend takes
 * a separate `clear_restaurant_location` flag. Sending
 * `restaurant_location_id: null` alone would be read as "leave it alone" and
 * the owner's change would silently do nothing.
 *
 * Returns an empty object when nothing changed, so the caller can skip a
 * request rather than bump `token_version` and sign a cook out for no reason.
 */
export function buildStaffUpdate(
  staff: KitchenStaff,
  values: Pick<StaffFormValues, 'full_name' | 'restaurant_location_id'>,
): KitchenStaffUpdatePayload {
  const payload: KitchenStaffUpdatePayload = {};

  const name = values.full_name.trim();
  if (name && name !== staff.full_name) {
    payload.full_name = name;
  }

  const nextBranch = values.restaurant_location_id || null;
  if (nextBranch !== staff.restaurant_location_id) {
    if (nextBranch === null) {
      payload.clear_restaurant_location = true;
    } else {
      payload.restaurant_location_id = nextBranch;
    }
  }

  return payload;
}

/** How a row's assignment reads in a list. */
export function branchLabel(staff: KitchenStaff): string {
  return staff.branch_name ?? 'All branches';
}
