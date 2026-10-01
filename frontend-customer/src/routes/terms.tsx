import { createFileRoute, Link } from "@tanstack/react-router";

import { InfoPage, InfoSection } from "@/components/bangkok/info-page";
import { pageMeta, useStorefrontContact, useStorefrontCopy } from "@/lib/storefront";
import { getStorefrontCopy } from "@/lib/storefront.server";

export const Route = createFileRoute("/terms")({
  loader: () => getStorefrontCopy(),
  head: ({ loaderData }) => ({
    meta: pageMeta(loaderData, "Terms of service", "The terms that apply when you order here."),
  }),
  component: TermsPage,
});

/**
 * The terms that apply when somebody orders here.
 *
 * **What this page is, and what it is not.** Every rule stated below is a rule
 * this software actually enforces — read off the order status flow, the
 * payment service, the slot validator and the customization rules, not copied
 * from a template. That is the half of a terms page that is usually wrong, and
 * it is the half a customer is most likely to be arguing about: when a price
 * is fixed, when an order can still change, what happens if a dish runs out.
 *
 * It is NOT a lawyer's document, and three things in it are the business's to
 * supply rather than ours to invent: the registered entity a customer is
 * contracting with, the governing law and venue, and any tax registration a
 * local regime requires on a receipt. Those are stated here from the
 * restaurant's own record where we have it and left unsaid where we do not,
 * because a guessed entity name or a guessed jurisdiction is worse than a gap
 * — it is a false statement about who is liable.
 *
 * **Review this page with the operator before launch.** It is accurate about
 * the software; it is not a substitute for advice about the business.
 */
function TermsPage() {
  const copy = useStorefrontCopy();
  const contact = useStorefrontContact();

  return (
    <InfoPage
      eyebrow="The small print"
      title="Terms of service"
      intro={
        <p>
          These terms apply when you place an order through this site. They describe what we
          commit to, what we need from you, and what happens when something goes wrong — in the
          order those questions actually come up.
        </p>
      }
      updated="1 October 2026"
    >
      <InfoSection id="who" heading="Who you are ordering from">
        <p>
          This site takes orders for <strong>{copy.name}</strong>
          {contact.address ? (
            <>
              , at {contact.address}
              {contact.country ? `, ${contact.country}` : ""}
            </>
          ) : null}
          . Your order is accepted and cooked by that kitchen, and any question about the food,
          the charge or a refund is settled with it.
        </p>
        <p>
          Each branch is operated separately for the purposes of an order: a branch keeps its own
          menu, prices, fees, minimum order and opening hours, and a cart belongs to exactly one
          branch. That is why a cart cannot mix two branches, and why switching branch starts a
          fresh one.
        </p>
      </InfoSection>

      <InfoSection id="account" heading="Your account">
        <p>
          You need an account to place an order, because an order has to belong to somebody who
          can be reached about it. Keep your password to yourself: an order placed from your
          account is treated as yours.
        </p>
        <p>
          An account on this site is an account <em>on this site</em>. The same phone number or
          email used on another restaurant's site, or in a different app, is a separate account
          with separate orders — they are not linked, and signing in to one does not sign you in
          to the other.
        </p>
      </InfoSection>

      <InfoSection id="orders" heading="Placing an order">
        <p>
          Submitting an order is an offer to buy, not a completed sale. The order is only on when
          the kitchen accepts it, and the kitchen can decline one — most often because a dish has
          just run out, the branch has closed for the day, or the address is outside the area it
          delivers to. Where a payment has already been taken and the order is not accepted, it
          is refunded.
        </p>
        <p>
          Prices, fees and any minimum are the ones shown at the moment you pay, and the total on
          your order page is the total you are charged. Delivery is quoted before you pay — never
          added afterwards — and an order cannot be placed for delivery until a deliverable
          address and a delivery charge have both been settled.
        </p>
        <p>
          Preparation and delivery times are estimates from the kitchen, not guarantees. They
          move with how busy it is.
        </p>
      </InfoSection>

      <InfoSection id="changes" heading="Changing or cancelling">
        <p>
          An order cannot be edited or cancelled by you once it has been placed, because the
          kitchen may already have started cooking it. If something needs to change, call the
          branch — <Link to="/contact">the number is on the contact page</Link> — and it is their
          call whether anything can still be done.
        </p>
        <p>
          <Link to="/refunds">Cancellations and refunds are set out separately.</Link>
        </p>
      </InfoSection>

      <InfoSection id="payment" heading="Paying">
        <p>
          Which methods you can use is decided per branch, and you will only be offered the ones
          that branch actually accepts. Card payments are handled by a payment provider: your
          card details are entered into the provider's own form and are never seen or stored by
          this site or by the restaurant.
        </p>
        <p>
          If a card payment is not completed — the form is closed, the bank declines it, or it is
          left too long — the order is cancelled and nothing is captured. Where an authorisation
          was placed, your bank releases it on its own schedule.
        </p>
      </InfoSection>

      <InfoSection id="food" heading="The food itself">
        <p>
          Dishes are cooked to order, and what is on the menu today is what the branch has today.
          Where a dish can be split into two halves, each half is priced at half the listed extra,
          and the kitchen's own limit on choices applies to each half separately rather than
          across the pair.
        </p>
        <p>
          <strong>Allergies and dietary needs.</strong> Dishes marked vegetarian are marked by the
          kitchen. Food is prepared in a shared kitchen, so we cannot promise that any dish is
          free of a given ingredient. If an ingredient matters to your health, call the branch and
          ask before you order — a note typed into an order is read by the kitchen but is not a
          substitute for that conversation.
        </p>
      </InfoSection>

      <InfoSection id="delivery" heading="Delivery and collection">
        <p>
          Delivery is to the address on the order. Somebody needs to be reachable on the phone
          number given: a rider who cannot find the address or reach anybody may have to return
          the order, and food that has been out for delivery cannot be re-sent.
        </p>
        <p>
          For collection, bring the order number. The kitchen times the food for the collection
          window you chose.
        </p>
      </InfoSection>

      <InfoSection id="conduct" heading="Using this site">
        <p>
          Order food, and leave the site working for everybody else. Don't try to break it, scrape
          it, place orders you do not intend to collect, or use somebody else's account or card.
          An account can be suspended for any of those, and an order refused.
        </p>
      </InfoSection>

      <InfoSection id="ai" heading="Anything a chat assistant tells you">
        <p>
          Where this site offers an assistant, it answers from this branch's live menu — it cannot
          invent a dish, a price or an opening time. It is still a convenience and not a promise:
          the menu, the prices and your order page are the record, and they win over anything a
          conversation said.
        </p>
      </InfoSection>

      <InfoSection id="changes-to-terms" heading="Changes to these terms">
        <p>
          These terms can change. The date at the top of this page is when they last did, and the
          version in force for an order is the one published when you placed it.
        </p>
      </InfoSection>

      <InfoSection id="reach" heading="Questions about these terms">
        <p>
          Raise them with the kitchen —{" "}
          <Link to="/contact">address, phone number and hours are on the contact page</Link>.
        </p>
      </InfoSection>
    </InfoPage>
  );
}
