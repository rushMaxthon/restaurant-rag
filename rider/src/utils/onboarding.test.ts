import type {
  ApplicationItem,
  ApplicationView,
  ItemKind,
  RiderMe,
} from '@/types/api';
import {
  applicationProblem,
  canWork,
  cleanPlate,
  errorKey,
  fieldErrorsFrom,
  firstIncompleteStep,
  gateFor,
  isAdult,
  itemState,
  isoToDmy,
  licenceValid,
  parseDmy,
  progress,
  requiredItems,
  todayIso,
  validAccount,
  validIfsc,
  validPan,
  validPincode,
  validUpi,
  validateBank,
  validateDocuments,
  validatePersonal,
  validateVehicle,
} from './onboarding';

/**
 * The same cases as backend/tests/test_rider_onboarding_rules.py: the phone
 * checks first so a rider hears "that IFSC is wrong" before sending, but only
 * if it agrees with the server - a rule stricter here refuses a rider the
 * server would take, a looser one sends them to a 422 they cannot read.
 */

describe('requiredItems mirrors the backend', () => {
  it('a motorbike needs licence and RC', () => {
    for (const kind of [
      'RC',
      'LICENCE_FRONT',
      'LICENCE_BACK',
      'VEHICLE_DETAILS',
    ]) {
      expect(requiredItems('BIKE')).toContain(kind);
      expect(requiredItems('SCOOTER')).toContain(kind);
    }
  });

  it('a bicycle and a low-speed EV need neither', () => {
    for (const kind of [
      'RC',
      'LICENCE_FRONT',
      'LICENCE_BACK',
      'VEHICLE_DETAILS',
    ]) {
      expect(requiredItems('CYCLE')).not.toContain(kind);
      expect(requiredItems('EV_SCOOTER')).not.toContain(kind);
    }
  });

  it('everyone needs identity and bank, even before choosing a vehicle', () => {
    for (const vehicle of [
      'BIKE',
      'SCOOTER',
      'EV_SCOOTER',
      'CYCLE',
      null,
    ] as const) {
      for (const kind of [
        'PERSONAL',
        'SELFIE',
        'AADHAAR_FRONT',
        'AADHAAR_BACK',
        'PAN',
        'BANK_DETAILS',
      ]) {
        expect(requiredItems(vehicle)).toContain(kind);
      }
    }
  });

  it('a bank account needs its proof; a UPI ID alone does not', () => {
    expect(requiredItems('CYCLE', true)).toContain('BANK_PROOF');
    expect(requiredItems('CYCLE', false)).not.toContain('BANK_PROOF');
  });
});

describe('validators', () => {
  it('normalises plates', () => {
    expect(cleanPlate(' gj 05 ab 1234 ')).toBe('GJ05AB1234');
    expect(cleanPlate('GJ-5-1234')).toBe('GJ51234');
    expect(cleanPlate('22 BH 1234 AA')).toBe('22BH1234AA');
    expect(cleanPlate('hello')).toBeNull();
  });

  it('checks PAN, IFSC and PIN code', () => {
    expect(validPan('abcde1234f')).toBe('ABCDE1234F');
    expect(validPan('ABCDE12345')).toBeNull();
    expect(validIfsc('sbin0001234')).toBe('SBIN0001234');
    expect(validIfsc('SBIN1001234')).toBeNull();
    expect(validPincode('395009')).toBe('395009');
    expect(validPincode('095009')).toBeNull();
  });

  it('needs the account number twice, the same', () => {
    expect(validAccount('1234 5678 9012', '123456789012')).toBe('123456789012');
    expect(validAccount('123456789012', '123456789013')).toBeNull();
    expect(validAccount('12345', '12345')).toBeNull();
  });

  it('lower-cases a UPI ID', () => {
    expect(validUpi('Ravi.k@okaxis')).toBe('ravi.k@okaxis');
    expect(validUpi('ravi')).toBeNull();
  });
});

