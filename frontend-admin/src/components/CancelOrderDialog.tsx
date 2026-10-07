import { Bell, Bike, RotateCcw } from "lucide-react";
import { useState } from "react";

import { Modal } from "./Modal";
import { ApiError, api } from "../services/api";
import { CANCEL_REASONS, cancelFormError, type StaffCancelReason } from "../services/orderCancellation";
import type { Order, ToastMessage } from "../types/app";

interface CancelOrderDialogProps {
  token: string;
  order: Pick<Order, "id" | "payment_method" | "payment_status">;
  amount: string;
  onClose: () => void;
  /** Called with the cancelled order, once the server has accepted it. */
  onCancelled: (order: Order) => void;
  onToast: (title: string, description: string, tone?: ToastMessage["tone"]) => void;
}

/**
 * Cancel one order: a reason from the fixed list, an optional note, and a
 * plain statement of what will happen to the money and the rider before the
 * button is pressed. The server makes every decision; a refusal (the rider
 * collected it in the meantime) comes back as its own sentence.
 *
 * The reasons are rows a whole finger can hit, not bare radio buttons: inside
 * `.field`, the panel's form rules stretched each radio to a full-height
 * circle above its label (`.cancel-reason` in legacy.css says why).
 */
export function CancelOrderDialog({ token, order, amount, onClose, onCancelled, onToast }: CancelOrderDialogProps) {
  const [reason, setReason] = useState<StaffCancelReason | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const prepaid = order.payment_method !== "COD" && order.payment_status === "PAID";
  const formError = cancelFormError(reason, note);
  const noteRequired = reason === "OTHER_BY_STAFF";

  async function submit() {
    if (formError || !reason) {
      setError(formError);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const cancelled = await api.cancelOrder(token, order.id, reason, note.trim());
      onToast(
        "Order cancelled",
        prepaid ? `#${order.id.slice(0, 8)} is cancelled and ${amount} is being refunded.` : `#${order.id.slice(0, 8)} is cancelled.`,
        "success",
      );
      onCancelled(cancelled);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not cancel the order. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal busy={busy} className="confirm-dialog cancel-order" labelledBy="cancel-order-title" onClose={onClose}>
      <div className="panel__header modal-card__header">
        <div>
          <span className="eyebrow">Order #{order.id.slice(0, 8)}</span>
          <h2 id="cancel-order-title">Cancel this order?</h2>
        </div>
        <button aria-label="Close" className="modal-close" disabled={busy} onClick={onClose} type="button">
          ×
        </button>
      </div>

      <div className="modal-card__body confirm-dialog__body cancel-order__body">
        <ul aria-label="What happens" className="cancel-order__effects">
          <li>
            <RotateCcw aria-hidden="true" size={16} />
            {prepaid ? (
              <span>
                <strong>{amount}</strong> is refunded to the customer in full.
              </span>
            ) : (
              <span>Nothing was paid online, so there is nothing to refund.</span>
            )}
          </li>
          <li>
            <Bike aria-hidden="true" size={16} />
            <span>A rider already booked for it is called off.</span>
          </li>
          <li>
            <Bell aria-hidden="true" size={16} />
            <span>The customer is told it was cancelled, and why.</span>
          </li>
        </ul>

        <fieldset className="cancel-reasons" disabled={busy}>
          <legend>Why is it being cancelled?</legend>
          {CANCEL_REASONS.map((option) => (
            <label
              className={`cancel-reason${reason === option.value ? " cancel-reason--chosen" : ""}`}
              key={option.value}
            >
              <input
                checked={reason === option.value}
                name="cancel-reason"
                onChange={() => {
                  setReason(option.value);
                  setError(null);
                }}
                type="radio"
                value={option.value}
              />
              <span>{option.label}</span>
            </label>
          ))}
        </fieldset>

        <label className="field cancel-order__note">
          <span>
            Note{" "}
            <small className={noteRequired ? "cancel-order__required" : undefined}>
              {noteRequired ? "(required)" : "(optional)"}
            </small>
          </span>
          <textarea
            disabled={busy}
            maxLength={500}
            onChange={(event) => {
              setNote(event.target.value);
              setError(null);
            }}
            placeholder={noteRequired ? "Say why, in a few words" : "e.g. Paneer finished for today"}
            rows={2}
            value={note}
          />
          <small className="hint-text">The customer sees this note.</small>
        </label>

        {error ? (
          <p className="cancel-order__error" role="alert">
            {error}
          </p>
        ) : formError ? (
          // Why the button is disabled, beside it (CLAUDE.md: a disabled
          // button says why).
          <p className="hint-text cancel-order__why">{formError}</p>
        ) : null}

        <div className="modal-actions">
          <button className="secondary-button" disabled={busy} onClick={onClose} type="button">
            Keep the order
          </button>
          <button
            className="primary-button primary-button--danger"
            disabled={busy || Boolean(formError)}
            onClick={() => void submit()}
            title={formError ?? "Cancel the order"}
            type="button"
          >
            {busy ? "Cancelling..." : prepaid ? `Cancel and refund ${amount}` : "Cancel order"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
