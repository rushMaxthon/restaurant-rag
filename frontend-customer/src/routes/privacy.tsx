import { createFileRoute, Link } from "@tanstack/react-router";

import { InfoPage, InfoSection } from "@/components/bangkok/info-page";
import { pageMeta, useStorefrontContact, useStorefrontCopy } from "@/lib/storefront";
import { getStorefrontCopy } from "@/lib/storefront.server";

export const Route = createFileRoute("/privacy")({
  loader: () => getStorefrontCopy(),
  head: ({ loaderData }) => ({
    meta: pageMeta(
      loaderData,
      "Privacy",
      "What this site stores about you, who it is shared with, and how to change it.",
    ),
  }),
  component: PrivacyPage,
});

/**
 * What this site actually stores, and who it actually goes to.
 *
 * Written from the schema and the code paths rather than from a template, which
 * is the only way a privacy notice is worth reading. Each claim below maps to
 * something checkable: the `users` and `orders` columns, the geocoding call the
 * address box makes, the courier handoff in the delivery service, the payment
 * provider's own form, the Firebase token a push notification needs, and the
 * Redis session the assistant keeps.
 *
 * **Two disclosures here are the uncomfortable kind, and are stated plainly on
 * purpose.** Marketing consent on this platform is OPT-OUT — a new account
 * starts opted in — and a typed address is sent to a mapping provider to be
 * turned into coordinates. Both are true, both are the sort of thing a notice
 * usually buries, and burying them is what makes a notice worthless.
 *
 * **What is deliberately absent**: a retention period in days, a named legal
 * basis, a supervisory authority and a grievance officer. Those depend on where
 * the business is registered and which regime applies to it, and inventing them
 * would be a claim about the business's obligations rather than about this
 * software. The operator's own advisers fill those in. Review this page with
 * them before launch.
 */
function PrivacyPage() {
  const copy = useStorefrontCopy();
  const contact = useStorefrontContact();

  return (
    <InfoPage
      eyebrow="The small print"
      title="Privacy"
      intro={
        <p>
          This page is about the information <strong>{copy.name}</strong> holds when you order
          here: what is stored, why it has to be, who else sees it, and what you can change.
        </p>
      }
      updated="1 October 2026"
    >
      <InfoSection id="what" heading="What is stored">
        <p>
          <strong>Your account.</strong> Your name, email address and phone number, a scrambled
          form of your password — never the password itself — and a default delivery address if
          you save one.
        </p>
        <p>
          <strong>Your orders.</strong> What you ordered and how you customised it, the delivery
          address and contact number for that order, any note you left for the kitchen, when each
          stage happened, and whether the payment succeeded. Orders are kept after they are
          delivered: they are the receipt, and the record the kitchen works from if you query a
          charge.
        </p>
        <p>
          <strong>Your preferences.</strong> Dietary and spice preferences if you set them, and
          whether you want marketing messages.
        </p>
        <p>
          <strong>Not your card.</strong> Card numbers are typed into the payment provider's own
          form and never reach this site or the restaurant. What is stored here is the provider's
          reference for the payment and whether it went through.
        </p>
      </InfoSection>

      <InfoSection id="where-it-goes" heading="Who else sees it">
        <p>
          Only the parties who have to, and only the part they need.
        </p>
        <ul className="info-list">
          <li>
            <strong>The kitchen.</strong> Staff at the branch cooking your order see the order,
            the address and the contact number. Staff of other branches and other restaurants do
            not.
          </li>
          <li>
            <strong>The payment provider.</strong> Your card details go to them directly, along
            with the amount and an order reference.
          </li>
          <li>
            <strong>The courier,</strong> for a delivery order. They are given the delivery
            address and a contact number, because that is what it takes to hand food to somebody.
            A collection order involves no courier.
          </li>
          <li>
            <strong>A mapping provider,</strong> when you type an address. The text you type is
            sent to be completed and turned into coordinates, which is what makes the delivery
            charge for your address — rather than a flat guess — possible.
          </li>
          <li>
            <strong>A notification service,</strong> if you allow order notifications. It holds a
            device token, not your name.
          </li>
        </ul>
        <p>
          Your information is not sold, and it is not handed to anybody for advertising.
        </p>
      </InfoSection>

      <InfoSection id="marketing" heading="Marketing messages, and how to stop them">
        <p>
          <strong>A new account starts opted in.</strong> That is worth saying plainly rather than
          leaving you to discover it: this platform treats marketing as opt-OUT, so unless you
          turn it off you may receive occasional offers about this restaurant.
        </p>
        <p>
          Turning it off takes one switch on your{" "}
          <Link to="/preferences">preferences page</Link>, and it takes effect immediately.
          Replying <strong>STOP</strong> to a message does the same thing, and it opts out every
          account on that phone number rather than just the one the message went to.
        </p>
        <p>
          Notifications about an order you placed — accepted, on its way, delivered — are not
          marketing and are not covered by that switch. They are part of the order.
        </p>
      </InfoSection>

      <InfoSection id="assistant" heading="If you use the chat assistant">
        <p>
          Where this site offers an assistant, your side of the conversation is kept briefly so it
          can follow what you are talking about across a few messages, and it expires on its own.
          It answers from this branch's live menu. Don't type anything into it you would not want
          stored — it is a menu assistant, not a private channel.
        </p>
      </InfoSection>

      <InfoSection id="browser" heading="What is kept in your browser">
        <p>
          The sign-in token that keeps you signed in, the branch you chose, your cart before you
          pay, and whether you prefer the light or dark theme. None of it is advertising, and none
          of it is shared with anybody — it is how the site remembers what you were doing.
        </p>
      </InfoSection>

      <InfoSection id="control" heading="What you can change">
        <ul className="info-list">
          <li>
            Your name, phone number and saved address — on your{" "}
            <Link to="/profile">account page</Link>.
          </li>
          <li>
            Marketing consent and food preferences — on your{" "}
            <Link to="/preferences">preferences page</Link>.
          </li>
          <li>
            Anything else, including a copy of what is held about you or a request to close your
            account — ask the kitchen.{" "}
            {contact.phone
              ? "The phone number is on the contact page."
              : "Contact details are on the contact page."}
          </li>
        </ul>
        <p className="info-note">
          Closing an account does not delete past orders. They are the restaurant's business
          records of a transaction that happened, and they are kept as such.
        </p>
      </InfoSection>

      <InfoSection id="security" heading="Keeping it safe">
        <p>
          Connections to this site are encrypted. Passwords are stored only as a one-way hash, so
          nobody — including the restaurant — can read yours. Sign-ins can be revoked, and are
          revoked automatically when an account is deactivated.
        </p>
        <p>
          No system is beyond reach. If you think your account has been used by somebody else,
          change your password and tell the kitchen.
        </p>
      </InfoSection>

      <InfoSection id="changes" heading="Changes to this page">
        <p>
          The date at the top is when this page last changed. Where a change affects what is
          collected or who it goes to, it will be said here rather than left to be noticed.
        </p>
      </InfoSection>
    </InfoPage>
  );
}
