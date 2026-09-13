import { useState } from "react";
import { Link, createFileRoute } from "@tanstack/react-router";
import {
  AlertCircle,
  ArrowLeft,
  BadgeCheck,
  CheckCircle2,
  Clock,
  MapPin,
  Phone,
  ShieldCheck,
  Store,
  User,
  Wallet,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { DishImage } from "@/components/bangkok/dish-image";
import { formatINR, orderCode } from "@/lib/bangkok-data";
import { useBangkokStore } from "@/lib/bangkok-store";
import { useRequireAuth } from "@/lib/require-auth";
import { useCreateOrder, useValidateOrder } from "@/lib/queries";
import { ApiError, type OrderCreateRequest } from "@/lib/api";

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

  if (!isAuthenticated) return null;

  const branch = s.currentLocation;
  const isDelivery = s.fulfillment === "DELIVERY";
  const delivery = isDelivery ? Number(branch?.delivery_fee ?? 45) : 0;
  const tax = s.subtotal * 0.05;
  const total = s.subtotal + delivery + tax;
  const eta = isDelivery ? branch?.estimated_delivery_time : branch?.estimated_pickup_time;

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

    if (!s.restaurantId || !s.branchId) {
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
      restaurant_id: s.restaurantId,
      restaurant_location_id: s.branchId,
      fulfillment_type: s.fulfillment,
      delivery_address: deliveryAddress,
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
      s.clearCart();
      setPlacedOrderId(order.id);
      setPlacedOrderNumber(orderCode(order));
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "We couldn't place your order. Please try again.",
      );
    }
  }

  const submitting = validateOrder.isPending || createOrder.isPending;

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
            <h2 className="font-display text-xl font-black">Payment</h2>
            {/* Card payment exists in the backend but has no key configured, so
                offering it here would be a dead end. Only COD is shown. */}
            <div className="mt-4 flex items-center gap-3 rounded-xl border-2 border-primary bg-primary-soft p-4">
              <Wallet className="size-5 shrink-0 text-primary" />
              <div className="flex-1">
                <p className="font-bold">Pay on {isDelivery ? "delivery" : "pickup"}</p>
                <p className="text-sm text-muted">Cash or UPI when your order arrives.</p>
              </div>
              <BadgeCheck className="size-5 shrink-0 text-primary" />
            </div>
            <p className="mt-3 flex items-center gap-2 text-sm text-muted">
              <ShieldCheck className="size-4 shrink-0 text-success" />
              No card details are collected now.
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
                    {line.quantity} × {formatINR(line.unitPrice)}
                  </p>
                </div>
                <span className="money shrink-0 font-bold">
                  {formatINR(line.unitPrice * line.quantity)}
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
                  {Number(value) === 0 ? "Free" : formatINR(Number(value))}
                </dd>
              </div>
            ))}
          </dl>

          <div className="total-row mt-4 flex items-end justify-between border-t border-border pt-4">
            <span className="text-lg font-black">Total</span>
            <span className="font-display text-3xl font-black">{formatINR(total)}</span>
          </div>

          <Button
            className="mt-5 hidden h-12 w-full text-base lg:flex"
            disabled={!s.cart.length || submitting}
            type="submit"
          >
            {submitting ? "Placing order…" : `Place order · ${formatINR(total)}`}
          </Button>
        </aside>
      </div>

      {/* Kept for narrow screens, where the summary card scrolls out of reach. */}
      <div className="fixed inset-x-0 bottom-[58px] z-30 border-t border-border bg-surface/95 p-3 backdrop-blur lg:hidden">
        <div className="mx-auto flex max-w-2xl items-center gap-3">
          <div className="min-w-0">
            <p className="text-xs font-bold text-muted">
              {s.totalItems} {s.totalItems === 1 ? "item" : "items"}
            </p>
            <p className="money font-display text-xl font-black leading-tight">
              {formatINR(total)}
            </p>
          </div>
          <Button
            className="h-13 flex-1 text-base"
            disabled={!s.cart.length || submitting}
            type="submit"
          >
            {submitting ? "Placing order…" : "Place order"}
          </Button>
        </div>
      </div>
    </form>
  );
}
