import { Link, createFileRoute } from "@tanstack/react-router";
import { Bike, Check, ChevronLeft, Clock, MapPin, Store, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { OrderItemThumb } from "@/components/bangkok/order-item-thumb";
import { formatMoney, orderCode } from "@/lib/bangkok-data";
import { useRequireAuth } from "@/lib/require-auth";
import { useOrder } from "@/lib/queries";

const STEPS = [
  { key: "PLACED", label: "Placed", blurb: "We have your order" },
  { key: "ACCEPTED", label: "Accepted", blurb: "The kitchen confirmed it" },
  { key: "PREPARING", label: "Preparing", blurb: "Being cooked fresh" },
  { key: "OUT_FOR_DELIVERY", label: "On the way", blurb: "Your rider is moving" },
  { key: "DELIVERED", label: "Delivered", blurb: "Enjoy" },
];

export const Route = createFileRoute("/orders/$orderId")({
  head: () => ({
    meta: [
      { title: "Track Order — Bangkok Bowl" },
      { name: "description", content: "Follow your Bangkok Bowl order from kitchen to doorstep." },
      { property: "og:title", content: "Track Order — Bangkok Bowl" },
      { property: "og:description", content: "Live Bangkok Bowl order status." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
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
  const { orderId } = Route.useParams();
  const isAuthenticated = useRequireAuth();
  const orderQuery = useOrder(orderId, isAuthenticated);

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
      <div className="page-pad mx-auto max-w-xl py-24 text-center">
        <h1 className="font-display text-3xl font-black">We couldn't find that order</h1>
        <p className="mt-3 text-muted">It may belong to another account, or the link is wrong.</p>
        <Button className="mt-7 h-12 px-6" asChild>
          <Link to="/orders">All orders</Link>
        </Button>
      </div>
    );
  }

  const o = orderQuery.data;
  const cancelled = o.status === "CANCELLED";
  const active = Math.max(
    STEPS.findIndex((s) => s.key === o.status),
    0,
  );
  const progress = cancelled ? 0 : ((active + 1) / STEPS.length) * 100;
  const isDelivery = o.fulfillment_type === "DELIVERY";
  const discount = Number(o.discount_amount ?? 0);

  return (
    <div className="page-pad mx-auto max-w-6xl pb-24 pt-8">
      <Link
        to="/orders"
        className="inline-flex items-center gap-1.5 text-sm font-bold text-muted hover:text-foreground"
      >
        <ChevronLeft className="size-4" /> All orders
      </Link>

      <header className="mt-4 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="font-bold text-primary">Order {orderCode(o)}</p>
          <h1 className="mt-1 font-display text-4xl font-black sm:text-5xl">
            {cancelled
              ? "This order was cancelled"
              : `Your order is ${o.status.toLowerCase().replaceAll("_", " ")}`}
          </h1>
          <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-muted">
            <span className="flex items-center gap-1.5">
              <Clock className="size-4" />
              Placed {placedAt(o.placed_at)}
            </span>
            <span className="flex items-center gap-1.5">
              {isDelivery ? <Bike className="size-4" /> : <Store className="size-4" />}
              {isDelivery ? "Delivery" : "Pickup"}
            </span>
          </p>
        </div>
      </header>

      <div className="mt-8 grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_420px]">
        <section className="elevated-panel p-5 sm:p-6">
          {cancelled ? (
            <div className="flex items-start gap-3 rounded-xl bg-danger/10 p-4">
              <XCircle className="mt-0.5 size-5 shrink-0 text-danger" />
              <div>
                <p className="font-bold text-danger">Cancelled</p>
                <p className="text-sm text-muted">
                  Cancellations here are system-derived — nothing further is needed from you.
                </p>
              </div>
            </div>
          ) : (
            <>
              <div className="track-bar mb-6">
                <div className="track-fill" style={{ width: `${progress}%` }} />
              </div>
              <ol className="track-steps">
                {STEPS.map((step, i) => {
                  const state = i < active ? "done" : i === active ? "current" : "todo";
                  return (
                    <li className="flex items-start gap-3 pb-5 last:pb-0" key={step.key}>
                      <span className="track-dot" data-state={state}>
                        {state === "done" ? (
                          <Check className="size-3.5" strokeWidth={3} />
                        ) : (
                          <span className="text-xs font-black">{i + 1}</span>
                        )}
                      </span>
                      <div className="min-w-0">
                        <b className={state === "todo" ? "text-muted" : undefined}>{step.label}</b>
                        <p className="text-sm text-muted">
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
            <div className="mt-5 flex items-start gap-3 rounded-xl bg-surface-alt p-4">
              <MapPin className="mt-0.5 size-5 shrink-0 text-primary" />
              <div>
                <p className="text-xs font-bold uppercase tracking-wide text-muted">
                  Delivering to
                </p>
                <p className="mt-0.5 font-semibold">{o.delivery_address}</p>
              </div>
            </div>
          )}
        </section>

        <aside className="elevated-panel h-fit p-5 lg:sticky lg:top-24">
          <h2 className="font-display text-xl font-black">Order summary</h2>

          <div className="mt-5 space-y-3 border-b border-border pb-5">
            {o.items.map((item) => (
              <div className="flex items-center gap-3" key={item.id}>
                <OrderItemThumb
                  menuItemId={item.menu_item_id}
                  name={item.item_name_snapshot}
                  className="size-14 shrink-0 rounded-lg"
                />
                <div className="min-w-0 flex-1">
                  <p className="truncate font-semibold">{item.item_name_snapshot}</p>
                  <p className="money text-sm text-muted">
                    {item.quantity} × {formatMoney(item.unit_price)}
                  </p>
                </div>
                <span className="money shrink-0 font-bold">{formatMoney(item.total_price)}</span>
              </div>
            ))}
          </div>

          {/* The API returns all of these and the screen used to show only the
              total, so a customer could not see what the fees actually were. */}
          <dl className="mt-5 space-y-2.5 text-sm">
            <div className="flex justify-between">
              <dt className="text-muted">Subtotal</dt>
              <dd className="money font-semibold">{formatMoney(o.subtotal)}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-muted">{isDelivery ? "Delivery fee" : "Pickup"}</dt>
              <dd className="money font-semibold">
                {Number(o.delivery_fee) === 0 ? "Free" : formatMoney(o.delivery_fee)}
              </dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-muted">Tax</dt>
              <dd className="money font-semibold">{formatMoney(o.tax_amount)}</dd>
            </div>
            {discount > 0 && (
              <div className="flex justify-between text-success">
                <dt>Discount</dt>
                <dd className="money font-semibold">−{formatMoney(discount)}</dd>
              </div>
            )}
          </dl>

          <div className="total-row mt-4 flex items-end justify-between border-t border-border pt-4">
            <span className="text-lg font-black">Total</span>
            <span className="font-display text-3xl font-black">{formatMoney(o.total_amount)}</span>
          </div>

          {/* Inferring "cash" from "not yet PAID" told a card customer their
              order was cash on delivery for the whole window between paying and
              the webhook landing. The order knows its own method. */}
          <p className="mt-4 text-sm text-muted">
            {o.payment_status === "PAID"
              ? "Paid by card"
              : o.payment_status === "COD"
                ? `Pay by cash on ${isDelivery ? "delivery" : "pickup"}`
                : "Card payment confirming…"}
          </p>

          <Button variant="outline" className="mt-5 h-12 w-full" asChild>
            <Link to="/menu">Order something else</Link>
          </Button>
        </aside>
      </div>
    </div>
  );
}
