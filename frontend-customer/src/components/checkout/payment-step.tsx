import { Link } from "@tanstack/react-router";
import { AlertCircle, BadgeCheck, CreditCard, ShieldCheck } from "lucide-react";

import { StepHeader } from "@/components/checkout/step-header";

export type PayableMethod = "CARD" | "RAZORPAY";

/** What each method is called, in one place so the single-method block and
 *  the chooser cannot describe the same gateway two different ways. */
const METHOD_TITLE: Record<PayableMethod, string> = {
  CARD: "Pay by card",
  RAZORPAY: "UPI, cards and wallets",
};
const METHOD_BLURB: Record<PayableMethod, string> = {
  CARD: "Visa, Mastercard and Amex, handled by Stripe.",
  RAZORPAY: "Any UPI app, card, netbanking or wallet, handled by Razorpay.",
};

/**
 * Step three: how this is paid for.
 *
 * Stateless, like the other two steps. Which methods THIS restaurant can take
 * is decided in the checkout from `/payments/config` — one deployment serves
 * every tenant, and a Surat kitchen on Razorpay and a Toronto one on Stripe are
 * both correct at once — so nothing here is a button that dead-ends.
 */
export function PaymentStep({
  paymentConfigPending,
  canPay,
  sessionExpired,
  paymentConfigFailed,
  payableMethods,
  method,
  onChooseMethod,
}: {
  paymentConfigPending: boolean;
  canPay: boolean;
  sessionExpired: boolean;
  paymentConfigFailed: boolean;
  payableMethods: readonly PayableMethod[];
  method: PayableMethod;
  onChooseMethod: (method: PayableMethod) => void;
}) {
  return (
    <section className="elevated-panel step-panel">
      <StepHeader
        number={3}
        title="Payment"
        blurb="Paid securely before your order reaches the kitchen."
      />

      {/* ONE method: described, not offered as a choice.
          -------------------------------------------------------------------
          This block used to render unconditionally and always said "Pay by
          card … handled by Stripe", which was true back when Stripe was the
          only gateway. It produced two bugs the moment a second one could be
          switched on. A restaurant with both showed card twice — once here
          and again in the list below. And a restaurant on Razorpay ALONE got
          a greyed-out card block describing a gateway it does not use, with
          no mention of the one it does.

          So the single-method case now describes whichever method that
          actually is. */}
      {payableMethods.length === 1 && payableMethods[0] && (
        <div className="mt-4 pay-option" data-on={canPay}>
          <CreditCard className="size-5 shrink-0 text-primary" />
          <span className="min-w-0 flex-1">
            <span className="block font-bold">{METHOD_TITLE[payableMethods[0]]}</span>
            <span className="block text-sm text-muted">{METHOD_BLURB[payableMethods[0]]}</span>
          </span>
          {canPay && <BadgeCheck className="size-5 shrink-0 text-primary" />}
        </div>
      )}

      {paymentConfigPending && <p className="mt-3 text-sm text-muted">Checking payment options…</p>}

      {!paymentConfigPending && !canPay && (
        <div
          className="mt-3 flex items-start gap-2 rounded-xl border border-danger bg-danger/10 p-3 text-sm font-semibold text-danger"
          role="alert"
        >
          <AlertCircle className="mt-0.5 size-4 shrink-0" />
          <span>
            {sessionExpired ? (
              <>
                Your sign-in has expired.{" "}
                <Link className="underline" to="/login" search={{ redirect: "/checkout" }}>
                  Sign in again
                </Link>{" "}
                — your cart is saved and you will come straight back here.
              </>
            ) : paymentConfigFailed ? (
              "We couldn't check the payment options just now. Check your connection and try again."
            ) : (
              "This restaurant hasn't switched on a way to pay yet, so orders can't be placed. Please try again shortly."
            )}
          </span>
        </div>
      )}

      {/* Only where there is a choice. One method is not a list to pick from,
          and rendering it as one asks the customer to make a decision that
          does not exist. */}
      {payableMethods.length > 1 && (
        <div className="mt-4 grid gap-2" role="radiogroup" aria-label="How to pay">
          {payableMethods.map((option) => (
            <button
              aria-checked={method === option}
              className="pay-option"
              data-selected={method === option}
              key={option}
              onClick={() => onChooseMethod(option)}
              role="radio"
              type="button"
            >
              <CreditCard className="size-5 shrink-0 text-primary" />
              <span className="min-w-0 flex-1 text-left">
                <span className="block font-bold">{METHOD_TITLE[option]}</span>
                <span className="block text-sm text-muted">{METHOD_BLURB[option]}</span>
              </span>
              {method === option && <BadgeCheck className="size-5 shrink-0 text-primary" />}
            </button>
          ))}
        </div>
      )}

      <p className="mt-3 flex items-center gap-2 text-sm text-muted">
        <ShieldCheck className="size-4 shrink-0 text-success" />
        {method === "RAZORPAY"
          ? "Your payment details go straight to Razorpay — this app never sees them."
          : "Your card details go straight to Stripe — this app never sees them."}
      </p>
    </section>
  );
}
