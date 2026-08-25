interface ConfirmDialogProps {
  open: boolean;
  eyebrow?: string;
  title: string;
  description: string;
  confirmLabel: string;
  cancelLabel?: string;
  tone?: "default" | "danger";
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

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
              disabled={busy}
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
