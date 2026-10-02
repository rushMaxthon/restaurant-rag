import { Link } from "@tanstack/react-router";
import { ChefHat, Clock, MapPin, UtensilsCrossed } from "lucide-react";

import type { RestaurantLocation } from "@/lib/bangkok-data";
import { availabilityNow, dayLabel, formatSlotTime, nextOpening } from "@/lib/branch-hours";

/**
 * Four facts under the hero, every one of them read off this restaurant's own
 * rows.
 *
 * This is the strip a first-time visitor scans before deciding whether to
 * scroll: is it open, how long will it take, how much is there, where is it.
 * On the sites people here already trust those four sit right under the name,
 * and a storefront that opens straight into a dish grid without them reads as
 * a catalogue rather than a kitchen.
 *
 * **Nothing is asserted that the data does not say.** A branch that has not
 * published an ETA gets no ETA tile; a menu that has not loaded gets no count;
 * a restaurant with no address gets no address. The strip simply has fewer
 * cells. The one thing it never does is invent "Open now", "30 min" or "FSSAI
 * certified" — the first two were literals on this page once, and the third
 * is a claim about a licence this platform cannot see.
 */
export function TrustStrip({
  branch,
  fulfillment,
  timeZone,
  dishCount,
  sectionCount,
}: {
  branch: RestaurantLocation | undefined;
  fulfillment: "DELIVERY" | "PICKUP";
  timeZone: string | undefined;
  dishCount: number;
  sectionCount: number;
}) {
  if (!branch) return null;

  const now = new Date();
  const open = availabilityNow(branch, fulfillment, now, timeZone);
  const reopens = open.available ? null : nextOpening(branch, fulfillment, now, timeZone);
  const eta = Number(
    fulfillment === "DELIVERY" ? branch.estimated_delivery_time : branch.estimated_pickup_time,
  );
  const where = [branch.address_line_1, branch.city].filter(Boolean).join(", ");

  return (
    <section className="trust-strip" aria-label="At a glance">
      <ul className="trust-strip__list">
        <li className="trust-cell" data-tone={open.available ? "open" : "closed"}>
          <Clock aria-hidden="true" />
          <span>
            <strong>{open.available ? "Open now" : "Closed right now"}</strong>
            <small>
              {open.available
                ? `Taking ${fulfillment === "DELIVERY" ? "delivery" : "collection"} orders`
                : reopens
                  ? `Opens ${reopens.isToday ? "today" : dayLabel(reopens.day)} at ${formatSlotTime(reopens.slot.start_time)}`
                  : "Scheduling may still be available"}
            </small>
          </span>
        </li>

        {Number.isFinite(eta) && eta > 0 && (
          <li className="trust-cell">
            <ChefHat aria-hidden="true" />
            <span>
              <strong>About {eta} min</strong>
              <small>
                {fulfillment === "DELIVERY" ? "Cooked and delivered" : "Ready to collect"}
              </small>
            </span>
          </li>
        )}

        {dishCount > 0 && (
          <li className="trust-cell">
            <UtensilsCrossed aria-hidden="true" />
            <span>
              <strong>
                {dishCount} {dishCount === 1 ? "dish" : "dishes"}
              </strong>
              <small>
                {sectionCount > 1 ? `Across ${sectionCount} sections` : "Cooked to order"}
              </small>
            </span>
          </li>
        )}

        {where && (
          <li className="trust-cell">
            <MapPin aria-hidden="true" />
            <span>
              <strong>{branch.branch_name}</strong>
              <small>
                <Link to="/contact">{where}</Link>
              </small>
            </span>
          </li>
        )}
      </ul>
    </section>
  );
}
