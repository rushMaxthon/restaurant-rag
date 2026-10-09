import type { Key } from '@/i18n/strings';
import type {
  ApplicationView,
  ItemKind,
  PhotoKind,
  RiderMe,
  RiderOnboarding,
  SectionKey,
  VehicleType,
} from '@/types/api';

/**
 * The rules a rider's application is checked against, on the phone.
 *
 * A mirror of `backend/app/services/fleet/onboarding/rules.py` and the
 * section checks in `applications.save_section`, kept to the same regexes
 * and the same error codes, so the rider hears "that IFSC is wrong" before
 * sending and the words match what the server would have said. The server's
 * copy is the one that counts: a rule changed there must change here, or the
 * phone either refuses a rider the server would take or sends them to a 422.
 */

// --- validators (rules.py) ----------------------------------------------------

// Standard plates (GJ05AB1234, GJ51234) and the Bharat series (22BH1234AA).
const PLATE = /^[A-Z]{2}\d{1,2}[A-Z]{0,3}\d{4}$/;
const BH_PLATE = /^\d{2}BH\d{4}[A-Z]{1,2}$/;
const PAN = /^[A-Z]{5}\d{4}[A-Z]$/;
// The fifth character of an IFSC is always zero, reserved by the RBI.
const IFSC = /^[A-Z]{4}0[A-Z0-9]{6}$/;
const PINCODE = /^[1-9]\d{5}$/;
const ACCOUNT = /^\d{9,18}$/;
const UPI = /^[a-z0-9.\-_]{2,256}@[a-z]{2,64}$/;

/** What `_squash` does on the server: no spaces, no hyphens, upper case. */
function squash(raw: string | null | undefined): string {
  return (raw ?? '').replace(/[\s-]/g, '').toUpperCase();
}

export function cleanPlate(raw: string | null | undefined): string | null {
  const plate = squash(raw);
  return PLATE.test(plate) || BH_PLATE.test(plate) ? plate : null;
}

export function validPan(raw: string | null | undefined): string | null {
  const pan = squash(raw);
  return PAN.test(pan) ? pan : null;
}

export function validIfsc(raw: string | null | undefined): string | null {
  const ifsc = squash(raw);
  return IFSC.test(ifsc) ? ifsc : null;
}

export function validPincode(raw: string | null | undefined): string | null {
  const pin = squash(raw);
  return PINCODE.test(pin) ? pin : null;
}

/** Typed twice because a wrong digit pays a stranger and is not undone. */
export function validAccount(
  raw: string | null | undefined,
  again: string | null | undefined,
): string | null {
  const first = squash(raw);
  return ACCOUNT.test(first) && first === squash(again) ? first : null;
}

export function validUpi(raw: string | null | undefined): string | null {
  const upi = (raw ?? '').trim().toLowerCase();
  return UPI.test(upi) ? upi : null;
}

/** A 10-digit Indian mobile, sent as +91XXXXXXXXXX (what `canonical_phone` keeps). */
export function validMobile(raw: string | null | undefined): string | null {
  const digits = (raw ?? '').replace(/\D/g, '');
  const ten =
    digits.length === 12 && digits.startsWith('91') ? digits.slice(2) : digits;
  return ten.length === 10 ? `+91${ten}` : null;
}

// --- dates ----------------------------------------------------------------------
//
// Dates travel as 'YYYY-MM-DD' and are compared as strings, which sorts
// correctly for that shape. No Date arithmetic: a Date built from a string is
// UTC midnight, which in India is 05:30 local, and an "18 today" check done in
// Date maths was off by a day before 05:30 in other apps of this kind.

export type Dmy = { dd: string; mm: string; yyyy: string };

const pad = (n: number, width = 2) => String(n).padStart(width, '0');

function daysIn(year: number, month: number): number {
  return new Date(Date.UTC(year, month, 0)).getUTCDate();
}

