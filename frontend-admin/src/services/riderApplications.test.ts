import { describe, expect, it } from 'vitest';

import type { ApplicationItem, ItemKind, RiderApplicationDetail } from '../types/app';
import {
  dueForRefresh,
  firstTab,
  ITEM_LABELS,
  REASONS,
  STATUS_META,
  applicationErrorMessage,
  decisionState,
  eventLabel,
  ageOn,
  masked,
  mergePhotos,
  photoPairs,
  reviewItems,
  waitingLabel,
} from './riderApplications';

const item = (kind: ItemKind, status: ApplicationItem['status'] = 'PENDING', required = true): ApplicationItem => ({
  kind,
  status,
  reason: '',
  section: 'documents',
  required,
  has_photo: true,
  editable: false,
});

function detail(overrides: Partial<RiderApplicationDetail> = {}): RiderApplicationDetail {
  const items = overrides.items ?? [item('PERSONAL', 'ACCEPTED'), item('SELFIE', 'ACCEPTED'), item('PAN', 'ACCEPTED')];
  return {
    rider_user_id: 'r1',
    status: 'SUBMITTED',
    phone_number: '+919876543210',
    final_reason: '',
    submitted_at: '2026-10-09T08:00:00Z',
    decided_at: null,
    sections: {
      personal: {
        full_name: 'Ravi Patel',
        date_of_birth: '2000-01-01',
        city: 'Surat',
        address_line: '12 Ring Road',
        pincode: '395001',
        emergency_name: 'Asha',
        emergency_phone: '9876500000',
      },
      vehicle: { vehicle_type: 'BIKE', vehicle_number: 'GJ05AB1234' },
      documents: { aadhaar_last4: '1234', pan_last4: '567F', licence_last4: '9012', licence_expiry: '2030-01-01' },
      bank: { bank_holder: 'Ravi Patel', bank_account_last4: '9012', ifsc: 'HDFC0001234', upi_id: '' },
    },
    items,
    required: items.filter((i) => i.required).map((i) => i.kind),
    missing: [],
    photos: {},
    photos_error: null,
    events: [],
    ...overrides,
  };
}

describe('the decision bar', () => {
  it('approves only when every required item is accepted', () => {
    const state = decisionState(detail());
    expect(state.canApprove).toBe(true);
    expect(state.approveReason).toBeNull();
  });

  it('says how many items are still not accepted', () => {
    const state = decisionState(
      detail({ items: [item('PERSONAL', 'ACCEPTED'), item('SELFIE', 'PENDING'), item('PAN', 'NEEDS_CHANGE')] }),
    );
    expect(state.canApprove).toBe(false);
    expect(state.approveReason).toBe('2 items not accepted yet');
  });

  it('uses the singular for one item', () => {
    const state = decisionState(detail({ items: [item('PERSONAL', 'ACCEPTED'), item('SELFIE', 'PENDING')] }));
    expect(state.approveReason).toBe('1 item not accepted yet');
  });

  it('ignores an item the application does not require', () => {
    // An RC left over from when the rider said "motorbike" and then chose a
    // bicycle: the server never asks for it, so it cannot block approval.
    const state = decisionState(detail({ items: [item('PERSONAL', 'ACCEPTED'), item('RC', 'PENDING', false)] }));
    expect(state.canApprove).toBe(true);
  });

  it('needs at least one flag before sending back', () => {
    const state = decisionState(detail({ items: [item('PERSONAL', 'PENDING')] }));
    expect(state.canSendBack).toBe(false);
    expect(state.sendBackReason).toBe('Flag at least one item');
  });

  it('sends back once something is flagged', () => {
    const state = decisionState(detail({ items: [item('PERSONAL', 'NEEDS_CHANGE')] }));
    expect(state.canSendBack).toBe(true);
    expect(state.sendBackReason).toBeNull();
  });

  it('reviews items only while the application is submitted', () => {
    expect(decisionState(detail()).canReview).toBe(true);
    for (const status of ['DRAFT', 'CHANGES_NEEDED', 'APPROVED', 'REJECTED'] as const) {
      const state = decisionState(detail({ status }));
      expect(state.canReview).toBe(false);
      expect(state.canApprove).toBe(false);
      expect(state.canSendBack).toBe(false);
      expect(state.approveReason).toBeTruthy();
    }
  });

  it('rejects from submitted or changes needed, and reopens only a rejection', () => {
    expect(decisionState(detail({ status: 'SUBMITTED' })).canReject).toBe(true);
    expect(decisionState(detail({ status: 'CHANGES_NEEDED' })).canReject).toBe(true);
    expect(decisionState(detail({ status: 'APPROVED' })).canReject).toBe(false);
    expect(decisionState(detail({ status: 'REJECTED' })).canReopen).toBe(true);
    expect(decisionState(detail({ status: 'SUBMITTED' })).canReopen).toBe(false);
  });
});