describe('dates', () => {
  it('reads DD/MM/YYYY and refuses a day that does not exist', () => {
    expect(parseDmy('9', '10', '2008')).toBe('2008-10-09');
    expect(parseDmy('29', '02', '2008')).toBe('2008-02-29');
    expect(parseDmy('29', '02', '2009')).toBeNull();
    expect(parseDmy('31', '04', '2000')).toBeNull();
    expect(parseDmy('', '04', '2000')).toBeNull();
    expect(parseDmy('01', '13', '2000')).toBeNull();
    expect(parseDmy('01', '01', '99')).toBeNull();
  });

  it('turns the server date back into the three boxes', () => {
    expect(isoToDmy('2008-10-09')).toEqual({
      dd: '09',
      mm: '10',
      yyyy: '2008',
    });
    expect(isoToDmy(null)).toEqual({ dd: '', mm: '', yyyy: '' });
  });

  it("today is the phone's local day", () => {
    expect(todayIso(new Date(2026, 9, 9, 23, 30))).toBe('2026-10-09');
  });

  it('is 18 on the day', () => {
    expect(isAdult('2008-10-09', '2026-10-09')).toBe(true);
    expect(isAdult('2008-10-10', '2026-10-09')).toBe(false);
  });

  it('born on 29 February: the birthday is 1 March', () => {
    expect(isAdult('2008-02-29', '2026-02-28')).toBe(false);
    expect(isAdult('2008-02-29', '2026-03-01')).toBe(true);
  });

  it('a licence must expire after today', () => {
    expect(licenceValid('2026-10-08', '2026-10-09')).toBe(false);
    expect(licenceValid('2026-10-09', '2026-10-09')).toBe(false);
    expect(licenceValid('2026-10-10', '2026-10-09')).toBe(true);
  });
});

describe('step forms', () => {
  const today = '2026-10-09';
  const personal = {
    full_name: 'Ravi Kumar',
    dob: { dd: '01', mm: '01', yyyy: '2000' },
    city: 'Surat',
    address_line: '12 Ring Road',
    pincode: '395009',
    emergency_name: 'Sita',
    emergency_phone: '9876543210',
  };

  it('a complete About-you form has no errors and becomes the API body', () => {
    const result = validatePersonal(personal, today);
    expect(result.errors).toEqual({});
    expect(result.body).toEqual({
      full_name: 'Ravi Kumar',
      date_of_birth: '2000-01-01',
      city: 'Surat',
      address_line: '12 Ring Road',
      pincode: '395009',
      emergency_name: 'Sita',
      emergency_phone: '+919876543210',
    });
  });

  it('names every wrong field at once', () => {
    const result = validatePersonal(
      {
        ...personal,
        full_name: ' ',
        dob: { dd: '01', mm: '01', yyyy: '2015' },
        pincode: '12',
        emergency_phone: '98765',
        address_line: 'abc',
      },
      today,
    );
    expect(result.body).toBeNull();
    expect(result.errors).toEqual({
      full_name: 'required',
      date_of_birth: 'too_young',
      pincode: 'bad_pincode',
      emergency_phone: 'bad_phone',
      address_line: 'bad_length',
    });
  });

  it('a bad date is bad_date, not too_young', () => {
    expect(
      validatePersonal(
        { ...personal, dob: { dd: '31', mm: '02', yyyy: '2000' } },
        today,
      ).errors,
    ).toEqual({ date_of_birth: 'bad_date' });
  });

  it('vehicle: a plate only for a registered vehicle', () => {
    expect(
      validateVehicle({ vehicle_type: null, vehicle_number: '' }).errors,
    ).toEqual({
      vehicle_type: 'required',
    });
    expect(
      validateVehicle({ vehicle_type: 'BIKE', vehicle_number: 'x' }).errors,
    ).toEqual({
      vehicle_number: 'bad_plate',
    });
    expect(
      validateVehicle({ vehicle_type: 'BIKE', vehicle_number: 'gj 05 ab 1234' })
        .body,
    ).toEqual({
      vehicle_type: 'BIKE',
      vehicle_number: 'GJ05AB1234',
    });
    expect(
      validateVehicle({ vehicle_type: 'CYCLE', vehicle_number: 'junk' }).body,
    ).toEqual({
      vehicle_type: 'CYCLE',
    });
  });

  it('documents: only the fields the rider may edit are checked and sent', () => {
    const form = {
      aadhaar_last4: '1234',
      pan: 'abcde1234f',
      licence_number: 'GJ05 20190001234',
      licence_expiry: { dd: '01', mm: '01', yyyy: '2030' },
    };
    const all = { aadhaar: true, pan: true, licence: true };
    expect(validateDocuments(form, 'BIKE', all, today).body).toEqual({
      aadhaar_last4: '1234',
      pan: 'ABCDE1234F',
      licence_number: 'GJ0520190001234',
      licence_expiry: '2030-01-01',
    });
    // A bicycle has no licence fields at all.
    expect(validateDocuments(form, 'CYCLE', all, today).body).toEqual({
      aadhaar_last4: '1234',
      pan: 'ABCDE1234F',
    });
    // Sent back for the PAN only: the accepted Aadhaar is not sent again.
    expect(
      validateDocuments(
        { ...form, aadhaar_last4: '' },
        'BIKE',
        { aadhaar: false, pan: true, licence: false },
        today,
      ).body,
    ).toEqual({ pan: 'ABCDE1234F' });
  });

  it('documents: an expired licence and a short Aadhaar', () => {
    const result = validateDocuments(
      {
        aadhaar_last4: '12',
        pan: 'ABCDE1234F',
        licence_number: 'GJ05',
        licence_expiry: { dd: '01', mm: '01', yyyy: '2020' },
      },
      'SCOOTER',
      { aadhaar: true, pan: true, licence: true },
      today,
    );
    expect(result.errors).toEqual({
      aadhaar_last4: 'bad_aadhaar_last4',
      licence_number: 'bad_licence',
      licence_expiry: 'licence_expired',
    });
  });

  it('bank: an account (twice, with IFSC) or a UPI ID', () => {
    const empty = {
      bank_holder: 'Ravi',
      account_number: '',
      account_number_again: '',
      ifsc: '',
      upi_id: '',
    };
    expect(validateBank(empty).errors).toEqual({
      account_number: 'bank_required',
    });
    expect(validateBank({ ...empty, upi_id: 'ravi@okaxis' }).body).toEqual({
      bank_holder: 'Ravi',
      upi_id: 'ravi@okaxis',
    });
    expect(
      validateBank({
        ...empty,
        account_number: '123456789012',
        account_number_again: '123456789013',
        ifsc: 'bad',
      }).errors,
    ).toEqual({ account_number_again: 'account_mismatch', ifsc: 'bad_ifsc' });
    expect(
      validateBank({
        ...empty,
        account_number: '123456789012',
        account_number_again: '123456789012',
        ifsc: 'sbin0001234',
      }).body,
    ).toEqual({
      bank_holder: 'Ravi',
      account_number: '123456789012',
      account_number_again: '123456789012',
      ifsc: 'SBIN0001234',
    });
  });
});