/** The three boxes as an ISO date, or null when that day does not exist. */
export function parseDmy(dd: string, mm: string, yyyy: string): string | null {
  if (!/^\d{1,2}$/.test(dd) || !/^\d{1,2}$/.test(mm) || !/^\d{4}$/.test(yyyy))
    return null;
  const day = Number(dd);
  const month = Number(mm);
  const year = Number(yyyy);
  if (
    year < 1900 ||
    month < 1 ||
    month > 12 ||
    day < 1 ||
    day > daysIn(year, month)
  )
    return null;
  return `${pad(year, 4)}-${pad(month)}-${pad(day)}`;
}

export function isoToDmy(iso: string | null | undefined): Dmy {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? '');
  return match
    ? { dd: match[3]!, mm: match[2]!, yyyy: match[1]! }
    : { dd: '', mm: '', yyyy: '' };
}

/** The phone's own calendar day; the server checks against India's, the same day for a rider here. */
export function todayIso(now: Date = new Date()): string {
  return `${pad(now.getFullYear(), 4)}-${pad(now.getMonth() + 1)}-${pad(
    now.getDate(),
  )}`;
}

/** 18 on or before today. Born on 29 February: the birthday is 1 March. */
export function isAdult(dobIso: string, today: string): boolean {
  const [y, m, d] = dobIso.split('-').map(Number) as [number, number, number];
  const year = y + 18;
  const eighteenth =
    m === 2 && d === 29 && daysIn(year, 2) === 28
      ? `${pad(year, 4)}-03-01`
      : `${pad(year, 4)}-${pad(m)}-${pad(d)}`;
  return today >= eighteenth;
}

export function licenceValid(expiryIso: string, today: string): boolean {
  return expiryIso > today;
}

// --- what is required (rules.required_items + applications.required_for) -------

export function needsRc(vehicle: VehicleType | null | undefined): boolean {
  return vehicle === 'BIKE' || vehicle === 'SCOOTER';
}

export function needsLicence(vehicle: VehicleType | null | undefined): boolean {
  return vehicle === 'BIKE' || vehicle === 'SCOOTER';
}

export function requiredItems(
  vehicle: VehicleType | null | undefined,
  hasAccount = false,
): ItemKind[] {
  const items: ItemKind[] = [
    'PERSONAL',
    'SELFIE',
    'AADHAAR_FRONT',
    'AADHAAR_BACK',
    'PAN',
    'BANK_DETAILS',
  ];
  if (needsRc(vehicle)) items.push('VEHICLE_DETAILS', 'RC');
  if (needsLicence(vehicle)) items.push('LICENCE_FRONT', 'LICENCE_BACK');
  // A bank account is checked against a cheque or passbook; a UPI ID alone
  // has nothing to photograph.
  if (hasAccount) items.push('BANK_PROOF');
  return items;
}

/** Which step each item lives on (`SECTION_OF` on the server), so "Fix" opens the right one. */
export const SECTION_OF: Record<ItemKind, SectionKey> = {
  PERSONAL: 'personal',
  SELFIE: 'personal',
  VEHICLE_DETAILS: 'vehicle',
  RC: 'vehicle',
  AADHAAR_FRONT: 'documents',
  AADHAAR_BACK: 'documents',
  PAN: 'documents',
  LICENCE_FRONT: 'documents',
  LICENCE_BACK: 'documents',
  BANK_DETAILS: 'bank',
  BANK_PROOF: 'bank',
};

export const STEPS: readonly SectionKey[] = [
  'personal',
  'vehicle',
  'documents',
  'bank',
];

export type Step = SectionKey | 'review';

/**
 * Where an app opened mid-application resumes - read from the server, never
 * from the phone, so a second phone or a reinstall lands in the same place.
 * Sent back: the first step with something flagged. Otherwise the first step
 * with something missing; a vehicle not chosen yet counts, though the server
 * lists nothing for it (what it needs depends on the choice).
 */
