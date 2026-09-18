import { useEffect, useRef, useState } from "react";
import { AlertCircle, ShieldCheck } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ApiError, api } from "@/lib/api";
import { useMoney } from "@/lib/storefront";

/**
 * Razorpay Checkout, opened against an order the backend already created.
 *
 * Razorpay's flow is not Stripe's, and the difference shapes this component.
 * Stripe mounts an iframe that collects the card and confirms an intent
 * client-side. Razorpay opens its own modal over the page, settles UPI, cards,
 * netbanking and wallets inside it, and hands three values back — an order id,
 * a payment id, and a signature over both.
 *
 * **Those three are worth nothing until the server checks them.** They arrive
 * in the browser, which means they can be fabricated by anyone willing to
 * open devtools. `api.confirmRazorpayPayment` posts them back and the server
 * verifies the signature against that restaurant's own API secret before any
 * order is marked paid.
 *
 * And the confirm call is the fast path, not the source of truth: it marks the
 * order paid while the customer is still looking at the screen. If they close
 * the tab first, the webhook settles it instead, and both routes end at the
 * same idempotent handler. So a failure here is not a failed payment, and this
 * component is careful never to say that it is.
 */
const CHECKOUT_SCRIPT = "https://checkout.razorpay.com/v1/checkout.js";

type RazorpayHandlerResponse = {
  razorpay_order_id: string;
  razorpay_payment_id: string;
  razorpay_signature: string;
};

type RazorpayInstance = { open: () => void; close: () => void };

declare global {
  interface Window {
    Razorpay?: new (options: Record<string, unknown>) => RazorpayInstance;
  }
}

/**
 * Loaded once per page rather than once per render.
 *
 * Razorpay's script registers a global; loading it twice re-registers it
 * mid-checkout. The promise is cached so a customer who cancels and reopens
 * does not re-download it.
 */
let scriptPromise: Promise<boolean> | null = null;

function loadCheckoutScript(): Promise<boolean> {
  if (typeof window === "undefined") return Promise.resolve(false);
  if (window.Razorpay) return Promise.resolve(true);
  if (scriptPromise) return scriptPromise;

  scriptPromise = new Promise<boolean>((resolve) => {
    const existing = document.querySelector<HTMLScriptElement>(
      `script[src="${CHECKOUT_SCRIPT}"]`,
    );
    const script = existing ?? document.createElement("script");
    script.src = CHECKOUT_SCRIPT;
    script.async = true;
    script.addEventListener("load", () => resolve(Boolean(window.Razorpay)));
    // A blocked or failed script is not an error to throw: the customer is
    // told the method is unavailable and can choose another.
    script.addEventListener("error", () => {
      scriptPromise = null;
      resolve(false);
    });
    if (!existing) document.body.appendChild(script);
  });
  return scriptPromise;
}

interface RazorpayPaymentProps {
  /** The restaurant's own `key_id`. Public — it is in this page's source. */
  keyId: string;
  /** The Razorpay order id the backend created, carried as the intent id. */
  razorpayOrderId: string;
  orderId: string;
  orderNumber: string;
  amount: number | string;
  /** What the modal shows above the amount. */
  restaurantName: string;
  customerName?: string | null;
  customerEmail?: string | null;
  customerPhone?: string | null;
  onPaid: () => void;
  onCancel: () => void;
}

export function RazorpayPayment({
  keyId,
  razorpayOrderId,
  orderId,
  orderNumber,
  amount,
  restaurantName,
  customerName,
  customerEmail,
  customerPhone,
  onPaid,
  onCancel,
}: RazorpayPaymentProps) {
  // Prices in whatever this restaurant charges in — the same formatter every
  // other amount on the site goes through.
  const money = useMoney();
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Guards the double-open: Razorpay's modal is not idempotent, and a second
  // instance over the first leaves a customer looking at a dialog whose
  // cancel button closes the wrong one.
  const openRef = useRef(false);

  useEffect(() => {
    let cancelled = false;
    void loadCheckoutScript().then((loaded) => {
      if (cancelled) return;
      setReady(loaded);
      if (!loaded) {
        setError(
          "We couldn't load the payment window. Check your connection, or choose another way to pay.",
        );
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  async function confirm(response: RazorpayHandlerResponse): Promise<void> {
    setBusy(true);
    try {
      await api.confirmRazorpayPayment(orderId, response);
      onPaid();
    } catch (caught: unknown) {
      // The money may well have moved — this call is the fast path, and the
      // webhook is the backstop. Saying "payment failed" here would be a
      // guess, and the wrong one often enough to matter.
      setError(
        caught instanceof ApiError
          ? `We couldn't confirm the payment yet: ${caught.message} If your account was charged, your order will update shortly.`
          : "We couldn't confirm the payment yet. If your account was charged, your order will update shortly.",
      );
    } finally {
      setBusy(false);
      openRef.current = false;
    }
  }

  function open(): void {
    if (!window.Razorpay || openRef.current) return;
    setError(null);
    openRef.current = true;

    const checkout = new window.Razorpay({
      key: keyId,
      order_id: razorpayOrderId,
      name: restaurantName,
      description: `Order ${orderNumber}`,
      // Razorpay takes the amount from the order it is settling, so it is not
      // sent again here — passing a second figure is how a display amount and
      // a charged amount end up disagreeing.
      prefill: {
        name: customerName ?? undefined,
        email: customerEmail ?? undefined,
        contact: customerPhone ?? undefined,
      },
      theme: { color: "#ff5200" },
      handler: (response: RazorpayHandlerResponse) => {
        void confirm(response);
      },
      modal: {
        ondismiss: () => {
          openRef.current = false;
          // Closing the window is not abandoning the order: it is held, and
          // the customer can pay again or leave. `onCancel` is the explicit
          // "I do not want to pay now" further down.
          setError(null);
        },
      },
    });

    checkout.open();
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted">
        Pay {money(amount)} with UPI, a card, netbanking or a wallet. The
        payment window opens over this page.
      </p>

      {error ? (
        <div className="inline-error" role="alert">
          <AlertCircle className="mt-0.5 size-4 shrink-0" />
          <span>{error}</span>
        </div>
      ) : null}

      <Button className="w-full" disabled={!ready || busy} onClick={open} size="lg">
        {busy ? "Confirming…" : `Pay ${money(amount)}`}
      </Button>

      <p className="flex items-center gap-2 text-sm text-muted">
        <ShieldCheck className="size-4 shrink-0 text-success" />
        Your payment details go straight to Razorpay — this app never sees them.
      </p>

      <Button className="w-full" disabled={busy} onClick={onCancel} variant="ghost">
        Pay later
      </Button>
    </div>
  );
}
