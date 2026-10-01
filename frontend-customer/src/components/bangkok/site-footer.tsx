import { Link } from "@tanstack/react-router";
import { MapPin, Phone, Sparkles } from "lucide-react";

import { brandInitials } from "@/lib/brand-mark";
import { hasCapability, useBangkokStore } from "@/lib/bangkok-store";
import { useStorefrontContact, useStorefrontCopy } from "@/lib/storefront";

/**
 * The end of every page, and the part of a brand site that says somebody real
 * stands behind it.
 *
 * The storefront had no footer at all. On a marketplace that is defensible —
 * the brand is the marketplace, and the restaurant is a listing inside it. On
 * a single-restaurant site it is not: a page that ends at the last dish with
 * no address, no phone number and no terms reads as a form rather than as a
 * business, and it is the first thing a customer deciding whether to hand over
 * a card number looks for.
 *
 * **Every fact here is the restaurant's own, and absent when it is absent.**
 * The address and phone number come from `restaurants`' own columns through
 * `services/restaurant_contact.py`, which omits any part still carrying its
 * onboarding placeholder. So a tenant created five minutes ago gets a footer
 * with no address block rather than one advertising "Pending restaurant setup,
 * Pending 000000". Nothing here falls back to a platform default, because a
 * platform default address would be a false claim about a real business.
 *
 * The structured data at the bottom is the same information in the form a
 * search engine reads, emitted from the same values for the same reason — two
 * copies of an address that can disagree is how a business ends up listed at
 * an address it moved away from.
 */
export function SiteFooter() {
  const copy = useStorefrontCopy();
  const contact = useStorefrontContact();
  const store = useBangkokStore();
  const askAi = hasCapability(store.capabilities, "ask_ai");
  const initials = brandInitials(copy.name);

  // The branch the customer is actually looking at, which may be one of
  // several. Its address is more specific than the brand's registered one, so
  // it wins where there is one — somebody wanting to collect an order needs
  // the branch, not the head office.
  const branch = store.currentLocation;
  const branchAddress = branch
    ? [branch.address_line_1, branch.city].filter(Boolean).join(", ")
    : "";
  const address = branchAddress || contact.address || "";

  return (
    <footer className="site-footer">
      <div className="site-footer__inner">
        <div className="site-footer__brand">
          <Link to="/" className="site-footer__id" aria-label={`${copy.name} home`}>
            {initials && <span className="brand-mark">{initials}</span>}
            <span className="font-display site-footer__name">{copy.name}</span>
          </Link>
          {/* The restaurant's own sentence about itself — the same one in its
              search listing, so the two cannot describe different businesses. */}
          <p className="site-footer__blurb">{copy.meta_description}</p>

          {(address || contact.phone) && (
            <ul className="site-footer__contact">
              {address && (
                <li>
                  <MapPin aria-hidden="true" />
                  <span>
                    {branchAddress && branch ? (
                      <>
                        <span className="site-footer__branch">{branch.branch_name}</span>
                        {address}
                      </>
                    ) : (
                      address
                    )}
                  </span>
                </li>
              )}
              {contact.phone && (
                <li>
                  <Phone aria-hidden="true" />
                  {/* A real link, not text. On a phone this is the single most
                      used thing in a restaurant's footer. */}
                  <a href={`tel:${contact.phone.replace(/[^+\d]/g, "")}`}>{contact.phone}</a>
                </li>
              )}
            </ul>
          )}
        </div>

        <nav className="site-footer__nav" aria-label="Footer">
          <div className="site-footer__col">
            <h2>Order</h2>
            <ul>
              <li>
                <Link to="/menu">Menu</Link>
              </li>
              <li>
                <Link to="/cart">Your cart</Link>
              </li>
              <li>
                <Link to="/orders">Your orders</Link>
              </li>
              {askAi && (
                <li>
                  <Link to="/concierge">
                    <Sparkles aria-hidden="true" className="site-footer__spark" />
                    Ask AI
                  </Link>
                </li>
              )}
            </ul>
          </div>

          <div className="site-footer__col">
            <h2>This kitchen</h2>
            <ul>
              <li>
                <Link to="/about">Our story</Link>
              </li>
              <li>
                <Link to="/contact">Contact &amp; hours</Link>
              </li>
            </ul>
          </div>

          <div className="site-footer__col">
            <h2>The small print</h2>
            <ul>
              <li>
                <Link to="/terms">Terms of service</Link>
              </li>
              <li>
                <Link to="/privacy">Privacy</Link>
              </li>
              <li>
                <Link to="/refunds">Cancellations &amp; refunds</Link>
              </li>
            </ul>
          </div>
        </nav>
      </div>

      <div className="site-footer__base">
        <p>
          © {new Date().getFullYear()} {copy.name}
        </p>
        {/* Said plainly because it is the honest description of what this site
            is, and because a customer who knows the kitchen cooks to order is
            a customer who is not surprised by the wait. */}
        <p className="site-footer__made">Every order cooked to order.</p>
      </div>

      <StructuredData name={copy.name} description={copy.meta_description} />
    </footer>
  );
}

/**
 * The same facts, in the form a search engine reads.
 *
 * Built from the loader data this component already has rather than from a
 * second source, so the address a crawler indexes and the address on the page
 * cannot drift apart. Fields the restaurant has not filled in are left OUT of
 * the object instead of sent empty — an empty `telephone` in structured data
 * is worse than none, because it is a machine-readable claim that there is no
 * phone number.
 *
 * Rendered in the footer rather than the document head purely because that is
 * where this data lives; JSON-LD is read wherever it appears in the document.
 */
function StructuredData({ name, description }: { name: string; description: string }) {
  const contact = useStorefrontContact();

  const postal: Record<string, string> = { "@type": "PostalAddress" };
  if (contact.address_line_1) {
    postal["streetAddress"] = [contact.address_line_1, contact.address_line_2]
      .filter(Boolean)
      .join(", ");
  }
  if (contact.city) postal["addressLocality"] = contact.city;
  if (contact.state) postal["addressRegion"] = contact.state;
  if (contact.postal_code) postal["postalCode"] = contact.postal_code;
  if (contact.country) postal["addressCountry"] = contact.country;

  const data: Record<string, unknown> = {
    "@context": "https://schema.org",
    "@type": "Restaurant",
    name,
    description,
  };
  if (contact.phone) data["telephone"] = contact.phone;
  // Only when there is something in it beyond the type marker.
  if (Object.keys(postal).length > 1) data["address"] = postal;

  return (
    <script
      type="application/ld+json"
      // Known-shaped object built field by field above, never a passthrough of
      // anything a visitor typed.
      dangerouslySetInnerHTML={{ __html: JSON.stringify(data) }}
    />
  );
}