export function firstIncompleteStep(view: ApplicationView): Step {
  if (view.status === 'CHANGES_NEEDED') {
    const flagged = view.items.filter(
      i => i.status === 'NEEDS_CHANGE' && i.editable !== false,
    );
    for (const step of STEPS)
      if (flagged.some(i => SECTION_OF[i.kind] === step)) return step;
    return 'review';
  }
  const missing = new Set(view.missing.map(kind => SECTION_OF[kind]));
  if (missing.has('personal')) return 'personal';
  if (!view.sections.vehicle.vehicle_type || missing.has('vehicle'))
    return 'vehicle';
  for (const step of STEPS) if (missing.has(step)) return step;
  return 'review';
}

/** Why Submit cannot go yet, as the server would say it - or null. */
export function applicationProblem(
  view: ApplicationView,
): 'locked' | 'missing' | 'flagged' | null {
  if (view.status !== 'DRAFT' && view.status !== 'CHANGES_NEEDED')
    return 'locked';
  if (view.missing.length > 0) return 'missing';
  if (view.items.some(i => i.status === 'NEEDS_CHANGE' && i.required))
    return 'flagged';
  return null;
}

/** Done = given and not flagged; what the progress bar on the status screen counts. */
export function progress(view: ApplicationView): {
  done: number;
  total: number;
} {
  const missing = new Set(view.missing);
  const flagged = new Set(
    view.items.filter(i => i.status === 'NEEDS_CHANGE').map(i => i.kind),
  );
  const total = view.required.length;
  const done = view.required.filter(
    k => !missing.has(k) && !flagged.has(k),
  ).length;
  return { done, total };
}

export type ItemState = 'todo' | 'added' | 'inReview' | 'accepted' | 'fix';

/**
 * What a row on the status screen says about one item. PENDING is "added"
 * while the rider is still filling in (nobody is looking yet) and "in review"
 * once it is sent; anything the server lists as missing is "to do" whatever
 * its row says, because a PAN photo without the PAN number is not done.
 */
export function itemState(view: ApplicationView, kind: ItemKind): ItemState {
  const item = view.items.find(i => i.kind === kind);
  if (item?.status === 'NEEDS_CHANGE') return 'fix';
  if (!item || item.status === 'MISSING' || view.missing.includes(kind))
    return 'todo';
  if (item.status === 'ACCEPTED') return 'accepted';
  return view.status === 'DRAFT' ? 'added' : 'inReview';
}

export const PHOTO_KINDS: readonly PhotoKind[] = [
  'SELFIE',
  'RC',
  'AADHAAR_FRONT',
  'AADHAAR_BACK',
  'PAN',
  'LICENCE_FRONT',
  'LICENCE_BACK',
  'BANK_PROOF',
];

// --- who sees what -----------------------------------------------------------------

/** An old server sends no `onboarding`: every rider it knows was made by an admin. */
export function canWork(me: RiderMe | null | undefined): boolean {
  return me != null && (me.onboarding ?? 'APPROVED') === 'APPROVED';
}

/**
 * Tabs or the application, before and after /rider/me answers. The last
 * answer is remembered on the phone so an approved rider opening the app on
 * a dead network goes straight to work instead of a blank screen, and a new
 * rider does not see the tabs flash before their application.
 */
export function gateFor(
  me: RiderMe | null,
  remembered: RiderOnboarding | null,
  loading: boolean,
): 'wait' | 'onboarding' | 'app' {
  if (me) return canWork(me) ? 'app' : 'onboarding';
  if (remembered) return remembered === 'APPROVED' ? 'app' : 'onboarding';
  return loading ? 'wait' : 'app';
}

// --- step forms ---------------------------------------------------------------------

export type FieldErrors = Record<string, string>;
type Checked<B> = { errors: FieldErrors; body: B | null };

function checked<B>(errors: FieldErrors, body: B): Checked<B> {
  return Object.keys(errors).length ? { errors, body: null } : { errors, body };
}

/** `_text` on the server: whitespace collapsed, then a length range. */
function text(
  errors: FieldErrors,
  field: string,
  raw: string,
  low: number,
  high: number,
): string {
  const value = raw.split(/\s+/).filter(Boolean).join(' ');
  if (value.length < low || value.length > high)
    errors[field] = value ? 'bad_length' : 'required';
  return value;
}

