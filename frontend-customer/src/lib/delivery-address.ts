/**
 * The checkout address and phone, validated where the customer can fix them.
 *
 * Checkout used to ask for one free-text line and a phone number, mark both
 * required, and send neither the phone nor any structure to the server: the
 * rider got a single string and no number to call. The server now takes
 * `contact_name` and `contact_phone` (migration 0058) and still stores the
 * address as one readable line, so these parts are collected, checked, and
 * composed into it.
 *
 * Pure, so the rules can be pinned without a browser and the form and the
 * submit handler cannot disagree about what "valid" means.
 */

/** Matches the backend's `default_phone_national_digits`. */
const NATIONAL_DIGITS = 10;

export type AddressFields = {
  line1: string;
  line2: string;
  landmark: string;
  city: string;
  state: string;
  zip: string;
};

export type AddressProblems = Partial<Record<keyof AddressFields, string>>;

function digitsOf(value: string): string {
  return value.replace(/\D/g, "");
}

/**
 * What is wrong with this phone number, or null.
 *
 * Mirrors the server's normaliser: a bare local number is assumed to be in the
 * deployment's own country, and anything with a `+` is taken at its word.
 */
export function validatePhone(value: string): string | null {
  const raw = value.trim();
  if (!raw) return "Enter a phone number so we can reach you about the order.";
  if (/[a-z]/i.test(raw)) return "Enter a phone number using digits only.";

  const digits = digitsOf(raw);
  if (!digits) return "Enter a phone number using digits only.";

  if (raw.startsWith("+")) {
    return digits.length >= 8 && digits.length <= 15
      ? null
      : "Enter a valid number, including the country code.";
  }
  // "1 415 555 0132" — the country code typed without its plus.
  if (digits.length === NATIONAL_DIGITS + 1 && digits.startsWith("1")) return null;
  return digits.length === NATIONAL_DIGITS
    ? null
    : `Enter a ${NATIONAL_DIGITS}-digit phone number, or include the country code.`;
}

/**
 * Group the digits as they are typed, so a wrong one is visible before submit.
 *
 * Only the default country is grouped. Every other country has its own
 * conventions, and guessing produces confident nonsense — those are left
 * exactly as typed. Nothing is ever dropped or reordered: a formatter that
 * eats characters is worse than no formatter.
 */
export function formatPhoneAsTyped(value: string): string {
  const raw = value.trim();
  if (raw.startsWith("+")) return raw;

  const digits = digitsOf(raw).slice(0, NATIONAL_DIGITS);
  if (digits.length <= 3) return digits.length === 3 ? `(${digits})` : digits;
  if (digits.length <= 6) return `(${digits.slice(0, 3)}) ${digits.slice(3)}`;
  return `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6)}`;
}

/**
 * What is missing or malformed, field by field.
 *
 * Line 2 and the landmark are genuinely optional. Demanding every box is how a
 * checkout loses an order; what has to be there is enough to find the door.
 */
export function validateAddress(fields: AddressFields): AddressProblems {
  const problems: AddressProblems = {};
  const line1 = fields.line1.trim();
  const city = fields.city.trim();
  const state = fields.state.trim();
  const zip = fields.zip.trim();

  if (!line1) problems.line1 = "Enter your street address.";
  else if (line1.length < 4) problems.line1 = "That looks too short to find.";

  if (!city) problems.city = "Enter your city.";
  if (!state) problems.state = "Enter your state.";

  if (!zip) problems.zip = "Enter your ZIP code.";
  // 12345 or 12345-6789, the two forms the postal service uses.
  else if (!/^\d{5}(-\d{4})?$/.test(zip)) problems.zip = "Enter a 5-digit ZIP code.";

  return problems;
}

/**
 * The parts joined into the one line the server stores and the rider reads.
 *
 * Comma-separated in the order an address is read aloud, with the state and
 * ZIP together as they are written on an envelope. Missing optional parts are
 * left out rather than leaving empty commas behind.
 */
export function composeDeliveryAddress(fields: AddressFields): string {
  const head = [fields.line1, fields.line2, fields.landmark, fields.city]
    .map((part) => part.trim())
    .filter(Boolean);
  const tail = [fields.state.trim(), fields.zip.trim()].filter(Boolean).join(" ");
  return [...head, tail].filter(Boolean).join(", ");
}
