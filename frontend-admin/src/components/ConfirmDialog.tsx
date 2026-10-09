interface ConfirmDialogProps {
  open: boolean;
  eyebrow?: string;
  title: string;
  description: string;
  confirmLabel: string;
  cancelLabel?: string;
  tone?: "default" | "danger";
  busy?: boolean;
  /**
   * Something the decision needs, such as a reason. Rendered above the
   * buttons; most confirmations have nothing to ask and pass none.
   */
  children?: ReactNode;
  /** Holds the confirm button until `children` has what it needs. */
  confirmDisabled?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

import type { ReactNode } from "react";

import { Modal } from "./Modal";

export function ConfirmDialog({
  open,
  eyebrow = "Confirm action",
  title,
  description,
  confirmLabel,
  cancelLabel = "Cancel",
  tone = "default",
  busy = false,
  children,
  confirmDisabled = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  if (!open) {
    return null;
  }

  return (
    <Modal busy={busy} className="confirm-dialog" onClose={onCancel}>
        <div className="panel__header modal-card__header">
          <div>
            <span className="eyebrow">{eyebrow}</span>
            <h2>{title}</h2>
            <p className="hint-text">{description}</p>
          </div>
          <button
            aria-label="Close confirmation dialog"
            className="modal-close"
            onClick={onCancel}
            type="button"
          >
            ×
          </button>
        </div>

        <div className="modal-card__body confirm-dialog__body">
          {children}
          <div className="modal-actions">
            <button
              className="secondary-button"
              disabled={busy}
              onClick={onCancel}
              type="button"
            >
              {cancelLabel}
            </button>
            <button
              className={
                tone === "danger"
                  ? "primary-button primary-button--danger"
                  : "primary-button"
              }
              disabled={busy || confirmDisabled}
              onClick={onConfirm}
              type="button"
            >
              {busy ? "Working..." : confirmLabel}
            </button>
          </div>
        </div>
    </Modal>
  );
}
