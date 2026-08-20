type PendingRegistrationDraft = {
  fullName: string;
  email: string;
  password: string;
  fullPhoneNumber: string;
};

let pendingRegistrationDraft: PendingRegistrationDraft | null = null;

export function setPendingRegistrationDraft(
  draft: PendingRegistrationDraft,
): void {
  pendingRegistrationDraft = draft;
}

export function getPendingRegistrationDraft(): PendingRegistrationDraft | null {
  return pendingRegistrationDraft;
}

export function clearPendingRegistrationDraft(): void {
  pendingRegistrationDraft = null;
}