describe('waiting time', () => {
  const now = new Date('2026-10-09T12:00:00Z');
  it('reads in minutes, hours, then days', () => {
    expect(waitingLabel('2026-10-09T11:48:00Z', now)).toBe('12 min');
    expect(waitingLabel('2026-10-09T09:00:00Z', now)).toBe('3 h');
    expect(waitingLabel('2026-10-07T11:00:00Z', now)).toBe('2 days');
    expect(waitingLabel('2026-10-08T11:00:00Z', now)).toBe('1 day');
  });

  it('says just now under a minute, and nothing when never submitted', () => {
    expect(waitingLabel('2026-10-09T11:59:30Z', now)).toBe('Just now');
    expect(waitingLabel(null, now)).toBe('—');
  });
});

describe('words on the page', () => {
  it('labels every item kind', () => {
    expect(ITEM_LABELS.RC).toBe('RC (registration)');
    expect(ITEM_LABELS.BANK_PROOF).toBe('Cheque / passbook');
    expect(ITEM_LABELS.LICENCE_BACK).toBe('Driving licence back');
    expect(Object.keys(ITEM_LABELS)).toHaveLength(11);
  });

  it('offers the five common reasons', () => {
    expect(REASONS).toHaveLength(5);
    expect(REASONS).toContain("Name doesn't match");
  });

  it('gives every status a label and a tone', () => {
    expect(STATUS_META.SUBMITTED.label).toBe('Submitted');
    expect(STATUS_META.REJECTED.tone).toBe('danger');
    expect(STATUS_META.APPROVED.tone).toBe('success');
  });

  it('shows only the last four digits', () => {
    expect(masked('9012')).toBe('•••• 9012');
    expect(masked('')).toBe('—');
  });

  it('describes a history entry with the item it was about', () => {
    expect(eventLabel({ at: '', action: 'ITEM_FLAGGED', item_kind: 'PAN', note: 'blurry', actor_name: 'Admin' })).toBe(
      'Flagged PAN card',
    );
    expect(eventLabel({ at: '', action: 'RESUBMITTED', item_kind: null, note: '', actor_name: null })).toBe('Resubmitted');
  });

  it('turns the server codes into sentences', () => {
    expect(applicationErrorMessage('state_changed')).toBe('Someone else just reviewed this - reloaded.');
    expect(applicationErrorMessage('not_all_accepted')).toMatch(/accept/i);
    expect(applicationErrorMessage('Something odd')).toBe('Something odd');
  });
});

describe('document cards', () => {
  it('pairs the front and back of Aadhaar and the licence, in reading order', () => {
    const items = [
      item('LICENCE_BACK'),
      item('PAN'),
      item('AADHAAR_BACK'),
      item('PERSONAL'),
      item('SELFIE'),
      item('AADHAAR_FRONT'),
      item('LICENCE_FRONT'),
      item('BANK_PROOF'),
    ];
    expect(photoPairs(items).map((group) => group.map((i) => i.kind))).toEqual([
      ['SELFIE'],
      ['AADHAAR_FRONT', 'AADHAAR_BACK'],
      ['PAN'],
      ['LICENCE_FRONT', 'LICENCE_BACK'],
      ['BANK_PROOF'],
    ]);
  });

  it('leaves out photos the application does not need', () => {
    const items = [item('SELFIE'), item('RC', 'MISSING', false)];
    expect(photoPairs(items)).toEqual([[items[0]]]);
  });

  it('reviews only required items', () => {
    expect(reviewItems([item('PERSONAL'), item('RC', 'PENDING', false)]).map((i) => i.kind)).toEqual(['PERSONAL']);
  });
});

describe('signed photo links', () => {
  const a1 = 'https://x.supabase.co/storage/v1/object/sign/riders/r1/pan-aaa.jpg?token=one';
  const a2 = 'https://x.supabase.co/storage/v1/object/sign/riders/r1/pan-aaa.jpg?token=two';
  const b = 'https://x.supabase.co/storage/v1/object/sign/riders/r1/pan-bbb.jpg?token=three';

  it('keeps the link it has for the same file, so a live hint does not reload every image', () => {
    expect(mergePhotos({ PAN: a1 }, { PAN: a2 })).toEqual({ PAN: a1 });
  });

  it('takes the new link when the rider uploaded a different file', () => {
    expect(mergePhotos({ PAN: a1 }, { PAN: b })).toEqual({ PAN: b });
  });

  it('drops a photo the server no longer sends', () => {
    expect(mergePhotos({ PAN: a1 }, {})).toEqual({});
  });
});

describe('age', () => {
  it('counts whole years, birthday included', () => {
    const now = new Date('2026-10-09T12:00:00Z');
    expect(ageOn('2000-10-09', now)).toBe(26);
    expect(ageOn('2000-10-10', now)).toBe(25);
    expect(ageOn(null, now)).toBeNull();
  });
});

describe('the Riders page settles its tabs once', () => {
  it('opens on Applications when someone was waiting at first look, else the map', () => {
    expect(firstTab(2)).toBe('applications');
    expect(firstTab(0)).toBe('map');
  });

  it('does not refetch the badge on every location ping', () => {
    expect(dueForRefresh(0, 1_000, 15_000)).toBe(false);
    expect(dueForRefresh(0, 15_000, 15_000)).toBe(true);
  });
});
