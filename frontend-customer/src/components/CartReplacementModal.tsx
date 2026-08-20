interface CartReplacementModalProps {
  visible: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

export function CartReplacementModal({
  visible,
  onCancel,
  onConfirm,
}: CartReplacementModalProps) {
  if (!visible) {
    return null;
  }

  return (
    <div
      aria-modal="true"
      className="app-modal"
      role="dialog"
    >
      <button
        aria-label="Close"
        className="app-modal__backdrop"
        onClick={onCancel}
        type="button"
      />
      <div className="app-modal__card">
        <span className="app-modal__badge">Cart</span>
        <h2>Replace cart items?</h2>
        <p>
          Your cart already has items from another restaurant. Do you want to
          clear the current cart and add this item instead?
        </p>
        <div className="app-modal__actions">
          <button className="secondary-button" onClick={onCancel} type="button">
            Cancel
          </button>
          <button className="primary-button" onClick={onConfirm} type="button">
            Clear &amp; Add
          </button>
        </div>
      </div>
    </div>
  );
}
