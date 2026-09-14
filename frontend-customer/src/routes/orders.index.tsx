import { Link, createFileRoute, useNavigate } from "@tanstack/react-router";
import {
  ArrowRight,
  Bike,
  CalendarClock,
  LogOut,
  ReceiptText,
  Store,
  WalletCards,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { OrderItemThumb } from "@/components/bangkok/order-item-thumb";
import { formatMoney, orderCode, scheduledFor, type Order } from "@/lib/bangkok-data";
import { useAuth } from "@/lib/auth";
import { useRequireAuth } from "@/lib/require-auth";
import { useOrders } from "@/lib/queries";

export const Route = createFileRoute("/orders/")({
  head: () => ({
    meta: [
      { title: "Your Orders — Bangkok Bowl" },
      { name: "description", content: "Track current Bangkok Bowl orders and view past orders." },
      { property: "og:title", content: "Your Orders — Bangkok Bowl" },
      { property: "og:description", content: "Track and review your Bangkok Bowl orders." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: Orders,
});

/** Strictly linear, matching OrderStatus on the backend. */
const FLOW = ["PLACED", "ACCEPTED", "PREPARING", "OUT_FOR_DELIVERY", "DELIVERED"];
const SETTLED = new Set(["DELIVERED", "CANCELLED"]);

const STATUS_TONE: Record<string, string> = {
  DELIVERED: "bg-success/15 text-success",
  CANCELLED: "bg-danger/15 text-danger",
};

function placedAt(iso: string): string {
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return "";
  const today = new Date();
  const sameDay = then.toDateString() === today.toDateString();
  const time = new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit" }).format(
    then,
  );
  if (sameDay) return `Today, ${time}`;
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (then.toDateString() === yesterday.toDateString()) return `Yesterday, ${time}`;
  return `${new Intl.DateTimeFormat("en-US", { day: "numeric", month: "short" }).format(then)}, ${time}`;
}

function OrderRow({ order, index }: { order: Order; index: number }) {
  const tone = STATUS_TONE[order.status] ?? "bg-primary/15 text-primary";
  // An unpaid order has not started, so it gets no pulse and no progress bar.
  const unpaid = order.status === "PAYMENT_PENDING" && order.payment_status !== "COD";
  const live = !SETTLED.has(order.status) && !unpaid;
  const step = Math.max(FLOW.indexOf(order.status), 0);
  const progress = ((step + 1) / FLOW.length) * 100;
  const itemCount = order.items.reduce((sum, item) => sum + item.quantity, 0);
  const isDelivery = order.fulfillment_type === "DELIVERY";
  const booked = scheduledFor(order);

  return (
    <article
      className="line-card elevated-panel rise-in min-w-0 p-4 sm:p-5"
      style={{ "--i": Math.min(index, 8) } as React.CSSProperties}
    >
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-x-6 gap-y-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5 text-sm">
            <span className={`status-chip ${tone}`}>{order.status.replaceAll("_", " ")}</span>
            {order.restaurant && <span className="font-bold">{order.restaurant.name}</span>}
            <span className="inline-flex items-center gap-1 text-muted">
              {isDelivery ? <Bike className="size-3.5" /> : <Store className="size-3.5" />}
              {isDelivery ? "Delivery" : "Pickup"}
            </span>
          </div>

          <div className="mt-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h2 className="whitespace-nowrap font-display text-xl font-black leading-none tracking-tight">
              Order {orderCode(order)}
            </h2>
            {/* Neither the date nor the item list was shown before, which made
                the history a wall of near-identical cards. */}
            <span className="text-sm text-muted">{placedAt(order.placed_at)}</span>
          </div>

          {/* A booked time is the single most important fact about a scheduled
              order, and it was shown nowhere after checkout. */}
          {booked && (
            <p className="mt-2 inline-flex items-center gap-1.5 text-sm font-bold text-primary">
              <CalendarClock className="size-4 shrink-0" />
              {isDelivery ? "Arriving" : "Ready"} {booked}
            </p>
          )}

          <p className="mt-2 truncate text-sm text-muted">
            <span className="font-semibold text-foreground">
              {itemCount} {itemCount === 1 ? "item" : "items"}
            </span>{" "}
            · {order.items.map((item) => `${item.quantity}× ${item.item_name_snapshot}`).join(", ")}
          </p>

          <div className="mt-4 flex flex-wrap items-center gap-2">
            {order.items.slice(0, 4).map((item) => (
              <OrderItemThumb
                key={item.id}
                menuItemId={item.menu_item_id}
                name={item.item_name_snapshot}
                className="size-12 rounded-lg text-sm ring-1 ring-border"
              />
            ))}
            {order.items.length > 4 && (
              <span className="grid size-12 place-items-center rounded-lg bg-surface-alt text-xs font-extrabold text-muted">
                +{order.items.length - 4}
              </span>
            )}
          </div>
        </div>

        <div className="flex shrink-0 flex-col items-end gap-3 sm:min-w-36">
          <b className="money font-display text-2xl font-black leading-none tracking-tight">
            {formatMoney(order.total_amount)}
          </b>
          <Button variant={live ? "default" : "outline"} className="font-bold" asChild>
            <Link to="/orders/$orderId" params={{ orderId: order.id }}>
              {live ? "Track order" : "View order"} <ArrowRight className="size-4" />
            </Link>
          </Button>
        </div>
      </div>

      {live && (
        <div className="track mt-5 border-t border-border pt-4">
          <div className="track-bar track-bar--segmented">
            <div className="track-fill" style={{ width: `${progress}%` }} />
          </div>
          <p className="track-caption">
            <span>
              Step {step + 1} of {FLOW.length}
            </span>
            <span aria-hidden="true">·</span>
            <b>{FLOW[step]?.replaceAll("_", " ").toLowerCase()}</b>
          </p>
        </div>
      )}
    </article>
  );
}

function Orders() {
  const { user, logout } = useAuth();
  const isAuthenticated = useRequireAuth();
  const navigate = useNavigate();
  const ordersQuery = useOrders(isAuthenticated);

  if (!isAuthenticated) return null;

  const orders = ordersQuery.data ?? [];
  // Three groups, not two.
  //
  // PAYMENT_PENDING used to count as "in progress", so every abandoned
  // checkout became a pulsing live order the kitchen had never seen. One
  // seeded account had 34 of them ahead of its real ones. An order nobody
  // has paid for is not on its way; it is waiting for the customer.
  const unpaid = orders.filter((o) => o.status === "PAYMENT_PENDING" && o.payment_status !== "COD");
  const live = orders.filter(
    (o) =>
      !SETTLED.has(o.status) && !(o.status === "PAYMENT_PENDING" && o.payment_status !== "COD"),
  );
  const past = orders.filter((o) => SETTLED.has(o.status));

  return (
    <div className="page-pad mx-auto max-w-6xl pb-24 pt-10">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="font-display text-4xl font-black tracking-tight sm:text-5xl">
            Your orders
          </h1>
          {user && (
            <p className="mt-2 text-muted">
              Signed in as <span className="font-semibold text-foreground">{user.full_name}</span>
            </p>
          )}
        </div>
        <Button
          variant="outline"
          onClick={() => {
            logout();
            navigate({ to: "/" });
          }}
        >
          <LogOut />
          Log out
        </Button>
      </div>

      {ordersQuery.isLoading && (
        <div className="mt-10 grid gap-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="dish-placeholder placeholder-a h-40 animate-pulse rounded-xl" />
          ))}
        </div>
      )}

      {ordersQuery.isError && (
        <p className="elevated-panel mt-10 px-6 py-10 text-center text-muted">
          We couldn't load your orders right now.
        </p>
      )}

      {!ordersQuery.isLoading && !ordersQuery.isError && orders.length === 0 && (
        <div className="elevated-panel empty-state mt-10">
          <div className="empty-state-icon">
            <ReceiptText className="size-9" />
          </div>
          <h2 className="mt-8 font-display text-3xl font-black tracking-tight">No orders yet</h2>
          <p className="mx-auto mt-3 max-w-sm text-muted">
            Your order history will show up here once you place one.
          </p>
          <Button className="mt-8 h-12 px-6 text-base font-bold" asChild>
            <Link to="/menu">
              Browse the menu <ArrowRight className="size-4" />
            </Link>
          </Button>
        </div>
      )}

      {live.length > 0 && (
        <section className="mt-10">
          <h2 className="mb-4 flex items-center gap-2.5 font-display text-xl font-black tracking-tight">
            <span className="relative flex size-2.5">
              <span className="absolute inline-flex size-full animate-ping rounded-full bg-primary opacity-70" />
              <span className="relative inline-flex size-2.5 rounded-full bg-primary" />
            </span>
            In progress
            <span className="section-count">{live.length}</span>
          </h2>
          <div className="grid gap-4">
            {live.map((order, i) => (
              <OrderRow order={order} index={i} key={order.id} />
            ))}
          </div>
        </section>
      )}

      {unpaid.length > 0 && (
        <section className="mt-10">
          <h2 className="mb-2 flex items-center gap-2.5 font-display text-xl font-black tracking-tight">
            <WalletCards className="size-5 text-muted" />
            Not paid for
            <span className="section-count">{unpaid.length}</span>
          </h2>
          <p className="mb-4 text-sm text-muted">
            These never reached the kitchen because the payment wasn't completed. Nothing has been
            charged.
          </p>
          <div className="grid gap-4">
            {unpaid.map((order, i) => (
              <OrderRow order={order} index={i} key={order.id} />
            ))}
          </div>
        </section>
      )}

      {past.length > 0 && (
        <section className="mt-12">
          <h2 className="mb-4 flex items-center gap-2.5 font-display text-xl font-black tracking-tight">
            Past orders
            <span className="section-count">{past.length}</span>
          </h2>
          <div className="grid gap-4">
            {past.map((order, i) => (
              <OrderRow order={order} index={i} key={order.id} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
