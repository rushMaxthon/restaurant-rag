import { describe, expect, it } from "vitest";

import { ACCOUNT_STATUS_META, PAYOUT_STATUS_META, accountInputErrors, payoutsCsv, periodQuery } from "./payouts";
import type { PayoutAccountInput, PayoutRow, PayoutStatus } from "../types/app";

const row: PayoutRow = {
  id: "p1", order_id: "o1", order_placed_at: "2026-10-05T10:00:00Z", restaurant_id: "r1",
  restaurant_name: "Darshan, Surat", restaurant_share: "496.00", platform_keeps: "102.20", currency: "INR",
  status: "HELD", transfer_id: "trf_1", last_error: null, released_at: null, settled_at: null,
};

const good: PayoutAccountInput = {
  legal_business_name: "Darshan Foods", business_type: "proprietorship", pan: "ABCDE1234F",
  contact_name: "Darshan", email: "d@x.in", phone: "9876543210", street: "1 Road", city: "Surat",
  state: "Gujarat", postal_code: "395007", bank_account_number: "123456789012", ifsc: "HDFC0000123",
  beneficiary_name: "Darshan Foods",
};

const STATUSES: PayoutStatus[] = [
  "WAITING_ACCOUNT", "HELD", "RELEASED", "SETTLED", "REVERSED", "FAILED", "BLOCKED", "NOT_APPLICABLE",
];

describe("payout statuses", () => {
  it("names every status for both readers", () => {
    for (const status of STATUSES) {
      expect(PAYOUT_STATUS_META[status].label).toBeTruthy();
      expect(PAYOUT_STATUS_META[status].ownerLabel).toBeTruthy();
    }
    expect(PAYOUT_STATUS_META.SETTLED.ownerLabel).toBe("In your bank");
    expect(ACCOUNT_STATUS_META.ACTIVE.label).toBe("Active");
  });
});

describe("payoutsCsv", () => {
  it("quotes a comma and gives the admin both halves", () => {
    const csv = payoutsCsv([row], true);
    expect(csv.split("\n")[0]).toContain("Platform keeps");
    expect(csv).toContain('"Darshan, Surat"');
    expect(csv).toContain("102.20");
  });

  it("never gives the owner the platform's half", () => {
    const csv = payoutsCsv([row], false);
    expect(csv).not.toContain("Platform keeps");
    expect(csv).not.toContain("102.20");
  });
});

describe("accountInputErrors", () => {
  it("accepts a good form", () => {
    expect(accountInputErrors(good)).toEqual({});
  });

  it("says what is wrong with a PAN, an IFSC, a PIN and an account number", () => {
    const errors = accountInputErrors({ ...good, pan: "ABC", ifsc: "HDFC123", postal_code: "39", bank_account_number: "12ab" });
    expect(Object.keys(errors).sort()).toEqual(["bank_account_number", "ifsc", "pan", "postal_code"]);
  });

  it("treats a lowercase PAN as the same PAN", () => {
    expect(accountInputErrors({ ...good, pan: "abcde1234f" })).toEqual({});
  });
});

describe("periodQuery", () => {
  it("sends whole days, the end day included", () => {
    const query = periodQuery({ start: new Date(2026, 9, 1), end: new Date(2026, 9, 6) });
    expect(query).toEqual({ date_from: "2026-10-01", date_to: "2026-10-05" });
  });
});

describe("payout status colours", () => {
  it("colours money owed amber, money moving blue and a stuck payout red", async () => {
    const { resolveStatusPillTone } = await import("../components/statusPillUtils");
    expect(resolveStatusPillTone("HELD")).toBe("warning");
    expect(resolveStatusPillTone("WAITING_ACCOUNT")).toBe("warning");
    expect(resolveStatusPillTone("RELEASED")).toBe("info");
    expect(resolveStatusPillTone("SETTLED")).toBe("success");
    expect(resolveStatusPillTone("BLOCKED")).toBe("danger");
    expect(resolveStatusPillTone("NOT_APPLICABLE")).toBe("muted");
  });
});
