import type { ReactNode } from "react";

/**
 * The heading of one checkout step: a numeral, a title, one line of why.
 *
 * The three panels on the checkout — contact, when, payment — had identical
 * headings in identical cards, and read as one long form rather than as three
 * short decisions. A numeral gives them an order the eye can follow down the
 * page, and ties them to the "2 Checkout" step in the rail above: this is the
 * inside of that step, in three parts.
 *
 * The title text is passed through untouched. The end-to-end suite finds
 * these sections by their headings ("Contact & delivery", "Payment", "When
 * would you like it?"), so the words are the contract and this only decides
 * how they sit.
 */
export function StepHeader({
  number,
  title,
  blurb,
  children,
}: {
  number: 1 | 2 | 3;
  title: ReactNode;
  blurb?: ReactNode;
  /** Something that belongs beside the heading — a status chip, a note. */
  children?: ReactNode;
}) {
  return (
    <header className="step-head">
      <span className="step-head__n" aria-hidden="true">
        {String(number).padStart(2, "0")}
      </span>
      <div className="step-head__text">
        <h2 className="step-head__title font-display">{title}</h2>
        {blurb && <p className="step-head__blurb">{blurb}</p>}
        {children}
      </div>
    </header>
  );
}
