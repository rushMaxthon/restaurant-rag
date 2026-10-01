import { createFileRoute, Link } from "@tanstack/react-router";
import { ChefHat, Clock, MapPin, Soup } from "lucide-react";

import { InfoPage, InfoSection } from "@/components/bangkok/info-page";
import { useBangkokStore } from "@/lib/bangkok-store";
import { pageMeta, useStorefrontContact, useStorefrontCopy } from "@/lib/storefront";
import { getStorefrontCopy } from "@/lib/storefront.server";

export const Route = createFileRoute("/about")({
  loader: () => getStorefrontCopy(),
  head: ({ loaderData }) =>
    ({
      meta: pageMeta(
        loaderData,
        "Our story",
        loaderData?.meta_description ?? "About this kitchen.",
      ),
    }),
  component: AboutPage,
});

/**
 * Who this kitchen is, in its own words.
 *
 * Deliberately short, and deliberately built from fields that already exist.
 * The temptation on an about page is to write a paragraph of restaurant prose,
 * and on a multi-tenant platform that paragraph would be written by us and
 * then shown over six different restaurants' names — exactly the bug
 * `services/restaurant_storefront.py` exists to have fixed. So every sentence
 * of substance here is the restaurant's own `storefront` copy, and what this
 * page adds is structure: the words the owner wrote, the branches they
 * actually operate, and a way to reach them.
 *
 * The three cards at the bottom are facts about the ORDERING, not about the
 * food — true of every tenant because they are properties of this platform,
 * and so safe to state over any restaurant's name.
 */
function AboutPage() {
  const copy = useStorefrontCopy();
  const contact = useStorefrontContact();
  const store = useBangkokStore();
  const branches = store.locations.filter((location) => location.is_active);

  return (
    <InfoPage
      eyebrow="Our story"
      title={copy.hero_headline}
      intro={<p>{copy.hero_subcopy}</p>}
      // The owner's copy is what dates this page, and nothing here is a claim
      // that needs a version history — so this is the date the page itself was
      // written rather than a stored timestamp we do not keep.
      updated="1 October 2026"
    >
      <InfoSection id="kitchen" heading="What we do">
        <p>{copy.meta_description}</p>
        <p>
          Everything on the <Link to="/menu">menu</Link> is cooked after you order it, which is
          why we quote a preparation time rather than promising a number we cannot keep. If
          something is off the menu today, it is because the kitchen has run out — not because it
          was quietly removed.
        </p>
      </InfoSection>

      {branches.length > 0 && (
        <InfoSection id="branches" heading={branches.length === 1 ? "Where we are" : "Our branches"}>
          <ul className="info-branches">
            {branches.map((branch) => (
              <li key={branch.id}>
                <MapPin aria-hidden="true" />
                <div>
                  <p className="info-branches__name">{branch.branch_name}</p>
                  <p className="info-branches__where">
                    {[branch.address_line_1, branch.city].filter(Boolean).join(", ")}
                  </p>
                  <p className="info-branches__how">
                    {[
                      branch.delivery_enabled ? "Delivery" : null,
                      branch.pickup_enabled ? "Collection" : null,
                    ]
                      .filter(Boolean)
                      .join(" and ") || "Currently not taking orders"}
                  </p>
                </div>
              </li>
            ))}
          </ul>
          <p>
            Each branch keeps its own menu, its own hours and its own prices, so pick the one
            nearest you before you start a cart — a cart belongs to one branch.{" "}
            <Link to="/contact">Opening hours are here.</Link>
          </p>
        </InfoSection>
      )}

      <InfoSection id="how-ordering-works" heading="How ordering here works">
        <div className="info-cards">
          <div className="info-card">
            <ChefHat aria-hidden="true" />
            <h3>Cooked to order</h3>
            <p>
              Nothing is sitting under a lamp. The kitchen starts your order when it accepts it,
              which is the moment the clock on your order page starts moving.
            </p>
          </div>
          <div className="info-card">
            <Clock aria-hidden="true" />
            <h3>You can watch it</h3>
            <p>
              Accepted, being prepared, on its way, delivered. Your{" "}
              <Link to="/orders">orders page</Link> updates as the kitchen moves it, without you
              refreshing.
            </p>
          </div>
          <div className="info-card">
            <Soup aria-hidden="true" />
            <h3>Made how you want it</h3>
            <p>
              Sizes, add-ons and — where the kitchen allows it — two halves of one dish, priced at
              half each rather than guessed at.
            </p>
          </div>
        </div>
      </InfoSection>

      <InfoSection id="reach-us" heading="Talking to us">
        <p>
          {contact.phone
            ? "The fastest way to reach the kitchen about an order that is already in is the phone."
            : "The fastest way to reach us about an order that is already in is the branch itself."}{" "}
          <Link to="/contact">Our address, phone number and opening hours are on the contact page.</Link>
        </p>
      </InfoSection>
    </InfoPage>
  );
}
