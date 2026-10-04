import { CircleHelp } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";

interface InfoTipProps {
  /** What the tip is about, for a screen reader: "About New orders". */
  label: string;
  children: ReactNode;
}

interface Placement {
  left: number;
  top?: number;
  bottom?: number;
}

const WIDTH = 288;
const MARGIN = 8;

/**
 * A small "?" that explains the thing beside it.
 *
 * Opens on hover and on keyboard focus, and on a tap — a phone has neither of
 * the first two, and a native `title` attribute never shows there at all.
 *
 * The bubble is rendered into `document.body` and positioned in viewport
 * coordinates. Inside the element it describes, it was clipped: a stat tile
 * and an order card both hide their overflow, the restaurant strip scrolls
 * sideways, and a card lifts on hover with a transform, which turns
 * `position: fixed` into "fixed to the card". Out here none of that reaches it.
 */
export function InfoTip({ label, children }: InfoTipProps) {
  const id = useId();
  const buttonRef = useRef<HTMLButtonElement>(null);
  const [placement, setPlacement] = useState<Placement | null>(null);
  // When it last opened. A tap on a phone is a focus and then a click, a few
  // milliseconds apart: without this the focus opened the bubble and the click
  // that followed read it as "already open" and closed it again.
  const openedAt = useRef(0);

  const open = useCallback(() => {
    const rect = buttonRef.current?.getBoundingClientRect();
    if (!rect) return;
    openedAt.current = Date.now();
    const width = Math.min(WIDTH, window.innerWidth - MARGIN * 2);
    const left = Math.min(
      Math.max(rect.left + rect.width / 2 - width / 2, MARGIN),
      window.innerWidth - width - MARGIN,
    );
    // Below when there is room, above when the button is low on the screen.
    setPlacement(
      rect.bottom > window.innerHeight * 0.6
        ? { left, bottom: window.innerHeight - rect.top + MARGIN }
        : { left, top: rect.bottom + MARGIN },
    );
  }, []);

  const close = useCallback(() => setPlacement(null), []);

  useEffect(() => {
    if (!placement) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    // The bubble is pinned to where the button WAS. Once the page moves it is
    // pointing at nothing, so it goes rather than follows.
    window.addEventListener("keydown", onKey);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [placement, close]);

  return (
    <>
      <button
        aria-describedby={placement ? id : undefined}
        aria-expanded={placement !== null}
        aria-label={`About ${label}`}
        className="tip"
        onBlur={close}
        onClick={(event) => {
          // Often sits inside something clickable. Asking what a column is
          // must not also open it.
          event.stopPropagation();
          if (placement && Date.now() - openedAt.current > 400) close();
          else if (!placement) open();
        }}
        onFocus={open}
        onMouseEnter={open}
        onMouseLeave={close}
        ref={buttonRef}
        type="button"
      >
        <CircleHelp aria-hidden="true" size={15} />
      </button>
      {placement
        ? createPortal(
            <div
              className="tip__bubble"
              id={id}
              role="tooltip"
              style={{
                left: placement.left,
                top: placement.top,
                bottom: placement.bottom,
                width: Math.min(WIDTH, window.innerWidth - MARGIN * 2),
              }}
            >
              {children}
            </div>,
            document.body,
          )
        : null}
    </>
  );
}

interface HelpRowsProps {
  title: string;
  what: string;
  who: string;
  action: string;
}

/** The three questions a new person asks, answered in the same order every time. */
export function HelpRows({ title, what, who, action }: HelpRowsProps) {
  return (
    <>
      <strong className="tip__title">{title}</strong>
      <dl className="tip__rows">
        <div>
          <dt>What it is</dt>
          <dd>{what}</dd>
        </div>
        <div>
          <dt>Who handles it</dt>
          <dd>{who}</dd>
        </div>
        <div>
          <dt>What you do</dt>
          <dd>{action}</dd>
        </div>
      </dl>
    </>
  );
}
