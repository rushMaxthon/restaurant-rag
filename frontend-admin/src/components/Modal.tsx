import { useCallback, useEffect, useRef, type ReactNode } from 'react';

/**
 * The shell every dialog in the admin renders inside.
 *
 * The ten editor dialogs were each hand-rolled and got only `role="dialog"`:
 * Escape did nothing, focus escaped into the page behind, screen readers were
 * never told a dialog had opened, and scrolling moved the background instead of
 * the dialog. All of that is handled here once.
 */
interface ModalProps {
  onClose: () => void;
  /** Id of the heading that names this dialog. */
  labelledBy?: string;
  /** Extra classes for the card, e.g. `modal-card--compact`. */
  className?: string;
  /**
   * Blocks Escape and overlay-click while a request is in flight, so a dialog
   * cannot be dismissed out from under a save that is still running.
   */
  busy?: boolean;
  children: ReactNode;
}

/**
 * Counts open dialogs rather than toggling a boolean: with two dialogs stacked,
 * closing the inner one must not release the outer one's scroll lock.
 */
let openModalCount = 0;

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function Modal({ onClose, labelledBy, className, busy = false, children }: ModalProps) {
  const cardRef = useRef<HTMLElement>(null);

  const requestClose = useCallback(() => {
    if (!busy) {
      onClose();
    }
  }, [busy, onClose]);

  // Scroll lock. Compensating for the scrollbar's width stops the page behind
  // shifting sideways as it disappears.
  useEffect(() => {
    openModalCount += 1;
    const { body } = document;
    if (openModalCount === 1) {
      const gap = window.innerWidth - document.documentElement.clientWidth;
      body.dataset.previousOverflow = body.style.overflow;
      body.dataset.previousPaddingRight = body.style.paddingRight;
      body.style.overflow = 'hidden';
      if (gap > 0) {
        body.style.paddingRight = `${gap}px`;
      }
    }
    return () => {
      openModalCount -= 1;
      if (openModalCount === 0) {
        body.style.overflow = body.dataset.previousOverflow ?? '';
        body.style.paddingRight = body.dataset.previousPaddingRight ?? '';
        delete body.dataset.previousOverflow;
        delete body.dataset.previousPaddingRight;
      }
    };
  }, []);

  // Move focus in on open, and put it back where it came from on close -
  // otherwise closing a dialog drops the caret at the top of the document.
  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const card = cardRef.current;
    const first = card?.querySelector<HTMLElement>(FOCUSABLE);
    (first ?? card)?.focus();
    return () => previouslyFocused?.focus?.();
  }, []);

  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        requestClose();
        return;
      }
      if (event.key !== 'Tab') {
        return;
      }
      // Trap: wrap from the last focusable to the first and back, so Tab can
      // never walk out of the dialog into the page underneath it.
      const card = cardRef.current;
      if (!card) {
        return;
      }
      const focusable = [...card.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(
        (element) => element.offsetParent !== null,
      );
      if (focusable.length === 0) {
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [requestClose]);

  return (
    <div className="modal-overlay" onClick={requestClose} role="presentation">
      <section
        aria-labelledby={labelledBy}
        aria-modal="true"
        className={className ? `modal-card ${className}` : 'modal-card'}
        onClick={(event) => event.stopPropagation()}
        ref={cardRef}
        role="dialog"
        tabIndex={-1}
      >
        {children}
      </section>
    </div>
  );
}
