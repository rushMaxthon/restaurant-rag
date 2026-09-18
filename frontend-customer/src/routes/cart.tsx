import { Link, createFileRoute } from "@tanstack/react-router";
import {
  ArrowRight,
  BadgePercent,
  ChevronDown,
  Clock,
  Minus,
  Plus,
  ShieldCheck,
  ShoppingBag,
  Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { DishImage } from "@/components/bangkok/dish-image";
import { WaiterPrompt } from "@/components/bangkok/waiter-prompt";

import { useBangkokStore } from "@/lib/bangkok-store";
import { chosenLabels } from "@/lib/customization";
import { BranchHours } from "@/components/bangkok/branch-hours";
import {
  availabilityNow,
  etaClockTime,
  bookableDays,
  dayLabel,
  formatSlotTime,
  nextOpening,
} from "@/lib/branch-hours";
import { useAuth } from "@/lib/auth";
import { pageMeta, useMoney } from "@/lib/storefront";
import { getStorefrontCopy } from "@/lib/storefront.server";

export const Route = createFileRoute("/cart")({
  loader: () => getStorefrontCopy(),
  head: ({ loaderData }) => ({
    meta: pageMeta(loaderData, "Your cart", "Review your order and continue to checkout."),
  }),
  component: CartPage,
});

function CartPage() {
  // Prices in whatever this restaurant charges in.
  const money = useMoney();
  const s = useBangkokStore();
  // The cart itself is guest-visible; it lives in localStorage and belongs to
  // the browser, not the account. The account is only needed to place the order.
  const { isAuthenticated } = useAuth();

  const isDelivery = s.fulfillment === "DELIVERY";
  // Falls back to 0, not 45. The branch's real fee is around three dollars, so
  // while it loaded the summary announced a $45.00 delivery charge and a total
  // to match — the single most alarming number the app could invent.
  const delivery = isDelivery ? Number(s.orderLocation?.delivery_fee ?? 0) : 0;
  const tax = s.subtotal * 0.05;
  const total = s.subtotal + delivery + tax;

  // Both of these are real fields on the location — no invented delivery promises.
  const minimumOrder = Number(s.orderLocation?.minimum_order_amount ?? 0);
  const shortfall = Math.max(0, minimumOrder - s.subtotal);
  const progress = minimumOrder > 0 ? Math.min(100, (s.subtotal / minimumOrder) * 100) : 100;
  const eta = isDelivery
    ? s.orderLocation?.estimated_delivery_time
    : s.orderLocation?.estimated_pickup_time;

  // The API has always said whether this branch can take the order right now.
  // Nothing read it, so at 11pm you could fill a cart, reach checkout and only
  // then be told the branch was closed. Said here instead, where the decision
  // to continue is actually made.
  const fulfillment = isDelivery ? "DELIVERY" : "PICKUP";
  // The branch's clock; see the note in checkout.tsx.
  const tz = s.timeZone;
  // The clock time the ETA lands on, on the branch's clock.
  const etaAt = etaClockTime(eta, new Date(), tz);
  const availability = availabilityNow(s.orderLocation, fulfillment, new Date(), tz);
  const reopens = availability.available
    ? null
    : nextOpening(s.orderLocation, fulfillment, new Date(), tz);
  const blocked = !availability.available;

  // Closed is not the same as unorderable. The server has always accepted a
  // scheduled order, and checkout has offered one since the slot picker landed
  // — but the cart still ended the journey with a disabled button, so nobody
  // ever reached it. A branch with a bookable window ahead of it gets a way
  // through; one with no windows at all keeps the honest dead end.
  const canSchedule =
    blocked && bookableDays(s.orderLocation, fulfillment, new Date(), tz).length > 0;

  // "Closed" and "we have not loaded the branch yet" are different things, and
  // availabilityNow(undefined) returns the first for the second. Until the
  // restaurant arrives the honest answer is that we do not know yet.
  const loadingBranch = s.isRestaurantLoading || !s.orderLocation;

  if (!s.cart.length) {
    return (
      <div className="page-pad mx-auto max-w-3xl pb-28 pt-16">
        <div className="elevated-panel empty-state">
          <div className="empty-state-icon">
            <ShoppingBag className="size-9" />
          </div>
          <h1 className="mt-8 font-display text-3xl font-extrabold tracking-tight sm:text-4xl">
            Your bowl is empty
          </h1>
          <p className="mx-auto mt-3 max-w-sm text-muted">
            Add a curry, a bowl of noodles or a snack to get started — or let the concierge pick for
            you.
          </p>
          <div className="mt-8 flex flex-wrap justify-center gap-3">
            <Button className="h-12 px-6 text-base font-bold" asChild>
              <Link to="/menu">
                Browse the menu <ArrowRight className="size-4" />
              </Link>
            </Button>
            <Button variant="outline" className="h-12 px-6 text-base font-bold" asChild>
              <Link to="/concierge">Ask the concierge</Link>
            </Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="page-pad mx-auto max-w-7xl pb-32 pt-10">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="font-display text-4xl font-extrabold tracking-tight sm:text-5xl">Your cart</h1>
          <p className="mt-2 text-muted">
            {s.totalItems} {s.totalItems === 1 ? "item" : "items"} from{" "}
            <span className="font-semibold text-foreground">
              {/* The cart's own restaurant, which is not always the app's:
                  the concierge answers across the whole marketplace. */}
              {s.cartRestaurantName ?? s.orderLocation?.branch_name ?? "your branch"}
            </span>
          </p>
        </div>
        <Button variant="outline" className="font-bold" asChild>
          <Link to="/menu">
            <Plus className="size-4" />
            Add more items
          </Link>
        </Button>
      </header>

      <WaiterPrompt placement="cart" />

      <div className="mt-8 grid items-start gap-6 grid-cols-[minmax(0,1fr)] lg:grid-cols-[minmax(0,1fr)_400px]">
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
                className="aspect-square rounded-xl text-xl ring-1 ring-border sm:text-2xl"
              />
              <div className="flex min-w-0 flex-col justify-between gap-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h2 className="truncate font-display text-lg font-bold leading-tight tracking-tight">
                      {line.name}
                    </h2>
                    {(line.sizeName || line.addOnNames.length > 0) && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {line.sizeName && <span className="tag-chip">{line.sizeName}</span>}
                        {/* With the half named, because "half pepperoni, half
                            mushroom" and "both all over" are different pizzas
                            at different prices and read identically without
                            it. */}
                        {chosenLabels(line.optionIds, line.addOnNames, line.optionPortions).map(
                          (label) => (
                            <span className="tag-chip" key={label}>
                              + {label}
                            </span>
                          ),
                        )}
                      </div>
                    )}
                    <p className="money mt-2 text-sm text-muted">
                      {money(line.unitPrice)} each
                    </p>
                  </div>
                  <b className="money shrink-0 text-lg font-extrabold leading-tight">
                    {money(line.unitPrice * line.quantity)}
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
                    className="remove-btn"
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

        <aside className="elevated-panel h-fit p-5 sm:p-6 lg:sticky lg:top-24">
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
              <Clock className="size-4 shrink-0 text-primary" />
              {isDelivery ? "Arrives in" : "Ready in"} about {eta}{" "}
              {typeof eta === "number" ? "min" : ""}
              {/* The clock time as well as the duration. "about 29 min" asks
                  someone to do arithmetic at the moment they are deciding
                  whether to order. */}
              {etaAt && <span className="text-muted">· by {etaAt}</span>}
            </p>
          )}

          {shortfall > 0 && (
            <div className="mt-4 rounded-xl bg-primary-soft p-3.5">
              <p className="text-sm font-semibold leading-snug">
                Add <b className="money">{money(shortfall)}</b> to reach the{" "}
                {money(minimumOrder)} minimum.
              </p>
              <div className="meter mt-2.5">
                <div className="meter-fill" style={{ width: `${progress}%` }} />
              </div>
            </div>
          )}

          <dl className="mt-6 space-y-2.5 text-sm">
            {[
              ["Subtotal", s.subtotal],
              [isDelivery ? "Delivery fee" : "Pickup", delivery],
              ["Tax", tax],
            ].map(([label, value]) => (
              <div className="sum-row" key={String(label)}>
                <dt>{label}</dt>
                <dd>{Number(value) === 0 ? "Free" : money(Number(value))}</dd>
              </div>
            ))}
          </dl>

          <div className="sum-total">
            <span className="text-lg font-extrabold">Total</span>
            <span className="sum-total-figure">{money(total)}</span>
          </div>

          {blocked && !loadingBranch && (
            <div className="closed-notice mt-5" data-tone="soft">
              <Clock className="mt-0.5 size-5 shrink-0 text-primary" />
              <div className="min-w-0">
                <p className="font-bold">
                  {isDelivery ? "Delivery" : "Pickup"} is closed right now
                </p>
                <p className="mt-0.5 text-sm text-muted">
                  {availability.reason ?? "This branch is outside its opening hours."}
                  {reopens && (
                    <>
                      {" "}
                      It opens again {reopens.isToday ? "today" : dayLabel(reopens.day)} at{" "}
                      <b className="text-foreground">{formatSlotTime(reopens.slot.start_time)}</b>.
                    </>
                  )}
                </p>
                {canSchedule && (
                  <p className="mt-2 text-sm font-semibold text-foreground">
                    You can still order now and choose when you want it.
                  </p>
                )}
                <details className="hours-disclosure mt-3">
                  <summary>
                    See opening hours
                    <ChevronDown className="size-3.5" />
                  </summary>
                  <BranchHours
                    className="mt-3"
                    location={s.orderLocation}
                    fulfillment={fulfillment}
                  />
                </details>
              </div>
            </div>
          )}

          <Button
            className="mt-5 h-12 w-full text-base font-bold"
            disabled={loadingBranch || shortfall > 0 || (blocked && !canSchedule)}
            asChild={!loadingBranch && shortfall === 0 && !(blocked && !canSchedule)}
          >
            {loadingBranch ? (
              <span>Checking the kitchen…</span>
            ) : blocked && !canSchedule ? (
              <span>Closed right now</span>
            ) : shortfall > 0 ? (
              <span>Minimum {money(minimumOrder)} to order</span>
            ) : isAuthenticated ? (
              <Link to="/checkout">
                {canSchedule ? "Schedule for later" : "Continue to checkout"}{" "}
                <ArrowRight className="size-4" />
              </Link>
            ) : (
              <Link to="/login" search={{ redirect: "/checkout" }}>
                {canSchedule ? "Sign in to schedule" : "Sign in to checkout"}{" "}
                <ArrowRight className="size-4" />
              </Link>
            )}
          </Button>

          {!isAuthenticated && shortfall === 0 && (
            <p className="mt-3 text-center text-sm text-muted">
              Your cart is saved — signing in takes a moment.
            </p>
          )}

          <div className="mt-5 space-y-2.5 border-t border-border pt-4">
            {/* Said "pay on delivery — no card needed now" for as long as COD
                existed. It does not any more, and a cart promising cash before
                a card-only checkout is the kind of small lie people notice. */}
            <p className="sum-note" data-tone="success">
              <ShieldCheck className="size-4" />
              Card payment is handled by Stripe — we never see your details.
            </p>
            <p className="sum-note">
              <BadgePercent className="size-4" />
              Offers are applied at checkout.
            </p>
          </div>
        </aside>
      </div>
    </div>
  );
}
