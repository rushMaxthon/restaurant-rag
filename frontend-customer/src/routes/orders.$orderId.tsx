import { Link, createFileRoute } from "@tanstack/react-router";
import {
  Banknote,
  Bike,
  CalendarClock,
  Check,
  ChevronLeft,
  Clock,
  CreditCard,
  MapPin,
  Store,
  XCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { OrderItemThumb } from "@/components/bangkok/order-item-thumb";
import { expectedBy, lineSelections, orderCode, scheduledFor } from "@/lib/bangkok-data";
import { useRequireAuth } from "@/lib/require-auth";
import { useOrder, usePaymentReconciliation } from "@/lib/queries";
import { pageMeta, useMoney } from "@/lib/storefront";
import { getStorefrontCopy } from "@/lib/storefront.server";

/**
 * The tracker, worded for how the food actually reaches the customer.
 *
 * The backend runs one linear flow for both, so a pickup order passes through
 * OUT_FOR_DELIVERY and DELIVERED too — and someone who chose to collect their
 * own food was told "Your rider is moving".
 */
function stepsFor(isDelivery: boolean) {
  return [
    { key: "PLACED", label: "Placed", blurb: "We have your order" },
    { key: "ACCEPTED", label: "Accepted", blurb: "The kitchen confirmed it" },
    { key: "PREPARING", label: "Preparing", blurb: "Being cooked fresh" },
    isDelivery
      ? { key: "OUT_FOR_DELIVERY", label: "On the way", blurb: "Your rider is moving" }
      : { key: "OUT_FOR_DELIVERY", label: "Ready", blurb: "Waiting at the counter" },
    isDelivery
      ? { key: "DELIVERED", label: "Delivered", blurb: "Enjoy" }
      : { key: "DELIVERED", label: "Collected", blurb: "Enjoy" },
  ];
}

/**
 * What to tell someone about a payment that went through.
 *
 * This said "Paid by card" for every paid order, and "Refunded to your card"
 * for every refund, off `payment_status` alone. A Razorpay link takes UPI,
 * netbanking, wallets and cards, and which of them was used is not something
 * this app is told — so naming the card is a guess that is wrong for most
 * Indian customers. Where the method is known and specific, it is said; where
 * it is not, the true short sentence is.
 */
function paidByLine(method: string | undefined): string {
  switch ((method ?? "").toUpperCase()) {
    case "CARD":
      return "Paid by card";
    case "COD":
      return "Paid in cash";
    default:
      return "Payment received";
  }
}

export const Route = createFileRoute("/orders/$orderId")({
  loader: () => getStorefrontCopy(),
  head: ({ loaderData }) => ({
    meta: pageMeta(loaderData, "Track order", "Follow your order from the kitchen to your doorstep."),
  }),
  component: OrderDetail,
});

function placedAt(iso: string): string {
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return "";
  return new Intl.DateTimeFormat("en-US", {
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
  }).format(then);
}

function OrderDetail() {
  // Prices in whatever this restaurant charges in.
  const money = useMoney();
  const { orderId } = Route.useParams();
  const isAuthenticated = useRequireAuth();
  const orderQuery = useOrder(orderId, isAuthenticated);

  // Stripe has taken the money by the time the customer lands here, but the
  // order only moves once the webhook is verified. Locally that never arrives
  // and in production it can be late, so this asks the reconciling endpoint
  // until the answer changes. See usePaymentReconciliation.
  const awaitingPayment =
    orderQuery.data?.status === "PAYMENT_PENDING" && orderQuery.data?.payment_status !== "COD";
  usePaymentReconciliation(orderId, isAuthenticated && Boolean(awaitingPayment));

  if (!isAuthenticated) return null;

  if (orderQuery.isLoading) {
    return (
      <div className="page-pad mx-auto max-w-6xl py-16">
        <div className="dish-placeholder placeholder-a h-80 animate-pulse rounded-xl" />
      </div>
    );
  }

  if (orderQuery.isError || !orderQuery.data) {
    return (
      <div className="page-pad mx-auto max-w-xl pb-24 pt-16">
        <div className="elevated-panel empty-state">
          <div className="empty-state-icon">
            <XCircle className="size-9" />
          </div>
          <h1 className="mt-8 font-display text-3xl font-extrabold tracking-tight">
            We couldn't find that order
          </h1>
          <p className="mx-auto mt-3 max-w-sm text-muted">
            It may belong to another account, or the link is wrong.
          </p>
          <Button className="mt-8 h-12 px-6 text-base font-bold" asChild>
            <Link to="/orders">All orders</Link>
          </Button>
        </div>
      </div>
    );
  }

  const o = orderQuery.data;
  const cancelled = o.status === "CANCELLED";
  const confirmingPayment = o.status === "PAYMENT_PENDING" && o.payment_status !== "COD";
  // PAYMENT_PENDING is not in STEPS, so findIndex returns -1 and the old
  // Math.max(..., 0) turned "not paid for yet" into "Placed — we have your
  // order" at 20%. An unpaid order has not started, so it shows no progress.
  const isDelivery = o.fulfillment_type === "DELIVERY";
  const STEPS = stepsFor(isDelivery);
  const booked = scheduledFor(o);
  // Only while it is still coming: a delivered or cancelled order has no
  // future, and `expectedBy` is silent once its own estimate has passed.
  const dueBy = cancelled || o.status === "DELIVERED" ? null : expectedBy(o);
  const stepIndex = STEPS.findIndex((s) => s.key === o.status);
  const active = Math.max(stepIndex, 0);
  const progress = cancelled || stepIndex < 0 ? 0 : ((active + 1) / STEPS.length) * 100;
  const discount = Number(o.discount_amount ?? 0);

  return (
    <div className="page-pad mx-auto max-w-6xl pb-24 pt-8">
      <Link to="/orders" className="back-link">
        <ChevronLeft className="size-4" /> All orders
      </Link>

      <header className="mt-2 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm font-extrabold uppercase tracking-wider text-primary">
            Order {orderCode(o)}
          </p>
          <h1 className="mt-2 font-display text-4xl font-extrabold leading-[1.05] tracking-tight sm:text-5xl">
            {cancelled
              ? "This order was cancelled"
              : `Your order is ${o.status.toLowerCase().replaceAll("_", " ")}`}
          </h1>
          <p className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted">
            <span className="inline-flex items-center gap-1.5">
              <Clock className="size-4" />
              Placed {placedAt(o.placed_at)}
            </span>
            <span className="inline-flex items-center gap-1.5">
              {isDelivery ? <Bike className="size-4" /> : <Store className="size-4" />}
              {isDelivery ? "Delivery" : "Pickup"}
            </span>
            {/* The time they booked. Shown next to "Placed" rather than instead
                of it: when the order was made and when it is due are different
                facts, and a scheduled order needs both. */}
            {booked && (
              <span className="inline-flex items-center gap-1.5 font-bold text-primary">
                <CalendarClock className="size-4" />
                {isDelivery ? "Arriving" : "Ready"} {booked}
              </span>
            )}
            {/* The estimate, for an order being made right now. Hedged in
                words because it is one: the branch's own figure from the
                moment the order was placed, not a promise anybody made. */}
            {!booked && dueBy && (
              <span className="inline-flex items-center gap-1.5 font-bold text-primary">
                <CalendarClock className="size-4" />
                {isDelivery ? "Usually arrives by" : "Usually ready by"} {dueBy}
              </span>
            )}
          </p>
        </div>
      </header>

      <div className="mt-8 grid items-start gap-6 grid-cols-[minmax(0,1fr)] lg:grid-cols-[minmax(0,1fr)_420px]">
        <section className="elevated-panel p-5 sm:p-7">
          {cancelled ? (
            <div className="flex items-start gap-3 rounded-xl bg-danger/10 p-4">
              <XCircle className="mt-0.5 size-5 shrink-0 text-danger" />
              <div>
                <p className="font-bold text-danger">Cancelled</p>
                <p className="mt-0.5 text-sm text-muted">
                  Cancellations here are system-derived — nothing further is needed from you.
                </p>
              </div>
            </div>
          ) : (
            <>
              <div className="track-bar mb-7">
                <div className="track-fill" style={{ width: `${progress}%` }} />
              </div>
              <ol className="track-steps">
                {STEPS.map((step, i) => {
                  const state = i < active ? "done" : i === active ? "current" : "todo";
                  return (
                    <li
                      className="track-step flex items-start gap-3.5 pb-6 last:pb-0"
                      data-state={state}
                      key={step.key}
                    >
                      <span className="track-dot" data-state={state}>
                        {state === "done" ? (
                          <Check className="size-3.5" strokeWidth={3} />
                        ) : (
                          <span className="text-xs font-extrabold">{i + 1}</span>
                        )}
                      </span>
                      <div className="min-w-0 pt-0.5">
                        <span className="track-label">{step.label}</span>
                        <p className="track-blurb">
                          {state === "current" ? step.blurb : state === "done" ? "Done" : "Waiting"}
                        </p>
                      </div>
                    </li>
                  );
                })}
              </ol>
            </>
          )}

          {isDelivery && o.delivery_address && (
            <div className="mt-7 flex items-start gap-3 rounded-xl bg-surface-alt p-4">
              <MapPin className="mt-0.5 size-5 shrink-0 text-primary" />
              <div className="min-w-0">
                <p className="text-xs font-extrabold uppercase tracking-wider text-muted">
                  Delivering to
                </p>
                <p className="mt-1 font-semibold leading-snug">{o.delivery_address}</p>
              </div>
            </div>
          )}
        </section>

        <aside className="elevated-panel h-fit p-5 sm:p-6 lg:sticky lg:top-24">
          <h2 className="font-display text-xl font-extrabold tracking-tight">Order summary</h2>

          <ul className="mt-5 space-y-3.5 border-b border-border pb-5">
            {o.items.map((item) => (
              <li className="flex items-center gap-3.5" key={item.id}>
                <OrderItemThumb
                  menuItemId={item.menu_item_id}
                  name={item.item_name_snapshot}
                  className="size-14 shrink-0 rounded-lg text-base ring-1 ring-border"
                />
                <div className="min-w-0 flex-1">
                  <p className="truncate font-semibold leading-snug">{item.item_name_snapshot}</p>
                  {/* The size and options that made up this price. Without them
                      a past order gave no way to see why it cost what it did. */}
                  {lineSelections(item) && (
                    <p className="mt-0.5 text-sm text-muted">{lineSelections(item)}</p>
                  )}
                  <p className="money mt-0.5 text-sm text-muted">
                    {item.quantity} × {money(item.unit_price)}
                  </p>
                </div>
                <span className="money shrink-0 font-bold">{money(item.total_price)}</span>
              </li>
            ))}
          </ul>

          {/* The API returns all of these and the screen used to show only the
              total, so a customer could not see what the fees actually were. */}
          <dl className="mt-5 space-y-2.5 text-sm">
            <div className="sum-row">
              <dt>Subtotal</dt>
              <dd>{money(o.subtotal)}</dd>
            </div>
            <div className="sum-row">
              <dt>{isDelivery ? "Delivery fee" : "Pickup"}</dt>
              <dd>{Number(o.delivery_fee) === 0 ? "Free" : money(o.delivery_fee)}</dd>
            </div>
            <div className="sum-row">
              <dt>Tax</dt>
              <dd>{money(o.tax_amount)}</dd>
            </div>
            {discount > 0 && (
              <div className="sum-row" data-tone="success">
                <dt>Discount</dt>
                <dd>−{money(discount)}</dd>
              </div>
            )}
          </dl>

          <div className="sum-total">
            <span className="text-lg font-extrabold">Total</span>
            <span className="sum-total-figure">{money(o.total_amount)}</span>
          </div>

          {/* Inferring "cash" from "not yet PAID" told a card customer their
              order was cash on delivery for the whole window between paying and
              the webhook landing. The order knows its own method. */}
          <p className="sum-note mt-4">
            {o.payment_status === "COD" ? (
              <Banknote className="size-4" />
            ) : (
              <CreditCard className="size-4" />
            )}
            {/* Every PaymentStatus is named. CANCELLED and FAILED used to fall
                through to "confirming", which left someone whose card was
                declined watching a spinner that would never resolve. */}
            {o.payment_status === "PAID"
              ? paidByLine(o.payment_method)
              : o.payment_status === "COD"
                ? `Pay by cash on ${isDelivery ? "delivery" : "pickup"}`
                : o.payment_status === "REFUNDED"
                  ? "Refunded to how you paid"
                  : o.payment_status === "FAILED"
                    ? "That payment didn't go through"
                    : o.payment_status === "CANCELLED"
                      ? "Payment was not completed"
                      : "Confirming your payment…"}
          </p>

          <Button variant="outline" className="mt-5 h-12 w-full font-bold" asChild>
            <Link to="/menu">Order something else</Link>
          </Button>
        </aside>
      </div>
    </div>
  );
}
