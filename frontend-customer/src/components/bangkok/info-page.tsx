import type { ReactNode } from "react";

/**
 * The shell every page of prose on this site shares.
 *
 * Five pages — our story, contact, terms, privacy, cancellations — and the
 * reason they share a component rather than each being its own layout is
 * narrower than consistency: a measure. Prose at the storefront's full content
 * width is unreadable on a desktop monitor, so these pages cap at roughly 68
 * characters and the cap lives here, once, where it cannot be forgotten on the
 * sixth page.
 *
 * `updated` is required, and deliberately so. A terms page with no date on it
 * is the single most common defect in small-business legal pages: a customer
 * cannot tell whether they are reading the version they agreed to, and neither
 * can the business. Making it a required prop means the date cannot be the
 * thing that gets left out.
 */
export function InfoPage({
  eyebrow,
  title,
  intro,
  updated,
  children,
}: {
  eyebrow: string;
  title: string;
  intro?: ReactNode;
  /** When the words on this page last changed, e.g. "1 October 2026". */
  updated: string;
  children: ReactNode;
}) {
  return (
    <div className="page-pad info-page pb-24 pt-6 sm:pt-12">
      <p className="eyebrow">{eyebrow}</p>
      <h1 className="font-display info-page__title">{title}</h1>
      {intro && <div className="info-page__intro">{intro}</div>}
      <p className="info-page__updated">Last updated {updated}</p>
      <div className="info-page__body">{children}</div>
    </div>
  );
}

/**
 * One section, with a heading that can be linked to.
 *
 * The `id` is not decoration: a refund conversation goes "see the third
 * paragraph of the cancellations page", and a link that lands on the paragraph
 * instead of the top of the page is the difference between that being useful
 * and being a chore.
 */
export function InfoSection({
  id,
  heading,
  children,
}: {
  id: string;
  heading: string;
  children: ReactNode;
}) {
  return (
    <section className="info-section" id={id}>
      <h2>
        {/* The heading is the anchor. No separate ¶ affordance, which is noise
            on a phone where there is no hover to reveal it. */}
        <a href={`#${id}`}>{heading}</a>
      </h2>
      {children}
    </section>
  );
}
