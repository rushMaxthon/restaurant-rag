import { useState } from "react";
import { Elements, PaymentElement, useElements, useStripe } from "@stripe/react-stripe-js";
import { loadStripe, type Stripe } from "@stripe/stripe-js";
import { AlertCircle, Lock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { formatMoney } from "@/lib/bangkok-data";

/**
 * Stripe's Payment Element, mounted against an intent the backend created.
 *
 * The card details are typed into an iframe Stripe serves, so they never touch
 * this app or its server — which is the whole reason to use the Element rather
 * than our own card inputs. `confirmPayment` needs that Element: a client
 * secret alone has nothing to confirm with.
 *
 * `loadStripe` is cached per publishable key. Calling it on every render would
 * re-download Stripe.js and remount the iframe, wiping whatever the customer
 * had typed.
 */
const stripeCache = new Map<string, Promise<Stripe | null>>();

function stripeFor(publishableKey: string): Promise<Stripe | null> {
  const cached = stripeCache.get(publishableKey);
  if (cached) return cached;
  const created = loadStripe(publishableKey);
  stripeCache.set(publishableKey, created);
  return created;
}

type CardPaymentProps = {
  publishableKey: string;
  clientSecret: string;
  amount: number;
  /** Where Stripe sends the customer back for redirect-based methods (3-D Secure). */
  returnUrl: string;
  onCancel: () => void;
};

function PayForm({
  amount,
  returnUrl,
  onCancel,
}: Omit<CardPaymentProps, "publishableKey" | "clientSecret">) {
  const stripe = useStripe();
  const elements = useElements();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // Silently returning here made the Pay button do nothing at all — no error,
    // no spinner, no navigation — whenever Stripe.js had not finished loading.
    // A dead button with no feedback is the worst possible failure on a payment
    // screen: the customer presses it again, and again.
    if (!stripe || !elements) {
      setError("The payment form is still loading. Give it a moment and try again.");
      return;
    }
    setBusy(true);
    setError(null);

    // `redirect: "if_required"` keeps a plain card payment on this page and
    // only navigates for methods that genuinely need it, so the common case
    // never loses the page state.
    const result = await stripe.confirmPayment({
      elements,
      confirmParams: { return_url: returnUrl },
      redirect: "if_required",
    });

    if (result.error) {
      setError(result.error.message ?? "That payment didn't go through.");
      setBusy(false);
      return;
    }
    // No error and no redirect: the intent succeeded. The order is still moved
    // out of PAYMENT_PENDING by the webhook, not by this callback — a client
    // must never be the thing that says money arrived.
    window.location.assign(returnUrl);
  }

  return (
    <form onSubmit={handleSubmit} className="grid gap-4">
      <PaymentElement options={{ layout: "tabs" }} />

      {error && (
        <div
          className="flex items-start gap-2 rounded-xl border border-danger bg-danger/10 p-3 text-sm font-semibold text-danger"
          role="alert"
        >
          <AlertCircle className="mt-0.5 size-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <Button
        type="submit"
        className="h-12 w-full text-base"
        disabled={!stripe || !elements || busy}
      >
        <Lock className="size-4" />
        {busy ? "Confirming…" : `Pay ${formatMoney(amount)}`}
      </Button>
      <Button type="button" variant="ghost" className="h-10" onClick={onCancel} disabled={busy}>
        Cancel and keep my cart
      </Button>
    </form>
  );
}

export function CardPayment({
  publishableKey,
  clientSecret,
  amount,
  returnUrl,
  onCancel,
}: CardPaymentProps) {
  return (
    <Elements stripe={stripeFor(publishableKey)} options={{ clientSecret }}>
      <PayForm amount={amount} returnUrl={returnUrl} onCancel={onCancel} />
    </Elements>
  );
}
