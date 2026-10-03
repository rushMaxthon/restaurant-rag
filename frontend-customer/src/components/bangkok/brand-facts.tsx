import { Award } from "lucide-react";

import { StatsCounter } from "@/components/ui/stats-counter";
import { useBangkokStore } from "@/lib/bangkok-store";
import { useStorefrontBrand, useStorefrontCopy, yearsTrading } from "@/lib/storefront";

/**
 * A tile's figure, counting up to itself once it is on screen.
 *
 * The value is a STRING the owner typed, not a number: "4.6", "₹400", "21",
 * "4.6★". So it is split rather than parsed — symbol, number, whatever
 * trails — and only the middle part animates. Anything that does not match
 * that shape is printed exactly as written, because an owner is entitled to
 * put a word in this box and a counter is not entitled to mangle it.
 *
 * The decimal count comes from what they typed, so "4.6" counts in tenths and
 * lands on 4.6 rather than on 5, and "4.60" would keep both places.
 *
 * **The trailing part may not contain digits**, which is what keeps a range
 * out of here. An owner's "15-25" tile matched an earlier version of this as
 * 15 followed by the literal "-25", so on the way up it read "0-25", "7-25",
 * "13-25" — three ranges that were never true. One number can count; two
 * cannot, so a value holding two is printed rather than animated.
 */
function FactValue({ animate, value }: { animate: boolean; value: string }) {
  const parts = /^([^\d]*)(\d+(?:\.\d+)?)([^\d]*)$/.exec(value.trim());
  if (!animate || !parts) return <>{value}</>;

  // Every group is optional to the type checker even though the pattern can
  // only match with all three present, so they are coerced rather than
  // asserted — an empty prefix is the right answer anyway.
  const prefix = parts[1] ?? "";
  const digits = parts[2] ?? "";
  const suffix = parts[3] ?? "";
  const decimals = digits.split(".")[1]?.length ?? 0;

  return (
    <StatsCounter decimals={decimals} prefix={prefix} suffix={suffix} value={Number(digits)} />
  );
}

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
            {/* The year does not count up. Watching "Baking since" climb from
                zero to 1999 is a slot machine, and the one number on this page
                that means something at a glance would be the last to arrive. */}
            <strong className="facts__value">
              <FactValue animate={!tile.lead} value={tile.value} />
            </strong>
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