export type PersonalForm = {
  full_name: string;
  dob: Dmy;
  city: string;
  address_line: string;
  pincode: string;
  emergency_name: string;
  emergency_phone: string;
};

export function validatePersonal(form: PersonalForm, today: string) {
  const errors: FieldErrors = {};
  const full_name = text(errors, 'full_name', form.full_name, 2, 120);
  const date_of_birth = parseDmy(form.dob.dd, form.dob.mm, form.dob.yyyy);
  if (!date_of_birth) errors.date_of_birth = 'bad_date';
  else if (!isAdult(date_of_birth, today)) errors.date_of_birth = 'too_young';
  const city = text(errors, 'city', form.city, 2, 80);
  const address_line = text(errors, 'address_line', form.address_line, 5, 240);
  const pincode = validPincode(form.pincode);
  if (!pincode) errors.pincode = 'bad_pincode';
  const emergency_name = text(
    errors,
    'emergency_name',
    form.emergency_name,
    2,
    120,
  );
  const emergency_phone = validMobile(form.emergency_phone);
  if (!emergency_phone) errors.emergency_phone = 'bad_phone';
  return checked(errors, {
    full_name,
    date_of_birth: date_of_birth ?? '',
    city,
    address_line,
    pincode: pincode ?? '',
    emergency_name,
    emergency_phone: emergency_phone ?? '',
  });
}

export type VehicleForm = {
  vehicle_type: VehicleType | null;
  vehicle_number: string;
};

export function validateVehicle(
  form: VehicleForm,
): Checked<{ vehicle_type: VehicleType; vehicle_number?: string }> {
  if (!form.vehicle_type)
    return { errors: { vehicle_type: 'required' }, body: null };
  if (!needsRc(form.vehicle_type))
    return { errors: {}, body: { vehicle_type: form.vehicle_type } };
  const plate = cleanPlate(form.vehicle_number);
  if (!plate) return { errors: { vehicle_number: 'bad_plate' }, body: null };
  return {
    errors: {},
    body: { vehicle_type: form.vehicle_type, vehicle_number: plate },
  };
}

export type DocumentsForm = {
  aadhaar_last4: string;
  pan: string;
  licence_number: string;
  licence_expiry: Dmy;
};
/** Which document fields the rider may change now: their item is a draft, or flagged. */
export type DocumentsEditable = {
  aadhaar: boolean;
  pan: boolean;
  licence: boolean;
};

export function validateDocuments(
  form: DocumentsForm,
  vehicle: VehicleType | null,
  may: DocumentsEditable,
  today: string,
) {
  const errors: FieldErrors = {};
  const body: {
    aadhaar_last4?: string;
    pan?: string;
    licence_number?: string;
    licence_expiry?: string;
  } = {};
  if (may.aadhaar) {
    const last4 = form.aadhaar_last4.trim();
    if (/^\d{4}$/.test(last4)) body.aadhaar_last4 = last4;
    else errors.aadhaar_last4 = 'bad_aadhaar_last4';
  }
  if (may.pan) {
    const pan = validPan(form.pan);
    if (pan) body.pan = pan;
    else errors.pan = 'bad_pan';
  }
  if (may.licence && needsLicence(vehicle)) {
    const number = form.licence_number
      .toUpperCase()
      .replace(/\s/g, '')
      .replace(/-/g, '');
    if (number.length >= 6 && number.length <= 20 && /^[A-Z0-9]+$/.test(number))
      body.licence_number = number;
    else errors.licence_number = 'bad_licence';
    const expiry = parseDmy(
      form.licence_expiry.dd,
      form.licence_expiry.mm,
      form.licence_expiry.yyyy,
    );
    if (!expiry) errors.licence_expiry = 'bad_date';
    else if (!licenceValid(expiry, today))
      errors.licence_expiry = 'licence_expired';
    else body.licence_expiry = expiry;
  }
  return checked(errors, body);
}

export type BankForm = {
  bank_holder: string;
  account_number: string;
  account_number_again: string;
  ifsc: string;
  upi_id: string;
};

