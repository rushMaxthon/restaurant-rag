import { createFileRoute, Link } from "@tanstack/react-router";

import { InfoPage, InfoSection } from "@/components/bangkok/info-page";
import { pageMeta, useStorefrontCopy } from "@/lib/storefront";
import { getStorefrontCopy } from "@/lib/storefront.server";

export const Route = createFileRoute("/refunds")({
  loader: () => getStorefrontCopy(),
  head: ({ loaderData }) => ({
    meta: pageMeta(
      loaderData,
      "Cancellations & refunds",
      "When an order can be cancelled, when it cannot, and how a refund reaches you.",
    ),
  }),
  component: RefundsPage,
});

/**
 * When an order can be cancelled, when it cannot, and how a refund arrives.
 *
 * This is the page a customer reads while annoyed, so it says the unwelcome
 * part first rather than after four paragraphs of preamble: there is no
 * cancel button, and there is no cancel button because the kitchen may already
 * be cooking.
 *
 * Everything here is read off the system rather than drafted around it. The
 * order flow is strictly linear and has no human cancellation path at all —
 * every cancellation this platform can produce is one of four system-derived
 * reasons, all of them about a payment that did not complete
 * (`OrderCancellationReason` in `backend/app/models/enums.py`). And there is no
 * refund button either: a refund is issued through the payment provider and
 * arrives back here as a status on the order. Promising a self-service refund
 * flow would be describing software that does not exist.
 *
 * **What the operator must decide, and what is therefore stated as the
 * kitchen's call rather than as a rule**: whether a wrong, cold or missing
 * order is refunded, replaced or credited, and within what window. That is a
 * commercial policy, not a property of the code, and writing a number into it
 * here would invent a promise on a real restaurant's behalf. Review with the
 * operator before launch and replace "the kitchen decides" with their actual
 * policy once they have one.
 */
function RefundsPage() {
  const copy = useStorefrontCopy();

  return (
    <InfoPage
      eyebrow="The small print"
      title="Cancellations & refunds"
      intro={
        <p>
          The short version: once {copy.name} has your order, you cannot cancel it yourself — and
          the reason is that the kitchen may already have started cooking it. Everything below is
          what happens instead.
        </p>
      }
      updated="1 October 2026"
    >
      <InfoSection id="no-self-cancel" heading="You cannot cancel a placed order">
        <p>
          There is no cancel button, and that is deliberate rather than missing. Food is cooked to
          order: by the time you have changed your mind, a pan may be on the heat, and a cancelled
          dish cannot be put back.
        </p>
        <p>
          If you need to stop or change an order, call the branch straight away —{" "}
          <Link to="/contact">the number is on the contact page</Link>. Whether anything can still
          be done depends entirely on how far along it is, and it is the kitchen's call. The
          earlier you call, the more likely the answer is yes.
        </p>
      </InfoSection>

      <InfoSection id="automatic" heading="When an order cancels itself">
        <p>
          Some orders never get as far as the kitchen, and those are cancelled automatically. In
          every one of these cases nothing is captured from you:
        </p>
        <ul className="info-list">
          <li>
            <strong>The payment was not completed.</strong> You started a card payment and left it
            — the order is closed after a short wait.
          </li>
          <li>
            <strong>You closed the payment form.</strong> The order is cancelled rather than left
            sitting unpaid.
          </li>
          <li>
            <strong>The bank declined the card.</strong> Nothing is taken; you can try again with
            another method.
          </li>
        </ul>
        <p>
          Where your bank placed a temporary hold before the payment failed, it is released on the
          bank's own schedule — typically a few working days. That hold is not a charge, and
          nothing has been sent to the restaurant.
        </p>
      </InfoSection>

      <InfoSection id="declined" heading="If the kitchen cannot take your order">
        <p>
          The kitchen can decline an order — usually because a dish has just run out, the branch
          has closed, or the address turns out to be outside its delivery area. Where you have
          already paid, that payment is refunded in full. You will see the order marked as
          cancelled and the payment marked as refunded.
        </p>
      </InfoSection>

      <InfoSection id="something-wrong" heading="If something is wrong with what arrived">
        <p>
          Call the branch, the same day, with your order number — it is on the order itself, from
          your <Link to="/orders">orders page</Link>. Tell them what was wrong: an item missing, a
          dish that is not what was ordered, or food that arrived in a state it should not have.
        </p>
        <p>
          Whether that is put right with a refund, a replacement or a credit is the kitchen's
          decision, and it depends on what happened. A photograph helps. What we can promise is
          that the order record — what you ordered, what you were charged, and when each stage
          happened — is there in full for both of you to look at.
        </p>
      </InfoSection>

      <InfoSection id="not-refunded" heading="What is not refunded">
        <p>
          A delivery that could not be completed because nobody was reachable at the address or on
          the phone number given. The rider has to bring the food back, and food that has been out
          for delivery cannot be re-sent or resold.
        </p>
        <p>
          A collection order that was not collected within the branch's closing time, for the same
          reason.
        </p>
      </InfoSection>

      <InfoSection id="how-refunds-arrive" heading="How a refund reaches you">
        <p>
          A refund goes back the way the payment came — to the same card, through the same payment
          provider. It is not paid out in cash, into a different card, or as a balance on this
          site.
        </p>
        <p>
          Once it is issued, your order page shows the payment as refunded. How long the money
          takes to appear is up to your bank rather than to us; a few working days is normal, and
          some banks are slower.
        </p>
        <p>
          A cash order is settled with the branch directly, because the money never passed through
          a provider in the first place.
        </p>
      </InfoSection>

      <InfoSection id="ask" heading="Still not resolved">
        <p>
          Take it up with the branch again, with the order number to hand.{" "}
          <Link to="/contact">Contact details and opening hours are here.</Link>
        </p>
      </InfoSection>
    </InfoPage>
  );
}
