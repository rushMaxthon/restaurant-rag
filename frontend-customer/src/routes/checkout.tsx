import { useState } from "react";
import { Link, createFileRoute } from "@tanstack/react-router";
import {
  AlertCircle,
  ArrowLeft,
  BadgeCheck,
  CreditCard,
  CheckCircle2,
  Clock,
  MapPin,
  Phone,
  ShieldCheck,
  Store,
  User,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { CardPayment } from "@/components/bangkok/card-payment";
import { DishImage } from "@/components/bangkok/dish-image";
import { formatMoney, orderCode } from "@/lib/bangkok-data";
import { useBangkokStore } from "@/lib/bangkok-store";
import { BranchHours } from "@/components/bangkok/branch-hours";
import {
  availabilityNow,
  bookableDays,
  bookableTimes,
  dayChipLabel,
  dayFromDate,
  dayLabel,
  formatTimeOfDay,
  nextOpening,
} from "@/lib/branch-hours";
import { useRequireAuth } from "@/lib/require-auth";
import { useCreateOrder, usePaymentConfig, useValidateOrder } from "@/lib/queries";
import { ApiError, api, type OrderCreateRequest } from "@/lib/api";

export const Route = createFileRoute("/checkout")({
  head: () => ({
    meta: [
      { title: "Checkout — Bangkok Bowl" },
      {
        name: "description",
        content: "Choose delivery or pickup and place your Bangkok Bowl order.",
      },
      { property: "og:title", content: "Checkout — Bangkok Bowl" },
      { property: "og:description", content: "Complete your Bangkok Bowl order." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: Checkout,
});

/** Cart → Checkout → Confirmation, rendered as a rail rather than a text label. */
function StepRail({ step }: { step: 1 | 2 | 3 }) {
  const steps = ["Cart", "Checkout", "Confirmation"] as const;
  return (
    <ol className="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm font-bold">
      {steps.map((label, i) => {
        const index = (i + 1) as 1 | 2 | 3;
        const done = index < step;
        const todo = index > step;
        return (
          <li className="flex items-center gap-3" key={label}>
            <span className="flex items-center gap-2">
              <span className="step-pill" data-done={done} data-todo={todo}>
                {done ? <CheckCircle2 className="size-4" /> : index}
              </span>
              <span className={todo ? "text-muted" : undefined}>{label}</span>
            </span>
            {index < 3 && <span className="h-px w-6 bg-border sm:w-10" aria-hidden="true" />}
          </li>
        );
      })}
    </ol>
  );
}

function Checkout() {
  const s = useBangkokStore();
  const isAuthenticated = useRequireAuth();
  const validateOrder = useValidateOrder();
  const createOrder = useCreateOrder();

  const [fullName, setFullName] = useState("");
  const [phone, setPhone] = useState("");
  const [address, setAddress] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [placedOrderId, setPlacedOrderId] = useState<string | null>(null);
  const [placedOrderNumber, setPlacedOrderNumber] = useState<string | null>(null);
  // Card only: this product does not take cash. The method still comes from
  // the server's `supported_methods` so an unconfigured Stripe shows as
  // "unavailable" rather than silently letting an order through unpaid.
  const [payingCard, setPayingCard] = useState(false);
  const [chosenSlot, setChosenSlot] = useState<Date | null>(null);
  const [chosenDay, setChosenDay] = useState<Date | null>(null);
  const [wantsLater, setWantsLater] = useState(false);
  // Pinned once per render pass so the day list, the slot list and the
  // validity check cannot disagree about what "now" is.
  const now = new Date();
  const method = "CARD" as const;
  // Set once the order and its intent exist; swaps the form for Stripe's
  // Payment Element. The cart is deliberately still full at this point — a
  // cancelled payment must leave the basket intact.
  const [pending, setPending] = useState<{
    orderId: string;
    orderNumber: string;
    clientSecret: string;
    publishableKey: string;
  } | null>(null);

  // Which methods this deployment can actually take. Card stays unavailable
  // until a Stripe key is configured, and saying so beats offering a button
  // that dead-ends.
  const paymentConfig = usePaymentConfig(isAuthenticated);
  const cardAvailable = Boolean(paymentConfig.data?.stripe_enabled);

  if (!isAuthenticated) return null;

  const branch = s.currentLocation;
  const isDelivery = s.fulfillment === "DELIVERY";
  const delivery = isDelivery ? Number(branch?.delivery_fee ?? 45) : 0;
  const tax = s.subtotal * 0.05;
  const total = s.subtotal + delivery + tax;
  const eta = isDelivery ? branch?.estimated_delivery_time : branch?.estimated_pickup_time;

  // Orders have carried schedule_type/scheduled_at since the beginning and the
  // server validates a scheduled time against the branch's own slots. The app
  // only ever sent ASAP, so outside opening hours there was nothing to do but
  // fail. Now a closed branch can still take an order for its next window.
  const fulfillment = isDelivery ? "DELIVERY" : "PICKUP";
  const availability = availabilityNow(branch, fulfillment);
  const reopens = availability.available ? null : nextOpening(branch, fulfillment);
  const canOrderNow = availability.available;

  // Scheduling is offered whether or not the branch is open. Closed, it is the
  // only way to order at all; open, it is someone ordering dinner from their
  // desk at 3pm. The days come from the branch's own `max_future_days`, and a
  // day with nothing left on it is left out rather than offered as a dead end.
  const days = bookableDays(branch, fulfillment, now);
  const selectedDay = chosenDay ?? days[0] ?? null;
  const slotTimes = selectedDay
    ? bookableTimes(branch, fulfillment, dayFromDate(selectedDay), selectedDay, now)
    : [];
  const mustSchedule = !canOrderNow;
  const scheduling = mustSchedule || wantsLater;

  // Once the intent exists the page becomes the payment sheet. Nothing else on
  // the checkout form can still change the amount at this point, so showing it
  // alongside an editable form would only invite a mismatch.
  if (pending) {
    return (
      <div className="page-pad mx-auto max-w-xl py-12">
        <div className="mt-4">
          <StepRail step={2} />
        </div>
        <h1 className="mt-5 font-display text-4xl font-black">Pay for your order</h1>
        <p className="mt-2 text-muted">
          Order {pending.orderNumber} is held for you. It reaches the kitchen once this payment
          clears.
        </p>
        <div className="elevated-panel mt-6 p-5 sm:p-6">
          <CardPayment
            publishableKey={pending.publishableKey}
            clientSecret={pending.clientSecret}
            amount={total}
            returnUrl={`${window.location.origin}/orders/${pending.orderId}`}
            onCancel={abandonPayment}
          />
        </div>
      </div>
    );
  }

  if (placedOrderId) {
    return (
      <div className="page-pad mx-auto max-w-2xl py-16">
        <div className="elevated-panel rise-in px-6 py-16 text-center">
          <div className="mx-auto grid size-24 place-items-center rounded-full bg-success/10">
            <CheckCircle2 className="size-12 text-success" />
          </div>
          <h1 className="mt-7 font-display text-4xl font-black sm:text-5xl">Order placed</h1>
          <p className="mt-4 text-lg text-muted">
            Your Thai feast is on its way. Track{" "}
            <b className="text-foreground">{placedOrderNumber ?? "your order"}</b> for live updates.
          </p>
          {eta != null && eta !== "" && (
            <p className="mt-3 flex items-center justify-center gap-2 font-semibold">
              <Clock className="size-4 text-primary" />
              {isDelivery ? "Arriving in" : "Ready in"} about {eta}{" "}
              {typeof eta === "number" ? "min" : ""}
            </p>
          )}
          <div className="mt-8 flex flex-wrap justify-center gap-3">
            <Button className="h-12 px-8 text-base" asChild>
              <Link to="/orders/$orderId" params={{ orderId: placedOrderId }}>
                Track order
              </Link>
            </Button>
            <Button variant="outline" className="h-12 px-8 text-base" asChild>
              <Link to="/menu">Order something else</Link>
            </Button>
          </div>
        </div>
      </div>
    );
  }

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);

    // Order against the cart's own restaurant. The concierge answers across the
    // whole marketplace, so a cart can legitimately hold another kitchen's dish
    // — sending it under the app's current branch failed validation with "One
    // or more menu items were not found for this restaurant".
    const orderRestaurantId = s.cartRestaurantId ?? s.restaurantId;
    const orderLocationId = s.cart[0]?.restaurantLocationId ?? s.branchId;
    if (!orderRestaurantId || !orderLocationId) {
      setError("We couldn't determine your branch. Please pick a branch and try again.");
      return;
    }
    const deliveryAddress =
      s.fulfillment === "DELIVERY" ? address : branch?.address_line_1 || address || "Pickup order";
    if (s.fulfillment === "DELIVERY" && deliveryAddress.trim().length < 5) {
      setError("Please enter a delivery address.");
      return;
    }

    const payload: OrderCreateRequest = {
      restaurant_id: orderRestaurantId,
      restaurant_location_id: orderLocationId,
      fulfillment_type: s.fulfillment,
      // ASAP while the branch is open; otherwise the slot they picked. The
      // server re-validates this against the same slot rows, so a stale page
      // cannot book a window that has since closed.
      ...(scheduling && chosenSlot
        ? { schedule_type: "SCHEDULED" as const, scheduled_at: chosenSlot.toISOString() }
        : {}),
      delivery_address: deliveryAddress,
      // Previously never sent, so the backend defaulted every order to COD and
      // marked it PLACED immediately — which is why "Place order" looked like
      // it skipped payment. A CARD order is created PAYMENT_PENDING instead and
      // waits for a verified webhook before it reaches the kitchen.
      payment_method: method,
      items: s.cart.map((line) => ({
        menu_item_id: line.itemId,
        menu_item_size_id: line.sizeId ?? null,
        selected_options: line.optionIds.map((id) => ({ option_id: id, quantity: 1 })),
        quantity: line.quantity,
      })),
    };

    try {
      await validateOrder.mutateAsync(payload);
      const order = await createOrder.mutateAsync(payload);

      // The order exists but is PAYMENT_PENDING, and stays out of the kitchen
      // queue until a verified webhook says the money moved. This step only
      // fetches the intent; the card itself is typed into Stripe's own iframe,
      // so no card data ever reaches this app or its server.
      setPayingCard(true);
      const intent = await api.createPaymentIntent(order.id);
      setPending({
        orderId: order.id,
        orderNumber: orderCode(order),
        clientSecret: intent.client_secret,
        publishableKey: intent.publishable_key,
      });
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "We couldn't place your order. Please try again.",
      );
    } finally {
      setPayingCard(false);
    }
  }

  /** Customer backed out of the payment sheet: the order stays retryable. */
  async function abandonPayment() {
    if (!pending) return;
    await api.cancelPayment(pending.orderId).catch(() => undefined);
    setPending(null);
  }

  const submitting = validateOrder.isPending || createOrder.isPending || payingCard;

  return (
    <form className="page-pad mx-auto max-w-7xl pb-40 pt-10" onSubmit={handleSubmit}>
      <Link
        to="/cart"
        className="inline-flex items-center gap-1.5 text-sm font-bold text-muted hover:text-foreground"
      >
        <ArrowLeft className="size-4" /> Back to cart
      </Link>
      <div className="mt-4">
        <StepRail step={2} />
      </div>
      <h1 className="mt-5 font-display text-4xl font-black sm:text-5xl">Checkout</h1>
      <p className="mt-2 text-lg text-muted">Almost there — just confirm where this is headed.</p>

      {error && (
        <div
          className="mt-6 flex items-start gap-2 rounded-xl border border-danger bg-danger/10 p-4 text-sm font-semibold text-danger"
          role="alert"
        >
          <AlertCircle className="mt-0.5 size-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <div className="mt-8 grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_420px]">
        <div className="space-y-5">
          <section className="elevated-panel p-5 sm:p-6">
            <h2 className="font-display text-xl font-black">
              Contact &amp; {isDelivery ? "delivery" : "pickup"}
            </h2>
            <p className="mt-1 text-sm text-muted">
              We use this to reach you if the rider needs directions.
            </p>

            <div className="mt-5 grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="full_name">Full name</Label>
                <div className="field-wrap">
                  <User className="size-4" />
                  <Input
                    id="full_name"
                    required
                    autoComplete="name"
                    placeholder="Your name"
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    className="h-12"
                  />
                </div>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="phone">Phone number</Label>
                <div className="field-wrap">
                  <Phone className="size-4" />
                  <Input
                    id="phone"
                    required
                    type="tel"
                    autoComplete="tel"
                    placeholder="10-digit mobile"
                    value={phone}
                    onChange={(e) => setPhone(e.target.value)}
                    className="h-12"
                  />
                </div>
              </div>
              {isDelivery && (
                <div className="space-y-1.5 sm:col-span-2">
                  <Label htmlFor="address">Delivery address</Label>
                  <div className="field-wrap">
                    <MapPin className="size-4" />
                    <Input
                      id="address"
                      required
                      autoComplete="street-address"
                      placeholder="Flat, street, area"
                      value={address}
                      onChange={(e) => setAddress(e.target.value)}
                      className="h-12"
                    />
                  </div>
                </div>
              )}
            </div>

            {!isDelivery && branch && (
              <div className="mt-5 flex items-start gap-3 rounded-xl bg-surface-alt p-4">
                <Store className="mt-0.5 size-5 shrink-0 text-primary" />
                <div>
                  <p className="font-bold">{branch.branch_name}</p>
                  <p className="text-sm text-muted">
                    {branch.address_line_1}, {branch.city}
                  </p>
                </div>
              </div>
            )}
          </section>

          <section className="elevated-panel p-5 sm:p-6">
            <h2 className="font-display text-xl font-black">When would you like it?</h2>

            {mustSchedule ? (
              <div className="closed-notice mt-4" data-tone="soft">
                <Clock className="mt-0.5 size-5 shrink-0 text-muted" />
                <div>
                  <p className="font-bold">
                    {isDelivery ? "Delivery" : "Pickup"} is closed right now
                  </p>
                  <p className="mt-0.5 text-sm text-muted">
                    {availability.reason ?? "This branch is outside its opening hours."} Pick a time
                    below and we'll have it ready then.
                  </p>
                </div>
              </div>
            ) : (
              // Offered even when the branch is open: ordering dinner from your
              // desk at 3pm is a normal thing to want, and the backend has
              // accepted a scheduled time since the beginning.
              <div className="segmented mt-4" data-active={wantsLater ? "PICKUP" : "DELIVERY"}>
                <span className="segmented-thumb" aria-hidden="true" />
                <button
                  type="button"
                  className="segmented-option"
                  data-selected={!wantsLater}
                  onClick={() => {
                    setWantsLater(false);
                    setChosenSlot(null);
                  }}
                >
                  As soon as possible
                </button>
                <button
                  type="button"
                  className="segmented-option"
                  data-selected={wantsLater}
                  onClick={() => setWantsLater(true)}
                >
                  Schedule for later
                </button>
              </div>
            )}

            {!scheduling && (
              <p className="mt-4 flex items-center gap-2 text-sm font-semibold">
                <Clock className="size-4 shrink-0 text-primary" />
                Ready in about {eta} {typeof eta === "number" ? "min" : ""}.
              </p>
            )}

            {scheduling &&
              (days.length === 0 ? (
                <p className="mt-4 text-sm text-muted">
                  This branch has no bookable times in the next {branch?.max_future_days ?? 0} days.
                  Try pickup, or another branch.
                </p>
              ) : (
                <>
                  {/* A day picker is only worth showing when there is more than
                      one day to pick; a single chip is furniture. */}
                  {days.length > 1 && (
                    <div className="mt-4">
                      <p className="text-xs font-black uppercase tracking-wide text-muted">Day</p>
                      <div className="day-rail mt-2">
                        {days.map((day) => (
                          <button
                            type="button"
                            key={day.toDateString()}
                            // Its own class, not `slot-chip`: a day and a time
                            // are different choices, and sharing one hook meant
                            // "pick the first chip" silently picked a day.
                            className="slot-chip day-chip"
                            data-on={selectedDay?.toDateString() === day.toDateString()}
                            onClick={() => {
                              setChosenDay(day);
                              setChosenSlot(null);
                            }}
                          >
                            {dayChipLabel(day, now)}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}

                  <div className="mt-4">
                    <p className="text-xs font-black uppercase tracking-wide text-muted">
                      {selectedDay ? dayChipLabel(selectedDay, now) : "Time"}
                    </p>
                    <div className="slot-grid mt-2">
                      {slotTimes.map((time) => (
                        <button
                          type="button"
                          key={time.toISOString()}
                          className="slot-chip"
                          data-on={chosenSlot?.toISOString() === time.toISOString()}
                          onClick={() => setChosenSlot(time)}
                        >
                          {formatTimeOfDay(time)}
                        </button>
                      ))}
                    </div>
                    {/* No lowercasing and no trailing period: lowercasing turned
                        "Thu, Sep 17" into "thu, sep 17", and the formatted time
                        already ends in one ("7:00 p.m.."). */}
                    {chosenSlot && (
                      <p className="mt-3 text-sm font-semibold text-success">
                        Arriving {dayChipLabel(chosenSlot, now)} at {formatTimeOfDay(chosenSlot)}
                      </p>
                    )}
                  </div>
                </>
              ))}

            <BranchHours
              location={branch}
              fulfillment={fulfillment}
              className="mt-6 border-t border-border pt-5"
            />
          </section>

          <section className="elevated-panel p-5 sm:p-6">
            <h2 className="font-display text-xl font-black">Payment</h2>
            <p className="mt-1 text-sm text-muted">
              Paid securely by card before your order reaches the kitchen.
            </p>

            <div className="mt-4 pay-option" data-on={cardAvailable}>
              <CreditCard className="size-5 shrink-0 text-primary" />
              <span className="min-w-0 flex-1">
                <span className="block font-bold">Pay by card</span>
                <span className="block text-sm text-muted">
                  Visa, Mastercard and Amex, handled by Stripe.
                </span>
              </span>
              {cardAvailable && <BadgeCheck className="size-5 shrink-0 text-primary" />}
            </div>

            {!cardAvailable && (
              <div
                className="mt-3 flex items-start gap-2 rounded-xl border border-danger bg-danger/10 p-3 text-sm font-semibold text-danger"
                role="alert"
              >
                <AlertCircle className="mt-0.5 size-4 shrink-0" />
                <span>
                  Card payments aren't switched on for this restaurant yet, so orders can't be
                  placed. Please try again shortly.
                </span>
              </div>
            )}

            <p className="mt-3 flex items-center gap-2 text-sm text-muted">
              <ShieldCheck className="size-4 shrink-0 text-success" />
              Your card details go straight to Stripe — this app never sees them.
            </p>
          </section>
        </div>

        <aside className="elevated-panel h-fit p-5 lg:sticky lg:top-24">
          <h2 className="font-display text-xl font-black">Your order</h2>
          <p className="mt-1 flex items-center gap-1.5 text-sm text-muted">
            <MapPin className="size-3.5 shrink-0 text-primary" />
            {isDelivery ? "Delivery" : "Pickup"} from {branch?.branch_name ?? "your branch"}
          </p>
          {eta != null && eta !== "" && (
            <p className="mt-1.5 flex items-center gap-1.5 text-sm font-semibold">
              <Clock className="size-3.5 shrink-0 text-primary" />
              About {eta} {typeof eta === "number" ? "min" : ""}
            </p>
          )}

          <div className="mt-5 space-y-3 border-b border-border pb-5">
            {s.cart.map((line, i) => (
              <div
                className="rise-in flex items-center gap-3"
                style={{ "--i": i } as React.CSSProperties}
                key={line.lineId}
              >
                <DishImage
                  src={line.image_url}
                  name={line.name}
                  className="size-14 shrink-0 rounded-lg"
                />
                <div className="min-w-0 flex-1">
                  <p className="truncate font-semibold">{line.name}</p>
                  <p className="money text-sm text-muted">
                    {line.quantity} × {formatMoney(line.unitPrice)}
                  </p>
                </div>
                <span className="money shrink-0 font-bold">
                  {formatMoney(line.unitPrice * line.quantity)}
                </span>
              </div>
            ))}
          </div>

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
            className="mt-5 hidden h-12 w-full text-base lg:flex"
            disabled={
              !s.cart.length || submitting || !cardAvailable || (!canOrderNow && !chosenSlot)
            }
            type="submit"
          >
            {submitting
              ? payingCard
                ? "Opening payment…"
                : "Preparing your order…"
              : `Pay ${formatMoney(total)}`}
          </Button>
        </aside>
      </div>

      {/* Kept for narrow screens, where the summary card scrolls out of reach. */}
      {/* z-40, matching the bottom nav. At z-30 the checkout content painted
          over this bar on a phone — Playwright found the day and time chips
          intercepting clicks meant for "Pay now", which means a real thumb
          would have hit them too. z-40 was not enough: the content grid wins at
          equal depth. Above the nav (z-40), below the header (z-50), and the
          two bars never overlap anyway — this sits at 58px, the nav at 0. */}
      <div className="fixed inset-x-0 bottom-[58px] z-[45] border-t border-border bg-surface/95 p-3 backdrop-blur lg:hidden">
        <div className="mx-auto flex max-w-2xl items-center gap-3">
          <div className="min-w-0">
            <p className="text-xs font-bold text-muted">
              {s.totalItems} {s.totalItems === 1 ? "item" : "items"}
            </p>
            <p className="money font-display text-xl font-black leading-tight">
              {formatMoney(total)}
            </p>
          </div>
          <Button
            className="h-13 flex-1 text-base"
            disabled={
              !s.cart.length || submitting || !cardAvailable || (!canOrderNow && !chosenSlot)
            }
            type="submit"
          >
            {submitting ? "Working…" : "Pay now"}
          </Button>
        </div>
      </div>
    </form>
  );
}
