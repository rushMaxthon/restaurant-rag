import { Landmark, RefreshCw, Send } from "lucide-react";
import { useEffect, useState } from "react";

import { resolveStatusPillTone } from "./statusPillUtils";
import { ApiError, api } from "../services/api";
import { ACCOUNT_STATUS_META, accountInputErrors } from "../services/payouts";
import type { PayoutAccount, PayoutAccountInput, ToastMessage } from "../types/app";

const EMPTY: PayoutAccountInput = {
  legal_business_name: "", business_type: "proprietorship", pan: "", contact_name: "", email: "", phone: "",
  street: "", city: "", state: "", postal_code: "", bank_account_number: "", ifsc: "", beneficiary_name: "",
};

const FIELDS: Array<{ key: keyof PayoutAccountInput; label: string; hint?: string }> = [
  { key: "legal_business_name", label: "Legal business name", hint: "As on the PAN." },
  { key: "pan", label: "PAN" },
  { key: "contact_name", label: "Contact name" },
  { key: "email", label: "Email" },
  { key: "phone", label: "Phone" },
  { key: "street", label: "Registered address" },
  { key: "city", label: "City" },
  { key: "state", label: "State" },
  { key: "postal_code", label: "PIN code" },
  { key: "beneficiary_name", label: "Account holder's name" },
  { key: "bank_account_number", label: "Bank account number", hint: "Stored encrypted; only the last four are shown again." },
  { key: "ifsc", label: "IFSC" },
];

/**
 * A restaurant's Razorpay linked account. Only the platform admin fills it
 * in (the server refuses an owner); the owner sees where it stands and what
 * Razorpay still needs.
 */
export function PayoutAccountPanel({ token, restaurantId, isAdmin, onToast }: {
  token: string;
  /** Empty for an owner: the server answers with their own restaurant. */
  restaurantId: string;
  isAdmin: boolean;
  onToast: (title: string, description: string, tone?: ToastMessage["tone"]) => void;
}) {
  const [account, setAccount] = useState<PayoutAccount | null>(null);
  const [form, setForm] = useState<PayoutAccountInput>(EMPTY);
  const [busy, setBusy] = useState(false);
  const [touched, setTouched] = useState(false);

  useEffect(() => {
    let current = true;
    api
      .getPayoutAccount(token, restaurantId || undefined)
      .then((next) => {
        if (!current) return;
        setAccount(next);
        setForm(next ? { ...EMPTY, ...next, bank_account_number: "" } : EMPTY);
      })
      .catch((error: unknown) => {
        if (!current) return;
        onToast("Could not load the payout account", error instanceof ApiError ? error.message : "Please try again.", "error");
      });
    return () => {
      current = false;
    };
  }, [token, restaurantId, onToast]);

  const editable = isAdmin && (!account || account.status === "DRAFT" || account.status === "NEEDS_CLARIFICATION");
  const errors = accountInputErrors(form);
  const canSave = Object.keys(errors).length === 0;

  async function run(action: () => Promise<PayoutAccount>, done: string) {
    setBusy(true);
    try {
      const next = await action();
      setAccount(next);
      onToast(done, ACCOUNT_STATUS_META[next.status].hint, "success");
    } catch (error) {
      onToast("That did not work", error instanceof ApiError ? error.message : "Please try again.", "error");
    } finally {
      setBusy(false);
    }
  }

  const meta = account ? ACCOUNT_STATUS_META[account.status] : null;
  return (
    <section aria-labelledby="payout-account-title" className="elevated-panel">
      <h2 id="payout-account-title">
        <Landmark aria-hidden="true" size={18} /> Bank account for payouts
      </h2>
      {meta ? (
        <p>
          <span className={`status-pill status-pill--${resolveStatusPillTone(account?.status ?? "")}`}>{meta.label}</span>{" "}
          {meta.hint}
          {account?.bank_account_last4 ? ` Account ending ${account.bank_account_last4}.` : ""}
        </p>
      ) : (
        <p>
          {isAdmin
            ? "Not set up yet. Fill this in to start passing payments on to this restaurant."
            : "Your platform admin has not set up payouts for you yet."}
        </p>
      )}
      {account?.requirements.length ? (
        <ul>
          {account.requirements.map((need) => (
            <li key={need}>{need}</li>
          ))}
        </ul>
      ) : null}
      {account?.last_error ? <p role="alert">{account.last_error}</p> : null}

      {editable ? (
        <form
          className="form-grid"
          onSubmit={(event) => {
            event.preventDefault();
            setTouched(true);
            if (canSave) void run(() => api.savePayoutAccount(token, restaurantId, form), "Saved");
          }}
        >
          {FIELDS.map(({ key, label, hint }) => (
            <label className="field" key={key}>
              <span>{label}</span>
              <input
                aria-invalid={touched && Boolean(errors[key])}
                autoComplete="off"
                onChange={(event) => setForm({ ...form, [key]: event.target.value })}
                value={form[key]}
              />
              {touched && errors[key] ? <small role="alert">{errors[key]}</small> : hint ? <small>{hint}</small> : null}
            </label>
          ))}
          <div>
            <button className="secondary-button" disabled={busy} type="submit">
              Save
            </button>
            <button
              className="primary-button"
              disabled={busy || !account}
              onClick={() => void run(() => api.submitPayoutAccount(token, restaurantId), "Sent to Razorpay")}
              title={account ? "Open the linked account with Razorpay." : "Save the details first."}
              type="button"
            >
              <Send size={15} /> Send to Razorpay
            </button>
            {!account ? <small>Save the details first.</small> : null}
          </div>
        </form>
      ) : null}

      {isAdmin && account?.razorpay_account_id ? (
        <button
          className="secondary-button"
          disabled={busy}
          onClick={() => void run(() => api.refreshPayoutAccount(token, restaurantId), "Status refreshed")}
          type="button"
        >
          <RefreshCw size={15} /> Refresh status
        </button>
      ) : null}
    </section>
  );
}