function item(
  kind: ItemKind,
  section: ApplicationItem['section'],
  status: ApplicationItem['status'] = 'MISSING',
): ApplicationItem {
  return {
    kind,
    section,
    status,
    reason: '',
    required: true,
    has_photo: false,
    editable: true,
  };
}

function view(partial: Partial<ApplicationView>): ApplicationView {
  return {
    rider_user_id: 'u',
    status: 'DRAFT',
    final_reason: '',
    submitted_at: null,
    decided_at: null,
    sections: {
      personal: {
        full_name: '',
        date_of_birth: null,
        city: '',
        address_line: '',
        pincode: '',
        emergency_name: '',
        emergency_phone: '',
      },
      vehicle: { vehicle_type: null, vehicle_number: '' },
      documents: {
        aadhaar_last4: '',
        pan_last4: '',
        licence_last4: '',
        licence_expiry: null,
      },
      bank: { bank_holder: '', bank_account_last4: '', ifsc: '', upi_id: '' },
    },
    items: [],
    required: [],
    missing: [],
    ...partial,
  };
}

describe('firstIncompleteStep resumes where the server says', () => {
  it('a new draft starts at About you', () => {
    expect(
      firstIncompleteStep(view({ missing: ['PERSONAL', 'SELFIE', 'PAN'] })),
    ).toBe('personal');
  });

  it('a missing selfie keeps the rider on About you', () => {
    expect(firstIncompleteStep(view({ missing: ['SELFIE', 'PAN'] }))).toBe(
      'personal',
    );
  });

  it('no vehicle chosen yet is the vehicle step, even though nothing lists it as missing', () => {
    expect(firstIncompleteStep(view({ missing: ['PAN'] }))).toBe('vehicle');
  });

  it('then the earliest missing section', () => {
    const base = view({ missing: ['BANK_DETAILS', 'AADHAAR_BACK'] });
    base.sections.vehicle.vehicle_type = 'CYCLE';
    expect(firstIncompleteStep(base)).toBe('documents');
  });

  it('nothing missing is the review', () => {
    const base = view({ missing: [] });
    base.sections.vehicle.vehicle_type = 'CYCLE';
    expect(firstIncompleteStep(base)).toBe('review');
  });

  it('sent back: the first flagged step', () => {
    const base = view({
      status: 'CHANGES_NEEDED',
      items: [
        item('PERSONAL', 'personal', 'ACCEPTED'),
        item('BANK_PROOF', 'bank', 'NEEDS_CHANGE'),
      ],
    });
    base.sections.vehicle.vehicle_type = 'BIKE';
    expect(firstIncompleteStep(base)).toBe('bank');
  });
});

