import { useEffect, useRef, useState } from "react";
import { Link, createFileRoute } from "@tanstack/react-router";
import {
  AlertCircle,
  ArrowLeft,
  BadgeCheck,
  CalendarDays,
  CreditCard,
  CheckCircle2,
  Clock,
  MapPin,
  Phone,
  ShieldCheck,
  Store,
  TicketPercent,
  Zap,
  User,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { CardPayment } from "@/components/bangkok/card-payment";
import { DishImage } from "@/components/bangkok/dish-image";
import { formatMoney, orderCode } from "@/lib/bangkok-data";
import { useBangkokStore } from "@/lib/bangkok-store";
import {
  activeSlots,
  availabilityNow,
  bookableDays,
  bookableTimes,
  dateInputValue,
  dayChipLabel,
  dayFromDate,
  dayFromInputValue,
  dayLabel,
  etaClockTime,
  formatSlotRange,
  formatTimeOfDay,
  groupByPartOfDay,
  isSameDay,
  lastBookableDay,
  nextBookableTime,
  nextOpening,
} from "@/lib/branch-hours";
import { chosenLabels } from "@/lib/customization";
import {
  addressFromSaved,
  composeDeliveryAddress,
  isSameAddress,
  formatPhoneAsTyped,
  looseAddressFields,
  validateAddress,
  validatePhone,
  type AddressFields,
} from "@/lib/delivery-address";
import { useRequireAuth } from "@/lib/require-auth";
import { useCreateOrder, usePaymentConfig, useProfile, useValidateOrder } from "@/lib/queries";
import { ApiError, api, type OrderCreateRequest } from "@/lib/api";
import { refusalNeedsCart } from "@/lib/order-refusal";

/** Shown beside the phone field; matches the backend's own default. */
const PHONE_COUNTRY_CODE = "+1";

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

/**
 * One labelled, validated address box.
 *
 * Declared at module scope on purpose. Defined inside Checkout it would be a
 * NEW component type on every render, so React would unmount and remount the
 * input on each keystroke — focus lost, and only the first character kept.
 * Everything it needs arrives as props instead.
 */
function AddressField({
  id,
  label,
  placeholder,
  autoComplete,
  hint,
  className,
  icon,
  inputMode,
  value,
  problem,
  onChange,
  onBlur,
}: {
  id: keyof AddressFields;
  label: string;
  placeholder: string;
  autoComplete: string;
  hint?: string;
  className?: string;
  icon?: React.ReactNode;
  inputMode?: "text" | "numeric" | "tel";
  value: string;
  problem?: string | undefined;
  onChange: (next: string) => void;
  onBlur: () => void;
}) {
  return (
    <div className={`space-y-1.5 ${className ?? ""}`}>
      <Label htmlFor={id}>
        {label}
        {hint && <span className="ml-1.5 text-xs font-medium text-muted">{hint}</span>}
      </Label>
      <div className="field-wrap" data-invalid={Boolean(problem)}>
        {icon}
        <Input
          id={id}
          value={value}
          placeholder={placeholder}
          autoComplete={autoComplete}
          {...(inputMode ? { inputMode } : {})}
          onChange={(e) => onChange(e.target.value)}
          onBlur={onBlur}
          aria-invalid={Boolean(problem)}
          aria-describedby={problem ? `${id}-error` : undefined}
          className="h-12"
        />
      </div>
      {problem && (
        <p className="field-error" id={`${id}-error`}>
          {problem}
        </p>
      )}
    </div>
  );
}

function Checkout() {
  const s = useBangkokStore();
  const isAuthenticated = useRequireAuth();
  const validateOrder = useValidateOrder();
  const createOrder = useCreateOrder();

  const [fullName, setFullName] = useState("");
  const [phone, setPhone] = useState("");
  // Optional, and deliberately not validated here: an unrecognised code is
  // not an error the customer should be stopped for. It buys nothing, so a
  // typo costs them nothing — it only means one post goes uncredited.
  const [promoCode, setPromoCode] = useState("");
  const [address, setAddress] = useState<AddressFields>({
    line1: "",
    line2: "",
    landmark: "",
    city: "",
    state: "",
    zip: "",
  });
  // Errors appear once a field has been left, not while it is being typed in.
  // Marking a half-typed ZIP wrong is the fastest way to make a form feel
  // hostile; saying nothing until submit is the slowest way to fix it.
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Whether that error is one the cart can fix. See placeOrder.
  const [errorNeedsCart, setErrorNeedsCart] = useState(false);
  const [placedOrderId, setPlacedOrderId] = useState<string | null>(null);
  const [placedOrderNumber, setPlacedOrderNumber] = useState<string | null>(null);
  // Card only: this product does not take cash. The method still comes from
  // the server's `supported_methods` so an unconfigured Stripe shows as
  // "unavailable" rather than silently letting an order through unpaid.
  const [payingCard, setPayingCard] = useState(false);
  const [chosenSlot, setChosenSlot] = useState<Date | null>(null);
  const [chosenDay, setChosenDay] = useState<Date | null>(null);
  const [wantsLater, setWantsLater] = useState(false);
  // Which saved address is in the form, so a customer with a home and a work
  // address can switch between them.
  const [addressId, setAddressId] = useState<string | null>(null);
  const [saveAddress, setSaveAddress] = useState(true);
  // Whether anything was actually filled in from the account. A ref cannot
  // answer this for rendering, because changing one does not cause a render.
  const [filledFromAccount, setFilledFromAccount] = useState(false);

  // What we already know about whoever is signed in. The account carries a
  // name, a number and, for anyone who has saved one, a full address — and
  // checkout used to ask for all of it again every single time.
  const profile = useProfile(isAuthenticated);
  const savedAddresses = profile.data?.saved_addresses ?? [];
  // Filled once. After that the form belongs to the customer: a late-arriving
  // request must never reach in and rewrite what they are part way through
  // typing.
  const prefilled = useRef(false);

  useEffect(() => {
    const account = profile.data?.user;
    if (!account || prefilled.current) return;
    prefilled.current = true;

    if (account.full_name) {
      setFullName(account.full_name);
      setFilledFromAccount(true);
    }

    const preferred = savedAddresses.find((entry) => entry.is_default) ?? savedAddresses[0] ?? null;
    // The address's own number first: it is the one attached to the door the
    // rider is going to.
    const number = preferred?.phone_number ?? account.phone_number;
    if (number) {
      setPhone(formatPhoneAsTyped(number));
      setFilledFromAccount(true);
    }

    if (preferred) {
      setAddress(addressFromSaved(preferred));
      setAddressId(preferred.id);
      setSaveAddress(false);
      setFilledFromAccount(true);
    } else if (account.default_address) {
      setAddress(looseAddressFields(account.default_address));
      setFilledFromAccount(true);
    }
  }, [profile.data, savedAddresses]);

  /** Put a saved address in the form, replacing whatever is there. */
  const useSavedAddress = (id: string) => {
    const picked = savedAddresses.find((entry) => entry.id === id);
    if (!picked) return;
    setAddress(addressFromSaved(picked));
    setAddressId(id);
    setSaveAddress(false);
    if (picked.phone_number) setPhone(formatPhoneAsTyped(picked.phone_number));
    // The new address has not been looked at yet, so nothing about it is
    // "wrong" until the customer has had a chance to read it.
    setTouched((t) => ({ ...t, line1: false, city: false, state: false, zip: false }));
  };
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
  // Three different situations, not two. While the config is in flight, and if
  // the request fails, `stripe_enabled` is falsy too — and the page used to
  // blame the restaurant for both, in red, on every single load.
  const paymentConfigPending = paymentConfig.isPending;
  const paymentConfigFailed = paymentConfig.isError;

  if (!isAuthenticated) return null;

  // The branch the ORDER names, not the one the picker is showing. Slot rules,
  // the delivery fee and the minimum are all per location, and the order is
  // placed against the cart's location a few lines below.
  const branch = s.orderLocation;
  // Every opening hour, slot and cutoff below is on the RESTAURANT's clock,
  // not the device's. Undefined until /app-config lands, which the helpers
  // read as "use the device zone" — the old behaviour, and harmless.
  const tz = s.timeZone;
  const isDelivery = s.fulfillment === "DELIVERY";
  // 0, not 45 — see the note in cart.tsx. An invented $45 delivery fee is
  // the worst thing to show someone one second before they pay.
  const delivery = isDelivery ? Number(branch?.delivery_fee ?? 0) : 0;
  const tax = s.subtotal * 0.05;
  const total = s.subtotal + delivery + tax;
  const eta = isDelivery ? branch?.estimated_delivery_time : branch?.estimated_pickup_time;
  // The clock time that ETA lands on, on the branch's clock.
  const etaAt = etaClockTime(eta, now, tz);

  // Validation lives in lib/delivery-address.ts so the form and the submit
  // handler cannot disagree about what "valid" means.
  const addressProblems = isDelivery ? validateAddress(address) : {};
  const phoneProblem = validatePhone(phone);
  const nameProblem = fullName.trim() ? null : "Enter the name for this order.";
  const contactReady = !phoneProblem && !nameProblem && Object.keys(addressProblems).length === 0;
  // Shown once the field has been left, or once submit has been attempted.
  /**
   * Change one part of the address.
   *
   * Editing a saved address means the form no longer holds THAT address, so
   * the chip stops claiming it does and the save box comes back — otherwise a
   * corrected flat number would be typed, sent, and forgotten by the next
   * order.
   */
  const editAddress = (part: keyof AddressFields, next: string) => {
    setAddress((a) => ({ ...a, [part]: next }));
    if (addressId) {
      setAddressId(null);
      setSaveAddress(true);
    }
  };

  const show = (field: keyof AddressFields | "phone" | "name") =>
    Boolean(touched[field] || submitted);

  // Orders have carried schedule_type/scheduled_at since the beginning and the
  // server validates a scheduled time against the branch's own slots. The app
  // only ever sent ASAP, so outside opening hours there was nothing to do but
  // fail. Now a closed branch can still take an order for its next window.
  const fulfillment = isDelivery ? "DELIVERY" : "PICKUP";
  const availability = availabilityNow(branch, fulfillment, now, tz);
  const reopens = availability.available ? null : nextOpening(branch, fulfillment, now, tz);
  const canOrderNow = availability.available;

  // Scheduling is offered whether or not the branch is open. Closed, it is the
  // only way to order at all; open, it is someone ordering dinner from their
  // desk at 3pm. The days come from the branch's own `max_future_days`, and a
  // day with nothing left on it is left out rather than offered as a dead end.
  const days = bookableDays(branch, fulfillment, now, tz);
  const selectedDay = chosenDay ?? days[0] ?? null;
  const slotTimes = selectedDay
    ? bookableTimes(branch, fulfillment, dayFromDate(selectedDay, tz), selectedDay, now, tz)
    : [];
  const mustSchedule = !canOrderNow;
  const scheduling = mustSchedule || wantsLater;
  // Submitting is gated on `scheduling && !chosenSlot`, not on the branch
  // being shut. Someone who switched an OPEN branch to "Schedule for later"
  // and picked no time could still press Pay, and the payload quietly fell
  // back to ASAP — they asked for later and got now.

  // A week of chips is enough for "tomorrow evening" and useless for "the 24th".
  // The date input covers the rest of the horizon without a second widget to
  // build — and it is the control people already know how to use on a phone,
  // where it opens the platform's own date wheel.
  const firstDay = days[0];
  const lastDay = lastBookableDay(branch, now, tz);

  const todaysWindows = selectedDay
    ? activeSlots(branch, fulfillment).filter((w) => w.day_of_week === dayFromDate(selectedDay, tz))
    : [];

  // A date the branch does not serve is worth saying out loud. Silently
  // snapping back to a day the customer did not pick is how you end up with an
  // order for the wrong evening.
  const pickedEmptyDay =
    selectedDay && slotTimes.length === 0 ? dayChipLabel(selectedDay, now, tz) : null;

  // The soonest the kitchen can actually have it. Offered as one tap, because
  // it is what most people scheduling ahead actually want, and because a wall
  // of twenty-four chips buries it.
  const earliest = nextBookableTime(branch, fulfillment, now, tz);
  const interval = Math.max(Number(branch?.slot_interval_minutes ?? 30), 5);
  // Every time this branch can actually take, grouped by part of day.
  //
  // There was a free-text time field here as well, and it was the wrong answer
  // to the right question: it let someone ask for a minute the branch does not
  // serve, which then had to be caught and explained. The slots ARE the
  // location's timings, so offering them and nothing else cannot be wrong.
  // A shortlist was dropped at the same time — with the week's hours table
  // gone there is room for the day, and the headings make it scannable.
  const slotGroups = groupByPartOfDay(slotTimes, tz);

  // Once the intent exists the page becomes the payment sheet. Nothing else on
  // the checkout form can still change the amount at this point, so showing it
  // alongside an editable form would only invite a mismatch.
  if (pending) {
    return (
      <div className="page-pad mx-auto max-w-xl py-12">
        <div className="mt-4">
          <StepRail step={2} />
        </div>
        <h1 className="mt-5 font-display text-4xl font-extrabold">Pay for your order</h1>
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
            onPaid={s.clearCart}
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
          <h1 className="mt-7 font-display text-4xl font-extrabold sm:text-5xl">Order placed</h1>
          <p className="mt-4 text-lg text-muted">
            Your Thai feast is on its way. Track{" "}
            <b className="text-foreground">{placedOrderNumber ?? "your order"}</b> for live updates.
          </p>
          {eta != null && eta !== "" && (
            <p className="mt-3 flex items-center justify-center gap-2 font-semibold">
              <Clock className="size-4 text-primary" />
              {isDelivery ? "Arriving in" : "Ready in"} about {eta}{" "}
              {typeof eta === "number" ? "min" : ""}
              {etaAt && <span className="text-muted">· by {etaAt}</span>}
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
    setErrorNeedsCart(false);

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
    // Reveal every problem at once rather than one per attempt.
    setSubmitted(true);
    if (!contactReady) {
      setError("Please check the highlighted details and try again.");
      return;
    }

    // The server stores one line, so the parts are joined into something a
    // rider can read at the door. For pickup there is nothing to deliver to,
    // and the branch's own address is the honest value.
    const deliveryAddress =
      s.fulfillment === "DELIVERY"
        ? composeDeliveryAddress(address)
        : `${branch?.branch_name ?? "Pickup"} — ${branch?.address_line_1 ?? "Pickup order"}`;

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
      // Collected since the beginning and thrown away until migration 0058:
      // the form demanded a name and phone, said they were how the rider would
      // reach you, and sent neither.
      contact_name: fullName.trim(),
      contact_phone: phone.trim(),
      // Upper-cased to match how the campaign stored it, so "insta20" off a
      // phone screen credits "INSTA20".
      promo_code: promoCode.trim().toUpperCase() || null,
      // Previously never sent, so the backend defaulted every order to COD and
      // marked it PLACED immediately — which is why "Place order" looked like
      // it skipped payment. A CARD order is created PAYMENT_PENDING instead and
      // waits for a verified webhook before it reaches the kitchen.
      payment_method: method,
      items: s.cart.map((line) => ({
        menu_item_id: line.itemId,
        menu_item_size_id: line.sizeId ?? null,
        // The portion travels with the option. Without it every half-and-half
        // order reached the server as a whole one: the kitchen was told to put
        // both toppings over the whole pizza, and the server priced two whole
        // toppings against a screen that had charged for two halves.
        selected_options: line.optionIds.map((id) => ({
          option_id: id,
          quantity: 1,
          portion: line.optionPortions?.[id] ?? ("WHOLE" as const),
        })),
        quantity: line.quantity,
      })),
    };

    try {
      await validateOrder.mutateAsync(payload);
      const order = await createOrder.mutateAsync(payload);

      // Saved only now, with an order number against it: an address typed into
      // a form the customer then abandoned is not one they have told us to
      // keep. Failure here is silent on purpose — the order is placed, and
      // "we could not save your address for next time" is not something to
      // interrupt a payment with.
      // Not one we already hold: an order placed to an address on file must
      // not add a second copy of it, or the picker fills up with one street.
      const alreadyKnown = savedAddresses.some((entry) => isSameAddress(address, entry));
      if (isDelivery && saveAddress && !addressId && !alreadyKnown) {
        api
          .createSavedAddress({
            address_line_1: address.line1.trim(),
            address_line_2: address.line2.trim() || null,
            landmark: address.landmark.trim() || null,
            city: address.city.trim(),
            state: address.state.trim(),
            postal_code: address.zip.trim(),
            phone_number: phone.trim() || null,
          })
          .catch(() => undefined);
      }

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
      // A refusal about what is in the order is fixed in the cart, not here.
      // Without the way back, "The selected size is unavailable for Build Your
      // Own Pizza" is a dead end on the last screen before paying. Refusals
      // about when ("Restaurant is currently closed") are answered on this
      // page, so the link is offered only when the message names a dish in
      // the cart or the cart itself.
      setErrorNeedsCart(
        refusalNeedsCart(
          err instanceof ApiError && err.status === 400 ? err.message : "",
          s.cart.map((line) => line.name),
        ),
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
      <h1 className="mt-5 font-display text-4xl font-extrabold sm:text-5xl">Checkout</h1>
      <p className="mt-2 text-lg text-muted">Almost there — just confirm where this is headed.</p>

      {error && (
        <div
          className="mt-6 flex items-start gap-2 rounded-xl border border-danger bg-danger/10 p-4 text-sm font-semibold text-danger"
          role="alert"
        >
          <AlertCircle className="mt-0.5 size-4 shrink-0" />
          <span>
            {error}
            {errorNeedsCart && (
              <>
                {" "}
                <Link to="/cart" className="underline">
                  Change it in your cart
                </Link>
                .
              </>
            )}
          </span>
        </div>
      )}

      <div className="mt-8 grid items-start gap-6 grid-cols-[minmax(0,1fr)] lg:grid-cols-[minmax(0,1fr)_420px]">
        <div className="space-y-5">
          <section className="elevated-panel p-5 sm:p-6">
            <h2 className="font-display text-xl font-extrabold">
              Contact &amp; {isDelivery ? "delivery" : "pickup"}
            </h2>
            <p className="mt-1 text-sm text-muted">
              We use this to reach you if the rider needs directions.
            </p>

            {/* Said out loud. Fields that fill themselves without a word read
                as the form having got something wrong, and the customer
                re-reads all of them looking for it. */}
            {filledFromAccount && (
              <p className="prefill-note mt-3">
                <BadgeCheck className="size-4 shrink-0" />
                Filled in from your account — change anything that has moved.
              </p>
            )}

            {isDelivery && savedAddresses.length > 1 && (
              <div className="saved-address-picker mt-4">
                {savedAddresses.map((entry) => (
                  <button
                    type="button"
                    key={entry.id}
                    className="saved-address"
                    data-on={addressId === entry.id}
                    onClick={() => useSavedAddress(entry.id)}
                  >
                    <span className="saved-address__label">
                      {entry.label === "HOME" ? "Home" : entry.label === "WORK" ? "Work" : "Other"}
                    </span>
                    <span className="saved-address__line">{entry.formatted_address}</span>
                  </button>
                ))}
              </div>
            )}

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
                <div className="field-wrap" data-invalid={Boolean(show("phone") && phoneProblem)}>
                  {/* The country code is shown, not typed. A customer entering
                      a local number should not have to know the deployment's
                      country, and a free-text "+1" is one more thing to get
                      wrong. */}
                  <span className="country-code">{PHONE_COUNTRY_CODE}</span>
                  <Input
                    id="phone"
                    required
                    type="tel"
                    inputMode="tel"
                    autoComplete="tel-national"
                    placeholder="(555) 000-0000"
                    value={phone}
                    onChange={(e) => setPhone(formatPhoneAsTyped(e.target.value))}
                    onBlur={() => setTouched((t) => ({ ...t, phone: true }))}
                    aria-invalid={Boolean(show("phone") && phoneProblem)}
                    aria-describedby={show("phone") && phoneProblem ? "phone-error" : undefined}
                    className="h-12"
                  />
                </div>
                {show("phone") && phoneProblem && (
                  <p className="field-error" id="phone-error">
                    {phoneProblem}
                  </p>
                )}
              </div>
              <div className="space-y-1.5 sm:col-span-2">
                <Label htmlFor="promo_code">Promo code (optional)</Label>
                <div className="field-wrap">
                  <TicketPercent className="size-4" />
                  <Input
                    id="promo_code"
                    autoCapitalize="characters"
                    placeholder="Seen one on Instagram?"
                    value={promoCode}
                    onChange={(e) => setPromoCode(e.target.value.toUpperCase())}
                    className="h-12"
                  />
                </div>
              </div>
              {isDelivery && (
                <>
                  <AddressField
                    id="line1"
                    label="Address line 1"
                    placeholder="Street address"
                    autoComplete="address-line1"
                    className="sm:col-span-2"
                    icon={<MapPin className="size-4" />}
                    value={address.line1}
                    problem={show("line1") ? addressProblems.line1 : undefined}
                    onChange={(next) => editAddress("line1", next)}
                    onBlur={() => setTouched((t) => ({ ...t, line1: true }))}
                  />
                  <AddressField
                    id="line2"
                    label="Address line 2"
                    hint="Optional"
                    placeholder="Apartment, suite, floor"
                    autoComplete="address-line2"
                    className="sm:col-span-2"

                    value={address.line2}
                    problem={show("line2") ? addressProblems.line2 : undefined}
                    onChange={(next) => editAddress("line2", next)}
                    onBlur={() => setTouched((t) => ({ ...t, line2: true }))}
                  />
                  <AddressField
                    id="landmark"
                    label="Landmark"
                    hint="Optional"
                    placeholder="Opposite the park"
                    autoComplete="off"
                    className="sm:col-span-2"

                    value={address.landmark}
                    problem={show("landmark") ? addressProblems.landmark : undefined}
                    onChange={(next) => editAddress("landmark", next)}
                    onBlur={() => setTouched((t) => ({ ...t, landmark: true }))}
                  />
                  <AddressField
                    id="city"
                    label="City"
                    placeholder="City"
                    autoComplete="address-level2"
                    value={address.city}
                    problem={show("city") ? addressProblems.city : undefined}
                    onChange={(next) => editAddress("city", next)}
                    onBlur={() => setTouched((t) => ({ ...t, city: true }))}
                  />
                  <AddressField
                    id="state"
                    label="State"
                    placeholder="State"
                    autoComplete="address-level1"

                    value={address.state}
                    problem={show("state") ? addressProblems.state : undefined}
                    onChange={(next) => editAddress("state", next)}
                    onBlur={() => setTouched((t) => ({ ...t, state: true }))}
                  />
                  <AddressField
                    id="zip"
                    label="ZIP code"
                    placeholder="00000"
                    autoComplete="postal-code"
                    inputMode="numeric"

                    value={address.zip}
                    problem={show("zip") ? addressProblems.zip : undefined}
                    onChange={(next) => editAddress("zip", next)}
                    onBlur={() => setTouched((t) => ({ ...t, zip: true }))}
                  />
                </>
              )}
            </div>

            {/* Offered, not assumed, and only when this is a new address: the
                prefill is worth nothing to a customer whose first order never
                left anything behind to prefill FROM. */}
            {isDelivery && isAuthenticated && !addressId && (
              <label className="save-address mt-4">
                <input
                  type="checkbox"
                  checked={saveAddress}
                  onChange={(e) => setSaveAddress(e.target.checked)}
                />
                <span>Save this address to my account for next time</span>
              </label>
            )}

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
            <h2 className="font-display text-xl font-extrabold">When would you like it?</h2>

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
                {isDelivery ? "Arriving in" : "Ready in"} about {eta}{" "}
                {typeof eta === "number" ? "min" : ""}
                {/* See cart.tsx: the duration alone leaves the customer doing
                    the sum themselves. */}
                {etaAt && <span className="text-muted">· by {etaAt}</span>}
              </p>
            )}

            {scheduling &&
              (days.length === 0 ? (
                <div className="closed-notice mt-4">
                  <AlertCircle className="mt-0.5 size-5 shrink-0 text-danger" />
                  <div>
                    <p className="font-bold">No times available</p>
                    <p className="mt-0.5 text-sm text-muted">
                      This branch has nothing bookable in the next {branch?.max_future_days ?? 0}{" "}
                      days. Try {isDelivery ? "pickup" : "delivery"}, or another branch.
                    </p>
                  </div>
                </div>
              ) : (
                <>
                  <div className="mt-4">
                    <div className="picker-head">
                      <p className="picker-label">Day</p>
                      {/* The chips cover the next few days; the date field
                          covers the rest of the horizon. Bounded to what the
                          branch actually accepts, so the picker cannot offer a
                          date the server will refuse. */}
                      <label className="date-field">
                        <CalendarDays className="size-4 shrink-0 text-muted" />
                        <span className="sr-only">Pick a date</span>
                        <input
                          type="date"
                          value={selectedDay ? dateInputValue(selectedDay, tz) : ""}
                          min={dateInputValue(firstDay ?? now, tz)}
                          max={dateInputValue(lastDay, tz)}
                          onChange={(event) => {
                            const picked = dayFromInputValue(event.target.value, tz);
                            if (!picked) return;
                            setChosenDay(picked);
                            setChosenSlot(null);
                          }}
                        />
                      </label>
                    </div>

                    {days.length > 1 && (
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
                            {dayChipLabel(day, now, tz)}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className="mt-4">
                    <div className="picker-head">
                      <p className="picker-label">
                        {selectedDay ? dayChipLabel(selectedDay, now, tz) : "Time"}
                      </p>
                      {/* The window the times come from. Without it a short
                          list reads as "barely any availability" rather than
                          "this branch closes at 3". */}
                      {/* The only statement of opening hours on this screen
                          now, so it carries the clock icon and full weight
                          rather than reading as a footnote. */}
                      {todaysWindows.length > 0 && (
                        <p className="day-hours">
                          <Clock className="size-3.5 shrink-0" />
                          Open {todaysWindows.map((w) => formatSlotRange(w)).join(", ")}
                        </p>
                      )}
                    </div>

                    {pickedEmptyDay ? (
                      <p className="mt-2 text-sm text-muted">
                        Nothing left on {pickedEmptyDay}. Pick another day above.
                      </p>
                    ) : (
                      <>
                        {/* The soonest the kitchen can have it, as one tap. It
                            is what most people scheduling ahead are looking
                            for, and a wall of chips buried it. */}
                        {earliest && isSameDay(earliest, selectedDay ?? earliest, tz) && (
                          <button
                            type="button"
                            className="earliest-row mt-3"
                            data-on={chosenSlot?.getTime() === earliest.getTime()}
                            onClick={() => {
                              setChosenDay(earliest);
                              setChosenSlot(earliest);
                            }}
                          >
                            <Zap className="size-4 shrink-0 text-primary" />
                            <span className="min-w-0 flex-1 text-left">
                              <span className="block font-bold">Earliest available</span>
                              <span className="block text-xs text-muted">
                                {dayChipLabel(earliest, now, tz)} at {formatTimeOfDay(earliest, tz)}
                              </span>
                            </span>
                          </button>
                        )}

                        {slotGroups.map((group) => (
                          <div className="mt-3" key={group.label}>
                            {/* One heading is noise; three are a map. */}
                            {slotGroups.length > 1 && (
                              <p className="slot-group-label">{group.label}</p>
                            )}
                            <div className="slot-grid mt-2">
                              {group.times.map((time) => (
                                <button
                                  type="button"
                                  key={time.toISOString()}
                                  className="slot-chip"
                                  data-on={chosenSlot?.toISOString() === time.toISOString()}
                                  onClick={() => {
                                    setChosenSlot(time);
                                  }}
                                >
                                  {formatTimeOfDay(time, tz)}
                                </button>
                              ))}
                            </div>
                          </div>
                        ))}
                      </>
                    )}

                    {/* No lowercasing and no trailing period: lowercasing turned
                        "Thu, Sep 17" into "thu, sep 17", and the formatted time
                        already ends in one ("7:00 p.m.."). */}
                    {chosenSlot ? (
                      <p className="mt-4 flex items-center gap-2 text-sm font-semibold text-success">
                        <CheckCircle2 className="size-4 shrink-0" />
                        {isDelivery ? "Arriving" : "Ready"} {dayChipLabel(chosenSlot, now, tz)} at{" "}
                        {formatTimeOfDay(chosenSlot, tz)}
                      </p>
                    ) : (
                      // The Pay button is disabled until a time exists. Saying
                      // why beats leaving someone to work it out from a greyed
                      // rectangle at the bottom of the screen.
                      <p className="mt-4 text-sm text-muted">Pick a time to continue.</p>
                    )}
                  </div>
                </>
              ))}

            {/* The week's table used to sit here and it said nothing new. The
                day rail already lists only the days this branch can be booked
                for, and the line above the times states the selected day's own
                window — so seven rows repeated that and pushed the Pay button
                a screen further down on a phone. The cart keeps the full week
                behind a disclosure, where there is no day picker to read it
                from. */}
          </section>

          <section className="elevated-panel p-5 sm:p-6">
            <h2 className="font-display text-xl font-extrabold">Payment</h2>
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

            {paymentConfigPending && (
              <p className="mt-3 text-sm text-muted">Checking payment options…</p>
            )}

            {!paymentConfigPending && !cardAvailable && (
              <div
                className="mt-3 flex items-start gap-2 rounded-xl border border-danger bg-danger/10 p-3 text-sm font-semibold text-danger"
                role="alert"
              >
                <AlertCircle className="mt-0.5 size-4 shrink-0" />
                <span>
                  {paymentConfigFailed
                    ? "We couldn't check the payment options just now. Check your connection and try again."
                    : "Card payments aren't switched on for this restaurant yet, so orders can't be placed. Please try again shortly."}
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
          <h2 className="font-display text-xl font-extrabold">Your order</h2>
          <p className="mt-1 flex items-center gap-1.5 text-sm text-muted">
            <MapPin className="size-3.5 shrink-0 text-primary" />
            {isDelivery ? "Delivery" : "Pickup"} from {branch?.branch_name ?? "your branch"}
          </p>
          {eta != null && eta !== "" && (
            <p className="mt-1.5 flex items-center gap-1.5 text-sm font-semibold">
              <Clock className="size-3.5 shrink-0 text-primary" />
              About {eta} {typeof eta === "number" ? "min" : ""}
              {etaAt && <span className="text-muted">· by {etaAt}</span>}
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
                  {/* The size and the choices, on the last screen before
                      paying. It showed the dish name alone, so a Large
                      half-and-half pizza and a Small plain one were the same
                      two lines of text at different prices. */}
                  {(line.sizeName || line.addOnNames.length > 0) && (
                    <p className="text-xs leading-snug text-muted">
                      {[
                        line.sizeName,
                        ...chosenLabels(line.optionIds, line.addOnNames, line.optionPortions),
                      ]
                        .filter(Boolean)
                        .join(", ")}
                    </p>
                  )}
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
            <span className="text-lg font-extrabold">Total</span>
            <span className="font-display text-3xl font-extrabold">{formatMoney(total)}</span>
          </div>

          <Button
            className="mt-5 hidden h-12 w-full text-base lg:flex"
            disabled={!s.cart.length || submitting || !cardAvailable || (scheduling && !chosenSlot)}
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
            <p className="money font-display text-xl font-extrabold leading-tight">
              {formatMoney(total)}
            </p>
          </div>
          <Button
            className="h-13 flex-1 text-base"
            disabled={!s.cart.length || submitting || !cardAvailable || (scheduling && !chosenSlot)}
            type="submit"
          >
            {submitting ? "Working…" : "Pay now"}
          </Button>
        </div>
      </div>
    </form>
  );
}
