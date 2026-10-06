/**
 * Rules for the Payouts screen, kept out of the component so they can be
 * tested without rendering it. The server is still the authority: it pins
 * an owner to their restaurant and never sends them the platform's half.
 */
import { isoDay, type PeriodRange } from "./dashboardPeriod";
import type { PayoutAccountInput, PayoutAccountStatus, PayoutRow, PayoutStatus } from "../types/app";

/**
 * What each status is called, for the admin and for the owner. The colour
 * comes from `resolveStatusPillTone`, which knows these words.
 */
export const PAYOUT_STATUS_META: Record<PayoutStatus, { label: string; ownerLabel: string }> = {
  WAITING_ACCOUNT: { label: "Waiting", ownerLabel: "Waiting for your account" },
  HELD: { label: "Held", ownerLabel: "Held until delivered" },
  RELEASED: { label: "Released", ownerLabel: "On its way" },
  SETTLED: { label: "Settled", ownerLabel: "In your bank" },
  REVERSED: { label: "Reversed", ownerLabel: "Taken back" },
  FAILED: { label: "Failed", ownerLabel: "Being looked into" },
  BLOCKED: { label: "Blocked", ownerLabel: "Being looked into" },
  NOT_APPLICABLE: { label: "Not via platform", ownerLabel: "Paid to you directly" },
};

export const ACCOUNT_STATUS_META: Record<PayoutAccountStatus, { label: string; hint: string }> = {
  DRAFT: { label: "Draft", hint: "Saved here, not sent to Razorpay yet." },
  SUBMITTED: { label: "Submitted", hint: "Sent to Razorpay." },
  UNDER_REVIEW: { label: "Under review", hint: "Razorpay is checking the details, usually 1-3 working days." },
  NEEDS_CLARIFICATION: { label: "Needs a correction", hint: "Razorpay asked for the changes listed below." },
  ACTIVE: { label: "Active", hint: "Payments are passed on to this bank account." },
  SUSPENDED: { label: "Suspended", hint: "Razorpay has stopped payouts to this account." },
};

function cell(value: string | number | null | undefined): string {
  const text = value === null || value === undefined ? "" : String(value);
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function payoutsCsv(rows: PayoutRow[], isAdmin: boolean): string {
  const header = [
    "Order placed", "Order", "Restaurant", "Restaurant share", ...(isAdmin ? ["Platform keeps"] : []),
    "Currency", "Status", "Razorpay transfer", "Released", "Settled", "Note",
  ];
  const lines = rows.map((row) =>
    [
      row.order_placed_at, row.order_id, row.restaurant_name, row.restaurant_share,
      ...(isAdmin ? [row.platform_keeps] : []), row.currency,
      isAdmin ? PAYOUT_STATUS_META[row.status].label : PAYOUT_STATUS_META[row.status].ownerLabel,
      row.transfer_id, row.released_at, row.settled_at, row.last_error,
    ].map(cell).join(","),
  );
  return [header.map(cell).join(","), ...lines].join("\n");
}

const PAN = /^[A-Z]{5}[0-9]{4}[A-Z]$/;
const IFSC = /^[A-Z]{4}0[A-Z0-9]{6}$/;
const REQUIRED = [
  "legal_business_name", "contact_name", "email", "phone", "street", "city", "state", "beneficiary_name",
] as const;

/** The same checks the server makes, so a typo is caught before Save. */
export function accountInputErrors(input: PayoutAccountInput): Partial<Record<keyof PayoutAccountInput, string>> {
  const errors: Partial<Record<keyof PayoutAccountInput, string>> = {};
  if (!PAN.test(input.pan.trim().toUpperCase())) errors.pan = "Five letters, four digits, a letter - like ABCDE1234F.";
  if (!IFSC.test(input.ifsc.trim().toUpperCase())) errors.ifsc = "Four letters, a zero, then six letters or digits.";
  if (!/^[1-9][0-9]{5}$/.test(input.postal_code.trim())) errors.postal_code = "Six digits.";
  if (!/^[0-9]{9,18}$/.test(input.bank_account_number.replace(/\s/g, ""))) {
    errors.bank_account_number = "9 to 18 digits.";
  }
  for (const key of REQUIRED) {
    if (!input[key].trim()) errors[key] = "Required.";
  }
  return errors;
}

/** The server takes whole days, both included; a range's `end` is exclusive. */
export function periodQuery(range: Pick<PeriodRange, "start" | "end">): { date_from: string; date_to: string } {
  return { date_from: isoDay(range.start), date_to: isoDay(new Date(range.end.getTime() - 1)) };
}