export function validateBank(form: BankForm) {
  const errors: FieldErrors = {};
  const bank_holder = text(errors, 'bank_holder', form.bank_holder, 2, 120);
  const body: {
    bank_holder: string;
    account_number?: string;
    account_number_again?: string;
    ifsc?: string;
    upi_id?: string;
  } = { bank_holder };
  const rawAccount = form.account_number.trim();
  const rawUpi = form.upi_id.trim();
  if (!rawAccount && !rawUpi) errors.account_number = 'bank_required';
  if (rawAccount) {
    const account = validAccount(rawAccount, form.account_number_again);
    if (!ACCOUNT.test(squash(rawAccount)))
      errors.account_number = 'bad_account';
    else if (!account) errors.account_number_again = 'account_mismatch';
    else {
      body.account_number = account;
      body.account_number_again = account;
    }
    const ifsc = validIfsc(form.ifsc);
    if (ifsc) body.ifsc = ifsc;
    else errors.ifsc = 'bad_ifsc';
  }
  if (rawUpi) {
    const upi = validUpi(rawUpi);
    if (upi) body.upi_id = upi;
    else errors.upi_id = 'bad_upi';
  }
  return checked(errors, body);
}

// --- errors in words ----------------------------------------------------------------

/**
 * Every code the sign-up and application routes answer with, as a sentence
 * key. Keys rather than sentences so a language switch applies; `http.ts`
 * reads this table too, so an ApiError's message is already in words.
 */
export const ONBOARDING_ERRORS: Record<string, Key> = {
  too_young: 'onboarding.err.tooYoung',
  bad_date: 'onboarding.err.badDate',
  bad_pincode: 'onboarding.err.badPincode',
  bad_phone: 'onboarding.err.badPhone',
  required: 'onboarding.err.required',
  bad_length: 'onboarding.err.badLength',
  bad_plate: 'onboarding.err.badPlate',
  bad_aadhaar_last4: 'onboarding.err.badAadhaar',
  bad_pan: 'onboarding.err.badPan',
  bad_licence: 'onboarding.err.badLicence',
  licence_expired: 'onboarding.err.licenceExpired',
  bank_required: 'onboarding.err.bankRequired',
  bad_account: 'onboarding.err.badAccount',
  account_mismatch: 'onboarding.err.accountMismatch',
  bad_ifsc: 'onboarding.err.badIfsc',
  bad_upi: 'onboarding.err.badUpi',
  not_editable: 'onboarding.err.notEditable',
  no_secrets: 'onboarding.err.noSecrets',
  too_large: 'onboarding.err.tooLarge',
  not_an_image: 'onboarding.err.notAnImage',
  storage_not_configured: 'onboarding.err.storage',
  phone_in_use: 'onboarding.err.phoneInUse',
  code_too_soon: 'onboarding.err.codeTooSoon',
  code_too_many: 'onboarding.err.codeTooMany',
  code_wrong: 'onboarding.err.codeWrong',
  code_expired: 'onboarding.err.codeExpired',
  code_locked: 'onboarding.err.codeLocked',
  state_changed: 'onboarding.err.stateChanged',
  rider_not_approved: 'onboarding.err.notApproved',
  missing: 'onboarding.err.missing',
  flagged: 'onboarding.err.flagged',
  photo_needed: 'onboarding.err.photoNeeded',
};

export function errorKey(code: string | null | undefined): Key | null {
  return code && Object.prototype.hasOwnProperty.call(ONBOARDING_ERRORS, code)
    ? ONBOARDING_ERRORS[code]!
    : null;
}

/** A section 422 is `{field, error}`: put the sentence under that field. */
export function fieldErrorsFrom(detail: unknown): FieldErrors {
  if (
    detail &&
    typeof detail === 'object' &&
    'field' in detail &&
    'error' in detail
  ) {
    const { field, error } = detail as { field: unknown; error: unknown };
    if (typeof field === 'string' && typeof error === 'string')
      return { [field]: error };
  }
  return {};
}
