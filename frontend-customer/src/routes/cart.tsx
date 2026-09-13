import { Link, createFileRoute } from "@tanstack/react-router";
import {
  ArrowRight,
  BadgePercent,
  Clock,
  Minus,
  Plus,
  ShieldCheck,
  ShoppingBag,
  Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { DishImage } from "@/components/bangkok/dish-image";
import { formatMoney } from "@/lib/bangkok-data";
import { useBangkokStore } from "@/lib/bangkok-store";
import { useAuth } from "@/lib/auth";

export const Route = createFileRoute("/cart")({
  head: () => ({
    meta: [
      { title: "Your Cart — Bangkok Bowl" },
      { name: "description", content: "Review your Bangkok Bowl order and continue to checkout." },
      { property: "og:title", content: "Your Cart — Bangkok Bowl" },
      { property: "og:description", content: "Review your Thai food order." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: CartPage,
});

function CartPage() {
  const s = useBangkokStore();
  // The cart itself is guest-visible; it lives in localStorage and belongs to
  // the browser, not the account. The account is only needed to place the order.
  const { isAuthenticated } = useAuth();

  const isDelivery = s.fulfillment === "DELIVERY";
  const delivery = isDelivery ? Number(s.currentLocation?.delivery_fee ?? 45) : 0;
  const tax = s.subtotal * 0.05;
  const total = s.subtotal + delivery + tax;

  // Both of these are real fields on the location — no invented delivery promises.
  const minimumOrder = Number(s.currentLocation?.minimum_order_amount ?? 0);
  const shortfall = Math.max(0, minimumOrder - s.subtotal);
  const progress = minimumOrder > 0 ? Math.min(100, (s.subtotal / minimumOrder) * 100) : 100;
  const eta = isDelivery
    ? s.currentLocation?.estimated_delivery_time
    : s.currentLocation?.estimated_pickup_time;

  if (!s.cart.length) {
    return (
      <div className="page-pad mx-auto max-w-3xl pb-28 pt-16">
        <div className="elevated-panel px-6 py-20 text-center">
          <div className="mx-auto grid size-20 place-items-center rounded-full bg-primary-soft">
            <ShoppingBag className="size-9 text-primary" />
          </div>
          <h1 className="mt-6 font-display text-3xl font-black sm:text-4xl">Your bowl is empty</h1>
          <p className="mx-auto mt-3 max-w-sm text-muted">
            Add a curry, a bowl of noodles or a snack to get started — or let the concierge pick for
            you.
          </p>
          <div className="mt-8 flex flex-wrap justify-center gap-3">
            <Button className="h-12 px-6" asChild>
              <Link to="/menu">Browse the menu</Link>
            </Button>
            <Button variant="outline" className="h-12 px-6" asChild>
              <Link to="/concierge">Ask the concierge</Link>
            </Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="page-pad mx-auto max-w-7xl pb-32 pt-10">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-4xl font-black sm:text-5xl">Your cart</h1>
          <p className="mt-2 text-muted">
            {s.totalItems} {s.totalItems === 1 ? "item" : "items"} from{" "}
            <span className="font-semibold text-foreground">
              {/* The cart's own restaurant, which is not always the app's:
                  the concierge answers across the whole marketplace. */}
              {s.cartRestaurantName ?? s.currentLocation?.branch_name ?? "your branch"}
            </span>
          </p>
        </div>
        <Link to="/menu" className="text-sm font-bold text-primary hover:underline">
          + Add more items
        </Link>
      </header>

      <div className="mt-8 grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_400px]">
        <section className="space-y-3">
          {s.cart.map((line, i) => (
            <article
              className="line-card elevated-panel rise-in grid grid-cols-[92px_minmax(0,1fr)] gap-4 p-3 sm:grid-cols-[120px_minmax(0,1fr)] sm:gap-5 sm:p-4"
              style={{ "--i": i } as React.CSSProperties}
              key={line.lineId}
            >
              <DishImage
                src={line.image_url}
                name={line.name}
                className="aspect-square rounded-xl"
              />
              <div className="flex min-w-0 flex-col justify-between gap-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h2 className="truncate font-display text-lg font-bold leading-tight">
                      {line.name}
                    </h2>
                    {(line.sizeName || line.addOnNames.length > 0) && (
                      <div className="mt-1.5 flex flex-wrap gap-1.5">
                        {line.sizeName && (
                          <span className="rounded-full bg-surface-alt px-2.5 py-0.5 text-xs font-semibold text-muted">
                            {line.sizeName}
                          </span>
                        )}
                        {line.addOnNames.map((name) => (
                          <span
                            className="rounded-full bg-surface-alt px-2.5 py-0.5 text-xs font-semibold text-muted"
                            key={name}
                          >
                            + {name}
                          </span>
                        ))}
                      </div>
                    )}
                    <p className="money mt-1.5 text-sm text-muted">
                      {formatMoney(line.unitPrice)} each
                    </p>
                  </div>
                  <b className="money shrink-0 text-lg">
                    {formatMoney(line.unitPrice * line.quantity)}
                  </b>
                </div>

                <div className="flex items-center justify-between gap-3">
                  <div className="qty-pill">
                    <button
                      type="button"
                      className="qty-step"
                      aria-label={`Reduce ${line.name}`}
                      disabled={line.quantity <= 1}
                      onClick={() => s.changeQuantity(line.lineId, -1)}
                    >
                      <Minus className="size-4" />
                    </button>
                    <span className="qty-value">{line.quantity}</span>
                    <button
                      type="button"
                      className="qty-step"
                      aria-label={`Add another ${line.name}`}
                      onClick={() => s.changeQuantity(line.lineId, 1)}
                    >
                      <Plus className="size-4" />
                    </button>
                  </div>
                  {/* Decrementing to zero was the only way to drop a line, which
                      meant six clicks to remove a quantity-six item. */}
                  <button
                    type="button"
                    className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1.5 text-sm font-semibold text-muted transition-colors hover:bg-danger/10 hover:text-danger"
                    aria-label={`Remove ${line.name}`}
                    onClick={() => s.changeQuantity(line.lineId, -line.quantity)}
                  >
                    <Trash2 className="size-4" />
                    <span className="hidden sm:inline">Remove</span>
                  </button>
                </div>
              </div>
            </article>
          ))}
        </section>

        <aside className="elevated-panel h-fit p-5 lg:sticky lg:top-24">
          <div className="segmented" data-active={s.fulfillment}>
            <span className="segmented-thumb" aria-hidden="true" />
            <button
              type="button"
              className="segmented-option"
              data-selected={isDelivery}
              onClick={() => s.setFulfillment("DELIVERY")}
            >
              Delivery
            </button>
            <button
              type="button"
              className="segmented-option"
              data-selected={!isDelivery}
              onClick={() => s.setFulfillment("PICKUP")}
            >
              Pickup
            </button>
          </div>

          {eta != null && eta !== "" && (
            <p className="mt-4 flex items-center gap-2 text-sm font-semibold">
              <Clock className="size-4 text-primary" />
              {isDelivery ? "Arrives in" : "Ready in"} about {eta}{" "}
              {typeof eta === "number" ? "min" : ""}
            </p>
          )}

          {shortfall > 0 && (
            <div className="mt-4 rounded-xl bg-primary-soft p-3">
              <p className="text-sm font-semibold">
                Add <b className="money">{formatMoney(shortfall)}</b> to reach the{" "}
                {formatMoney(minimumOrder)} minimum.
              </p>
              <div className="meter mt-2">
                <div className="meter-fill" style={{ width: `${progress}%` }} />
              </div>
            </div>
          )}

          <dl className="mt-5 space-y-2.5 text-sm">
            {[
              ["Subtotal", s.subtotal],
              [isDelivery ? "Delivery fee" : "Pickup", delivery],
              ["Tax", tax],
            ].map(([label, value]) => (
              <div className="flex justify-between" key={String(label)}>
                <dt className="text-muted">{label}</dt>
                <dd className="money font-semibold">
                  {Number(value) === 0 ? "Free" : formatMoney(Number(value))}
                </dd>
              </div>
            ))}
          </dl>

          <div className="total-row mt-4 flex items-end justify-between border-t border-border pt-4">
            <span className="text-lg font-black">Total</span>
            <span className="font-display text-3xl font-black">{formatMoney(total)}</span>
          </div>

          <Button
            className="mt-5 h-12 w-full text-base"
            disabled={shortfall > 0}
            asChild={shortfall === 0}
          >
            {shortfall > 0 ? (
              <span>Minimum {formatMoney(minimumOrder)} to order</span>
            ) : isAuthenticated ? (
              <Link to="/checkout">
                Continue to checkout <ArrowRight className="size-4" />
              </Link>
            ) : (
              <Link to="/login" search={{ redirect: "/checkout" }}>
                Sign in to checkout <ArrowRight className="size-4" />
              </Link>
            )}
          </Button>

          {!isAuthenticated && shortfall === 0 && (
            <p className="mt-3 text-center text-sm text-muted">
              Your cart is saved — signing in takes a moment.
            </p>
          )}

          <div className="mt-5 space-y-2 border-t border-border pt-4 text-sm text-muted">
            <p className="flex items-center gap-2">
              <ShieldCheck className="size-4 shrink-0 text-success" />
              Pay on delivery or pickup — no card needed now.
            </p>
            <p className="flex items-center gap-2">
              <BadgePercent className="size-4 shrink-0 text-primary" />
              Offers are applied at checkout.
            </p>
          </div>
        </aside>
      </div>
    </div>
  );
}
