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
 */
export function CancelOrderDialog({ token, order, amount, onClose, onCancelled, onToast }: CancelOrderDialogProps) {
  const [reason, setReason] = useState<StaffCancelReason | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const prepaid = order.payment_method !== "COD" && order.payment_status === "PAID";
  const formError = cancelFormError(reason, note);

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
    <Modal busy={busy} className="confirm-dialog" labelledBy="cancel-order-title" onClose={onClose}>
      <div className="panel__header modal-card__header">
        <div>
          <span className="eyebrow">Order #{order.id.slice(0, 8)}</span>
          <h2 id="cancel-order-title">Cancel this order?</h2>
          <p className="hint-text">
            {prepaid
              ? `The customer is refunded ${amount} in full, a booked rider is called off and the customer is told.`
              : "A booked rider is called off and the customer is told. Nothing was paid online, so there is nothing to refund."}
          </p>
        </div>
        <button aria-label="Close" className="modal-close" disabled={busy} onClick={onClose} type="button">
          ×
        </button>
      </div>

      <div className="modal-card__body confirm-dialog__body">
        <fieldset className="field">
          <legend>Why is it being cancelled?</legend>
          {CANCEL_REASONS.map((option) => (
            <label key={option.value}>
              <input
                checked={reason === option.value}
                disabled={busy}
                name="cancel-reason"
                onChange={() => setReason(option.value)}
                type="radio"
              />{" "}
              {option.label}
            </label>
          ))}
        </fieldset>
        <label className="field">
          <span>Note {reason === "OTHER_BY_STAFF" ? "(required)" : "(optional)"}</span>
          <textarea
            disabled={busy}
            maxLength={500}
            onChange={(event) => setNote(event.target.value)}
            placeholder="e.g. Paneer finished for today"
            rows={2}
            value={note}
          />
        </label>
        {error ? <p role="alert">{error}</p> : null}
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
            {busy ? "Cancelling..." : "Cancel order"}
          </button>
        </div>
        {formError ? <small>{formError}</small> : null}
      </div>
    </Modal>
  );
}
