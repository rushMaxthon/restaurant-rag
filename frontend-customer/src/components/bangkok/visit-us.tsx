import { Link } from "@tanstack/react-router";
import { ArrowUpRight, Clock, MapPin, Phone } from "lucide-react";

import { BranchHours } from "@/components/bangkok/branch-hours";
import type { RestaurantLocation } from "@/lib/bangkok-data";
import { useStorefrontContact } from "@/lib/storefront";

/**
 * Where the kitchen is and when it is open, as a block on the home page.
 *
 * A brand site has to answer "can I actually get there" without a click, and
 * for a lot of customers that is the question the whole visit is about. The
 * closing band used to list branch names as pills and nothing else; this puts
 * the address, the phone and today's hours beside each other, with a
 * directions link that opens the phone's own maps app.
 *
 * The maps link is a search by the address TEXT, not by coordinates. The
 * branch row has coordinates, but they are not on the public payload, and a
 * search by text lands on the same pin for any address a geocoder can read —
 * which is the same address a rider is given. Nothing is invented: a branch
 * with no address gets no link.
 */
export function VisitUs({ branch }: { branch: RestaurantLocation | undefined }) {
  const contact = useStorefrontContact();
  if (!branch) return null;

  const where = [branch.address_line_1, branch.city].filter(Boolean).join(", ");
  const query = contact.address || where;
  const mapsHref = query
    ? `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`
    : null;
  const tel = contact.phone ? contact.phone.replace(/[^+\d]/g, "") : "";

  return (
    <div className="visit reveal-left">
      <div className="visit__where">
        <p className="eyebrow eyebrow--inherit">Visit us</p>
        <h2 className="font-display visit__title">{branch.branch_name}</h2>
        {where && (
          <p className="visit__line">
            <MapPin aria-hidden="true" />
            <span>{where}</span>
          </p>
        )}
        {contact.phone && (
          <p className="visit__line">
            <Phone aria-hidden="true" />
            <a href={`tel:${tel}`}>{contact.phone}</a>
          </p>
        )}
        <div className="visit__actions">
          {mapsHref && (
            <a className="visit__cta" href={mapsHref} target="_blank" rel="noopener noreferrer">
              Get directions <ArrowUpRight aria-hidden="true" />
            </a>
          )}
          <Link className="visit__cta visit__cta--quiet" to="/contact">
            <Clock aria-hidden="true" /> All hours
          </Link>
        </div>
      </div>
      <div className="visit__hours">
        {/* Collection hours, because they are the hours the door is open —
            delivery can run shorter and is on the contact page in full. */}
        <BranchHours location={branch} fulfillment="PICKUP" />
      </div>
    </div>
  );
}
