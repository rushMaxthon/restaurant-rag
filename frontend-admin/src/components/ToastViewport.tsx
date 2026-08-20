import type { ToastMessage } from '../types/app';

interface ToastViewportProps {
  toasts: ToastMessage[];
  onDismiss: (id: number) => void;
}

export function ToastViewport({ toasts, onDismiss }: ToastViewportProps) {
  return (
    <div className="toast-viewport" aria-live="polite">
      {toasts.map((toast) => (
        <button
          key={toast.id}
          className={`toast toast--${toast.tone ?? 'info'}`}
          onClick={() => onDismiss(toast.id)}
          type="button"
        >
          <strong>{toast.title}</strong>
          <span>{toast.description}</span>
        </button>
      ))}
    </div>
  );
}
