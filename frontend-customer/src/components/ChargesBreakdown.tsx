/**
 * One line on the bill that opens to show what it is made of.
 *
 * Four extra rows on a checkout read as nickel-and-diming; a single figure
 * nobody can take apart reads as something to be suspicious of. So the summary
 * carries one "Taxes and charges" row with a dotted underline, and opening it
 * shows the packaging, the platform fee and each tax separately, each with a
 * sentence saying what it is.
 *
 * Those sentences matter more than they look. A platform fee with no
 * explanation is assumed to be a tax or assumed to be the restaurant keeping
 * it, and a tax row that does not say the rate is the government's sends the
 * complaint to the wrong party.
 *
 * **Every figure comes from the server.** Nothing is computed here and nothing
 * is rounded here, because a client that does its own arithmetic will
 * eventually disagree with the amount actually charged, and the customer will
 * be right to believe the one on screen.
 *
 * On a wide screen it is a popover anchored under the row; on a phone it is a
 * sheet that rises from the bottom, because a popover on a narrow screen ends
 * up half off the edge. Same content, same data, one component.
 */

import { useEffect, useRef, useState } from "react";

import type { OrderCharges } from "@/lib/api";

export function ChargesBreakdown({
  charges,
  money,
  label = "Taxes and charges",
}: {
  charges: OrderCharges | null | undefined;
  /** The caller's currency formatter, so this never guesses a symbol. */
  money: (amount: number) => string;
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  const holder = useRef<HTMLDivElement>(null);

  // Close on a click anywhere else and on Escape. Without the first, the panel
  // follows you around the page; without the second it is a trap for anyone
  // not using a mouse.
  useEffect(() => {
    if (!open) return;
    const awayClick = (event: MouseEvent) => {
      if (!holder.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", awayClick);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", awayClick);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  const lines = charges?.lines ?? [];
  // With nothing to reveal this is an ordinary row. A button that opens an
  // empty panel is worse than no button.
  const expandable = lines.length > 0;

  return (
    <div className="relative" ref={holder}>
      <div className="flex justify-between gap-3">
        <dt className="text-muted">
          {expandable ? (
            <button
              aria-expanded={open}
              className="cursor-pointer border-b border-dashed border-current pb-px text-left"
              onClick={() => setOpen((was) => !was)}
              type="button"
            >
              {label}
            </button>
          ) : (
            label
          )}
        </dt>
        <dd className="money font-semibold">{money(Number(charges?.total ?? 0))}</dd>
      </div>

      {open && expandable && (
        <>
          {/* Phone only: dims the page behind the sheet so the sheet reads as a
              layer rather than as part of the bill. */}
          <div
            aria-hidden="true"
            className="fixed inset-0 z-40 bg-[var(--overlay)] sm:hidden"
            onClick={() => setOpen(false)}
          />
          <div
            className={
              // A sheet from the bottom on a phone, a popover under the row on
              // anything wider. A popover at 360px ends up half off the edge.
              "elevated-panel z-50 p-4 " +
              "fixed inset-x-0 bottom-0 max-h-[70vh] overflow-auto rounded-b-none " +
              "sm:absolute sm:inset-x-auto sm:bottom-auto sm:right-0 sm:top-full sm:mt-2 " +
              "sm:w-80 sm:rounded-[var(--radius)]"
            }
            role="dialog"
            aria-label={label}
          >
            <div className="mb-3 flex items-center justify-between gap-3">
              <h3 className="font-display text-base font-extrabold">{label}</h3>
              <button
                aria-label="Close"
                className="text-muted"
                onClick={() => setOpen(false)}
                type="button"
              >
                ✕
              </button>
            </div>

            <dl className="space-y-3">
              {lines.map((line) => (
                <div key={line.key}>
                  <div className="flex justify-between gap-3 text-sm">
                    <dt className="font-semibold">{line.label}</dt>
                    <dd className="money font-semibold">{money(Number(line.amount))}</dd>
                  </div>
                  {line.note && <p className="mt-0.5 text-xs text-muted">{line.note}</p>}
                </div>
              ))}
            </dl>

            <div className="mt-3 flex justify-between gap-3 border-t border-border pt-3 text-sm">
              <span className="font-extrabold">{label}</span>
              <span className="money font-extrabold">{money(Number(charges?.total ?? 0))}</span>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
