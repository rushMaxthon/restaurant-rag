import { Info } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";

interface InfoTipProps {
  /** What the tip is about, for a screen reader: "About New orders". */
  label: string;
  /** For a longer explanation: a glossary reads badly in a narrow column. */
  wide?: boolean;
  children: ReactNode;
}

interface Placement {
  left: number;
  width: number;
  maxHeight: number;
  top?: number;
  bottom?: number;
}

const WIDTH = 288;
const WIDTH_WIDE = 420;
const MARGIN = 8;
/** How far the bubble's edge sits left of the button it opens from. */
const INSET = 12;

/**
 * A small "i" that explains the thing beside it.
 *
 * Opens on a click and nothing else. It used to open on hover and focus as
 * well, and a pointer crossing the page on its way somewhere else kept
 * throwing explanations up; a click also works the same on a phone, where a
 * native `title` attribute never shows at all. Enter and Space click a button,
 * so the keyboard needs nothing of its own.
 *
 * The bubble is rendered into `document.body` and positioned in viewport
 * coordinates. Inside the element it describes, it was clipped: a stat tile
 * and an order card both hide their overflow, the restaurant strip scrolls
 * sideways, and a card lifts on hover with a transform, which turns
 * `position: fixed` into "fixed to the card". Out here none of that reaches it.
 */
export function InfoTip({ label, wide = false, children }: InfoTipProps) {
  const id = useId();
  const buttonRef = useRef<HTMLButtonElement>(null);
  const bubbleRef = useRef<HTMLDivElement>(null);
  const [placement, setPlacement] = useState<Placement | null>(null);
  const open = useCallback(() => {
    const rect = buttonRef.current?.getBoundingClientRect();
    if (!rect) return;
    const width = Math.min(wide ? WIDTH_WIDE : WIDTH, window.innerWidth - MARGIN * 2);
    // Starts under the button and runs right, pulled back in at the screen's
    // edge. Centred on the button it hung over the sidebar from every page
    // title, which sits a few pixels from it.
    const left = Math.min(Math.max(rect.left - INSET, MARGIN), window.innerWidth - width - MARGIN);
    // Whichever side has more room, and never taller than that room: a long
    // explanation scrolls inside the bubble rather than running off the screen.
    const above = rect.top - MARGIN * 2;
    const below = window.innerHeight - rect.bottom - MARGIN * 2;
    setPlacement(
      above > below
        ? { left, width, maxHeight: above, bottom: window.innerHeight - rect.top + MARGIN }
        : { left, width, maxHeight: below, top: rect.bottom + MARGIN },
    );
  }, [wide]);

  const close = useCallback(() => setPlacement(null), []);

  useEffect(() => {
    if (!placement) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    // A click anywhere else closes it. Blur alone is not enough: Safari does
    // not focus a button on click, so there it would never blur either.
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      // Not the bubble itself: a long one scrolls, and that takes a press.
      if (!buttonRef.current?.contains(target) && !bubbleRef.current?.contains(target)) close();
    };
    // The bubble is pinned to where the button WAS. Once the page moves it is
    // pointing at nothing, so it goes rather than follows.
    window.addEventListener("keydown", onKey);
    window.addEventListener("pointerdown", onPointerDown);
    const onScroll = (event: Event) => {
      if (event.target !== bubbleRef.current) close();
    };
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", close);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("pointerdown", onPointerDown);
      window.removeEventListener("scroll", onScroll, true);
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
        onClick={(event) => {
          // Often sits inside something clickable. Asking what a column is
          // must not also open it.
          event.stopPropagation();
          if (placement) close();
          else open();
        }}
        ref={buttonRef}
        type="button"
      >
        <Info aria-hidden="true" size={15} />
      </button>
      {placement
        ? createPortal(
            <div
              className="tip__bubble"
              id={id}
              ref={bubbleRef}
              role="tooltip"
              style={{
                left: placement.left,
                top: placement.top,
                bottom: placement.bottom,
                width: placement.width,
                maxHeight: placement.maxHeight,
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
