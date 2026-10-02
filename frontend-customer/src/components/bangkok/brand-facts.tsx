import { Award } from "lucide-react";

import { useBangkokStore } from "@/lib/bangkok-store";
import { useStorefrontBrand, useStorefrontCopy, yearsTrading } from "@/lib/storefront";

/**
 * The figures a restaurant leads with, in a band of their own.
 *
 * A brand page that is three paragraphs and a photograph has nothing a
 * customer can take in at a glance, and the things most likely to win a first
 * order are rarely prose: a founding year, a rating, the size of the kitchen.
 * This bakery has been trading since 1999 and that was nowhere on its own
 * website while every listing site in Surat led with it.
 *
 * **Every tile is typed by the owner in `/website`.** Nothing is computed from
 * the platform's own data and nothing is inferred, with one exception: the
 * years-trading line beneath the year, which is subtraction rather than a
 * claim, and is done at render time precisely so it cannot go stale the way a
 * stored "26 years in business" does.
 *
 * `note` is attribution and it is the reason a rating may be shown at all. A
 * 4.6 earned on a listing site is a real fact and not this platform's
 * measurement; printed bare it reads as ours, which is a claim nobody here is
 * entitled to make. The tile puts the source under the number, always.
 */
export function BrandHighlights() {
  const { established_year: established, highlights } = useStorefrontBrand();
  const store = useBangkokStore();
  const years = yearsTrading(established);
  // The branch's own city, never a literal. This read "years in Surat",
  // which was true of the one restaurant it was written against and would
  // have been a false claim about the next one — the exact class of thing
  // that has to come from a row rather than from the code.
  const city = (store.orderLocation ?? store.currentLocation)?.city;

  // The year earns a tile of its own, ahead of whatever the owner wrote,
  // because "since 1999" is the one fact on this page that a competitor
  // cannot copy by Tuesday.
  const tiles = [
    ...(established
      ? [
          {
            value: String(established),
            label: "Baking since",
            note: years ? `${years} years${city ? ` in ${city}` : ""}` : undefined,
            lead: true,
          },
        ]
      : []),
    ...highlights.map((highlight) => ({ ...highlight, lead: false })),
  ];

  if (tiles.length === 0) return null;

  return (
    <section className="facts" aria-label="At a glance">
      <ul className="facts__grid reveal-group--sides" data-count={Math.min(tiles.length, 5)}>
        {tiles.map((tile) => (
          <li className="facts__tile" data-lead={tile.lead || undefined} key={tile.label}>
            <strong className="facts__value">{tile.value}</strong>
            <span className="facts__label">{tile.label}</span>
            {tile.note && <small className="facts__note">{tile.note}</small>}
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * What this kitchen is known for, in its own words.
 *
 * Deliberately NOT the menu's categories. Those are how 187 rows are filed;
 * these are the four or five things somebody in Katargam would name if you
 * asked them about this bakery — which is a different list, written by the
 * owner, and the one worth putting on a front page. Deriving it from the
 * biggest menu sections was the obvious shortcut and would have produced
 * "Namkeen & Sev, Breads & Pav, Cookies & Biscuits": true, generic, and
 * already two blocks further down the page.
 */
export function BrandSpecialities() {
  const { specialities } = useStorefrontBrand();
  const copy = useStorefrontCopy();

  if (specialities.length === 0) return null;

  return (
    <section className="known">
      <div className="page-pad section-pad known__inner">
        <p className="eyebrow reveal">What we are known for</p>
        <h2 className="font-display known__title reveal-wipe">
          <span>The things people come to {copy.name} for</span>
        </h2>
        <ul className="known__grid reveal-group">
          {specialities.map((speciality) => (
            <li className="known__item" key={speciality}>
              <Award aria-hidden="true" />
              <span>{speciality}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