describe('submitting', () => {
  it('says what is still missing or flagged before the server does', () => {
    const base = view({ missing: ['PAN'] });
    expect(applicationProblem(base)).toBe('missing');
    expect(
      applicationProblem(
        view({
          status: 'CHANGES_NEEDED',
          items: [item('PAN', 'documents', 'NEEDS_CHANGE')],
        }),
      ),
    ).toBe('flagged');
    expect(applicationProblem(view({ status: 'SUBMITTED' }))).toBe('locked');
    expect(applicationProblem(view({}))).toBeNull();
  });
});

describe('errors from the server', () => {
  it('every validation code has a sentence', () => {
    for (const code of [
      'too_young',
      'bad_date',
      'bad_pincode',
      'bad_phone',
      'required',
      'bad_length',
      'bad_plate',
      'bad_aadhaar_last4',
      'bad_pan',
      'bad_licence',
      'licence_expired',
      'bank_required',
      'account_mismatch',
      'bad_ifsc',
      'bad_upi',
      'not_editable',
      'no_secrets',
      'too_large',
      'not_an_image',
      'storage_not_configured',
      'phone_in_use',
      'code_too_soon',
      'code_too_many',
      'code_wrong',
      'code_expired',
      'code_locked',
      'state_changed',
      'rider_not_approved',
    ]) {
      expect([code, typeof errorKey(code)]).toEqual([code, 'string']);
    }
    expect(errorKey('something_else')).toBeNull();
  });

  it('a 422 names its field', () => {
    expect(fieldErrorsFrom({ field: 'ifsc', error: 'bad_ifsc' })).toEqual({
      ifsc: 'bad_ifsc',
    });
    expect(fieldErrorsFrom('not_editable')).toEqual({});
    expect(fieldErrorsFrom(null)).toEqual({});
  });
});

describe('who sees the tabs', () => {
  const me = (onboarding?: RiderMe['onboarding']) =>
    ({ onboarding } as RiderMe);

  it('only an approved rider works; an old server that says nothing means approved', () => {
    expect(canWork(me('APPROVED'))).toBe(true);
    expect(canWork(me(undefined))).toBe(true);
    expect(canWork(me('PENDING'))).toBe(false);
    expect(canWork(me('REJECTED'))).toBe(false);
    expect(canWork(null)).toBe(false);
  });

  it('/rider/me decides; before it answers, the last answer on this phone', () => {
    expect(gateFor(me('PENDING'), 'APPROVED', false)).toBe('onboarding');
    expect(gateFor(me('APPROVED'), 'PENDING', false)).toBe('app');
    expect(gateFor(null, 'PENDING', true)).toBe('onboarding');
    expect(gateFor(null, 'APPROVED', true)).toBe('app');
  });

  it('nothing known yet: wait for /me, then fall back to the app if it failed', () => {
    expect(gateFor(null, null, true)).toBe('wait');
    expect(gateFor(null, null, false)).toBe('app');
  });
});

describe('progress', () => {
  it('counts what is given and not flagged', () => {
    const base = view({
      required: ['PERSONAL', 'SELFIE', 'PAN', 'BANK_DETAILS'],
      missing: ['SELFIE'],
      items: [item('PAN', 'documents', 'NEEDS_CHANGE')],
    });
    expect(progress(base)).toEqual({ done: 2, total: 4 });
  });
});

describe('itemState', () => {
  it('says what each row is', () => {
    const base = view({
      missing: ['AADHAAR_FRONT'],
      items: [
        item('PERSONAL', 'personal', 'PENDING'),
        item('AADHAAR_FRONT', 'documents', 'PENDING'),
        item('PAN', 'documents', 'NEEDS_CHANGE'),
        item('SELFIE', 'personal', 'ACCEPTED'),
      ],
    });
    expect(itemState(base, 'PERSONAL')).toBe('added');
    // The photo is there but the last 4 digits are not.
    expect(itemState(base, 'AADHAAR_FRONT')).toBe('todo');
    expect(itemState(base, 'PAN')).toBe('fix');
    expect(itemState(base, 'SELFIE')).toBe('accepted');
    expect(itemState(base, 'RC')).toBe('todo');
    expect(itemState({ ...base, status: 'SUBMITTED' }, 'PERSONAL')).toBe(
      'inReview',
    );
  });
});
