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

import { useEffect } from "react";

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
  useEffect(() => {
    if (!open) {
      return;
    }
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) {
        onCancel();
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [busy, onCancel, open]);

  if (!open) {
    return null;
  }

  return (
    <div className="modal-overlay" onClick={onCancel} role="presentation">
      <section
        aria-modal="true"
        className="modal-card confirm-dialog"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
      >
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
      </section>
    </div>
  );
}
