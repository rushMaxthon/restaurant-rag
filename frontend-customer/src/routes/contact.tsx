import { createFileRoute, Link } from "@tanstack/react-router";
import { MapPin, Phone, ReceiptText } from "lucide-react";

import { BranchHours } from "@/components/bangkok/branch-hours";
import { InfoPage, InfoSection } from "@/components/bangkok/info-page";
import { useBangkokStore } from "@/lib/bangkok-store";
import { pageMeta, useStorefrontContact, useStorefrontCopy } from "@/lib/storefront";
import { getStorefrontCopy } from "@/lib/storefront.server";

export const Route = createFileRoute("/contact")({
  loader: () => getStorefrontCopy(),
  head: ({ loaderData }) => ({
    meta: pageMeta(
      loaderData,
      "Contact & hours",
      "Where to find us, when we are open, and how to reach us about an order.",
    ),
  }),
  component: ContactPage,
});

/**
 * Where we are, when we are open, and what to do about an order.
 *
 * There is no contact FORM here, on purpose. A form implies somebody is
 * watching an inbox, and this platform has no inbox — nothing receives, routes
 * or answers a message typed into a storefront. A form that silently goes
 * nowhere is worse than no form: the customer believes they have told us
 * something, and waits.
 *
 * So this page answers with the channels that genuinely reach a person: the
 * phone number on the restaurant's own record, the branch itself, and — for
 * anything about a specific order — the order page, which is the only place
 * that knows the order number the kitchen needs.
 *
 * Every detail is omitted rather than defaulted when the restaurant has not
 * filled it in, which is why each block below is conditional. A contact page
 * confidently printing a placeholder is the one outcome worse than a thin one.
 */
function ContactPage() {
  const copy = useStorefrontCopy();
  const contact = useStorefrontContact();
  const store = useBangkokStore();
  const branch = store.currentLocation;
  const branches = store.locations.filter((location) => location.is_active);
  const tel = contact.phone ? contact.phone.replace(/[^+\d]/g, "") : "";

  const nothingKnown = !contact.address && !contact.phone && branches.length === 0;

  return (
    <InfoPage
      eyebrow="Contact"
      title={`Reaching ${copy.name}`}
      intro={
        <p>
          The quickest route depends on what you need. An order already placed is best taken up
          with the branch cooking it; anything else can wait for opening hours.
        </p>
      }
      updated="1 October 2026"
    >
      {nothingKnown && (
        <InfoSection id="unavailable" heading="We're still setting this up">
          <p>
            This kitchen has not published its address or phone number yet. You can still browse
            the <Link to="/menu">menu</Link> and place an order — your order page will show the
            branch cooking it.
          </p>
        </InfoSection>
      )}

      {(contact.address || contact.phone) && (
        <InfoSection id="details" heading="The details">
          <ul className="info-contact">
            {contact.address && (
              <li>
                <MapPin aria-hidden="true" />
                <div>
                  <p className="info-contact__label">Address</p>
                  <p>{contact.address}</p>
                  {contact.country && <p className="info-contact__sub">{contact.country}</p>}
                </div>
              </li>
            )}
            {contact.phone && (
              <li>
                <Phone aria-hidden="true" />
                <div>
                  <p className="info-contact__label">Phone</p>
                  <p>
                    <a href={`tel:${tel}`}>{contact.phone}</a>
                  </p>
                  <p className="info-contact__sub">
                    Best for an order that is already in the kitchen.
                  </p>
                </div>
              </li>
            )}
          </ul>
        </InfoSection>
      )}

      <InfoSection id="about-an-order" heading="About an order you have placed">
        <p>
          Open it from your <Link to="/orders">orders page</Link> first. It carries the order
          number, what was in it, and where it has got to — and that number is the first thing the
          kitchen will ask for.
        </p>
        <p className="info-note">
          <ReceiptText aria-hidden="true" />
          An order cannot be cancelled once it has been placed, because the kitchen may already
          have started it. <Link to="/refunds">What happens instead is here.</Link>
        </p>
      </InfoSection>

      {branch && (
        <InfoSection id="hours" heading={`Opening hours — ${branch.branch_name}`}>
          <p>
            These are this branch's own windows.{" "}
            {branches.length > 1 && "Switch branch at the top of any page to see another's."}
          </p>
          <div className="info-hours">
            {/* Both, because they differ: a kitchen opens for collection before
                it starts sending riders out, and a customer told only one set
                is told the wrong thing half the time. Each renders nothing at
                all when the branch keeps no windows for it. */}
            <BranchHours location={branch} fulfillment="PICKUP" />
            <BranchHours location={branch} fulfillment="DELIVERY" />
          </div>
          {branch.temporary_closed_reason && (
            <p className="info-note">{branch.temporary_closed_reason}</p>
          )}
        </InfoSection>
      )}

      {branches.length > 1 && (
        <InfoSection id="branches" heading="Every branch">
          <ul className="info-branches">
            {branches.map((location) => (
              <li key={location.id}>
                <MapPin aria-hidden="true" />
                <div>
                  <p className="info-branches__name">{location.branch_name}</p>
                  <p className="info-branches__where">
                    {[location.address_line_1, location.city].filter(Boolean).join(", ")}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </InfoSection>
      )}
    </InfoPage>
  );
}
