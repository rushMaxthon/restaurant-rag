import { useEffect, useRef, useState } from "react";
import { Link, createFileRoute } from "@tanstack/react-router";
import { AlertCircle, ArrowLeft, CheckCircle2, Clock } from "lucide-react";
import type { PickedAddress } from "@/components/AddressAutocomplete";
import { Button } from "@/components/ui/button";
import { CardPayment } from "@/components/bangkok/card-payment";
import { RazorpayPayment } from "@/components/bangkok/razorpay-payment";
import { ContactStep } from "@/components/checkout/contact-step";
import { MobilePayBar, OrderSummary } from "@/components/checkout/order-summary";
import { PaymentStep } from "@/components/checkout/payment-step";
import { ScheduleStep } from "@/components/checkout/schedule-step";
import { StepRail } from "@/components/checkout/step-rail";
import { orderCode } from "@/lib/bangkok-data";
import { useBangkokStore } from "@/lib/bangkok-store";
import {
  activeSlots,
  availabilityNow,
  bookableDays,
  bookableTimes,
  dayChipLabel,
  dayFromDate,
  etaClockTime,
  groupByPartOfDay,
  lastBookableDay,
  nextBookableTime,
  nextOpening,
} from "@/lib/branch-hours";
import {
  addressFromSaved,
  composeDeliveryAddress,
  isSameAddress,
  formatPhoneAsTyped,
  phoneWithoutCountryCode,
  looseAddressFields,
  postalCodeLabel,
  validateAddress,
  validatePhone,
  type AddressFields,
} from "@/lib/delivery-address";
import { useRequireAuth } from "@/lib/require-auth";
import {
  useCreateOrder,
  useDeliveryQuote,
  usePaymentConfig,
  useProfile,
  useValidateOrder,
} from "@/lib/queries";
import { ApiError, api, type OrderCreateRequest } from "@/lib/api";
import { refusalNeedsCart } from "@/lib/order-refusal";
import { pageMeta, useCurrencyCode, useStorefrontCopy, useMoney } from "@/lib/storefront";
import { getStorefrontCopy } from "@/lib/storefront.server";

export const Route = createFileRoute("/checkout")({
  loader: () => getStorefrontCopy(),
  head: ({ loaderData }) => ({
    meta: pageMeta(loaderData, "Checkout", "Choose delivery or pickup and place your order."),
  }),
  component: Checkout,
});

function Checkout() {
  // Prices in whatever this restaurant charges in.
  const money = useMoney();
  // What this storefront calls its last address box. The form asked every
  // customer for a "ZIP code" and refused anything that was not five
  // digits, so an Indian PIN code could not be typed into it.
  const postalName = postalCodeLabel(useCurrencyCode());
  // This restaurant's own name, resolved from the address in the root route.
  const copy = useStorefrontCopy();
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
    house: "",
    line1: "",
    line2: "",
    landmark: "",
    city: "",
    state: "",
    zip: "",
  });
  // The coordinates of a place the customer PICKED, when they picked one.
  //
  // Kept separately from the address text on purpose. The text is what a rider
  // reads at the door; this is what the courier prices, and they are not the
  // same fact. Cleared the moment any part of the address is typed over,
  // because a stale coordinate prices the wrong trip with complete confidence.
  const [pickedPoint, setPickedPoint] = useState<{ latitude: number; longitude: number } | null>(
    null,
  );
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
      // Stripped of the code the chip beside the field already shows.
      setPhone(formatPhoneAsTyped(phoneWithoutCountryCode(number, s.phoneCountryCode)));
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
  }, [profile.data, savedAddresses, s.phoneCountryCode]);

  /** Put a saved address in the form, replacing whatever is there. */
  const applySavedAddress = (id: string) => {
    const picked = savedAddresses.find((entry) => entry.id === id);
    if (!picked) return;
    setAddress(addressFromSaved(picked));
    setAddressId(id);
    setSaveAddress(false);
    if (picked.phone_number)
      setPhone(
        formatPhoneAsTyped(phoneWithoutCountryCode(picked.phone_number, s.phoneCountryCode)),
      );
    // The new address has not been looked at yet, so nothing about it is
    // "wrong" until the customer has had a chance to read it.
    setTouched((t) => ({ ...t, line1: false, city: false, state: false, zip: false }));
  };
  // Pinned once per render pass so the day list, the slot list and the
  // validity check cannot disagree about what "now" is.
  const now = new Date();
  // Set once the order and its intent exist; swaps the form for the gateway's
  // own payment UI. The cart is deliberately still full at this point — a
  // cancelled payment must leave the basket intact.
  const [pending, setPending] = useState<{
    orderId: string;
    orderNumber: string;
    clientSecret: string;
    publishableKey: string;
    method: "CARD" | "RAZORPAY";
  } | null>(null);

  // Which methods THIS RESTAURANT can actually take. Not the deployment's:
  // one deployment serves every tenant, and a Surat kitchen settling through
  // its own Razorpay account and a Toronto one on Stripe are both correct at
  // the same time. A method appears here only when the branch has it switched
  // on and a gateway is configured that can settle it, so nothing on this
  // screen is a button that dead-ends.
  const paymentConfig = usePaymentConfig(isAuthenticated);
  const supported = paymentConfig.data?.supported_methods ?? [];
  const gatewayKeys = paymentConfig.data?.gateway_keys ?? {};
  const cardAvailable = supported.includes("CARD");
  const razorpayAvailable = supported.includes("RAZORPAY") && Boolean(gatewayKeys["RAZORPAY"]);
  const payableMethods = [
    ...(razorpayAvailable ? (["RAZORPAY"] as const) : []),
    ...(cardAvailable ? (["CARD"] as const) : []),
  ];

  // Chosen rather than assumed, but only where there is a choice. With one
  // method available this is invisible; the customer is not asked to pick
  // from a list of one.
  const [chosenMethod, setChosenMethod] = useState<"CARD" | "RAZORPAY" | null>(null);
  const method = chosenMethod ?? payableMethods[0] ?? "CARD";
  const canPay = payableMethods.length > 0;
  // Three different situations, not two. While the config is in flight, and if
  // the request fails, `stripe_enabled` is falsy too — and the page used to
  // blame the restaurant for both, in red, on every single load.
  const paymentConfigPending = paymentConfig.isPending;
  const paymentConfigFailed = paymentConfig.isError;
  // A 401 is not a connection problem, and telling somebody to check their
  // connection when their sign-in has simply lapsed sends them to look at
  // their wifi. `ApiError` has carried the status all along; nothing read it.
  const sessionExpired =
    paymentConfig.error instanceof ApiError && paymentConfig.error.status === 401;

  // Must sit ABOVE the `isAuthenticated` early return: a hook called after a
  // conditional return runs on some renders and not others, and React fails
  // the next render with "rendered more hooks than during the previous
  // render". The same trap that crashed the admin's branch gate.
  //
  // The address is quoted as the string the ORDER will carry, so the fee
  // shown is the fee for the trip that gets booked — and only once the form
  // is valid, because a courier priced against half an address is a number
  // about nothing.
  const addressIsQuotable =
    s.fulfillment === "DELIVERY" && Object.keys(validateAddress(address, postalName)).length === 0;
  // Sent in PARTS rather than as one joined string. A geocoder given separate
  // fields can refuse a house number in the wrong city; given a blob it
  // silently picks whichever reading scores best. The form already has the
  // parts, so flattening them and asking the server to take them apart again
  // loses accuracy for nothing.
  const deliveryQuote = useDeliveryQuote(
    s.orderLocation?.id,
    addressIsQuotable
      ? {
          // `house` and `landmark` are BOTH left out, and this was measured.
          //
          // Sending "A-31, Rangdarshan Soc, Near Dhanmora" resolves to the
          // NEIGHBOURHOOD — 124 m from the building, and graded LOCALITY.
          // Sending "Rang Darshan Society" on its own resolves to the rooftop,
          // exactly where picking it from the dropdown lands. The door number
          // and the landmark are directions for a human; to a geocoder they are
          // noise that drags a precise answer down to a vague one, and a vague
          // one prices the wrong trip.
          //
          // Both still reach the rider: they are in the address line the order
          // stores. They are simply not part of the question asked of the map.
          delivery_address: [address.line1, address.line2]
            .map((part) => part.trim())
            .filter(Boolean)
            .join(", "),
          city: address.city.trim(),
          state: address.state.trim(),
          postal_code: address.zip.trim(),
          // A saved address the customer chose carries coordinates already, so
          // the server prices from those and calls no geocoder at all.
          saved_address_id: addressId ?? undefined,
          // The place the customer picked, when they picked one. Sent so the
          // courier prices the building they pointed at rather than the
          // server's best reading of the text.
          latitude: pickedPoint?.latitude,
          longitude: pickedPoint?.longitude,
          // The cart's food total, so the SERVER works out the tax and the
          // charges rather than this page doing its own arithmetic and
          // eventually disagreeing with what is charged.
          subtotal: s.subtotal,
        }
      : null,
  );

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
  const eta = isDelivery ? branch?.estimated_delivery_time : branch?.estimated_pickup_time;
  // The clock time that ETA lands on, on the branch's clock.
  const etaAt = etaClockTime(eta, now, tz);

  // Validation lives in lib/delivery-address.ts so the form and the submit
  // handler cannot disagree about what "valid" means.
  const addressProblems = isDelivery ? validateAddress(address, postalName) : {};
  // 0, not 45 — see the note in cart.tsx. An invented $45 delivery fee is
  // the worst thing to show someone one second before they pay.
  //
  // The branch's flat fee is the starting point and the server's quote wins
  // when there is one. The arithmetic is deliberately NOT the authority: the
  // order is priced again server-side when it is placed, from the same rule,
  // and this line exists to show a customer the figure rather than to decide
  // it. A courier prices by distance, so a flat fee quietly overcharges the
  // customer next door and undercharges the one across the city.
  // Whether a fee is KNOWN yet, which is not the same as whether it is zero.
  //
  // Until the address is filled in there is nothing to quote, and the row used
  // to fall back to the branch's flat fee — usually 0, so it rendered as the
  // word "Free" on an empty form. That is a promise, made before anyone knows
  // the distance, and contradicted by a real number a moment later.
  //
  // `addressIsQuotable` is half of this and not redundant. The hook keeps the
  // previous answer as placeholder data so the fee does not blink on every
  // keystroke — which also means that when the address is emptied and the query
  // goes disabled, `data` still holds the fee for the address that WAS there.
  // Clearing the street box left a confident fee on screen for a trip with no
  // destination.
  // `isPlaceholderData` is the third half of this. The hook keeps the previous
  // answer while a new one is in flight so the fee does not blink, but during
  // that window the number on screen belongs to the PREVIOUS address. Typing a
  // new street showed the old street's fee as final for about a second, which
  // is long enough to read and believe.
  const deliveryKnown =
    !isDelivery ||
    (addressIsQuotable && Boolean(deliveryQuote.data) && !deliveryQuote.isPlaceholderData);
  const delivery =
    deliveryKnown && deliveryQuote.data ? Number(deliveryQuote.data.delivery_fee) : 0;
  const quotedByCourier = deliveryKnown && deliveryQuote.data?.source === "courier";
  /**
   * How far the food has to travel, in words.
   *
   * The courier measures this to the metre and it was buried in a muted line
   * under the totals. It belongs beside the branch it is measured FROM, which
   * is the only place it means anything.
   *
   * Under a kilometre reads in metres rounded to fifty, because "0.4 km" is a
   * worse way of saying "400 m" and "377 m" is a precision nobody asked for.
   */
  const distanceLabel = (() => {
    const metres = quotedByCourier ? deliveryQuote.data?.distance_metres : null;
    if (!metres) return null;
    if (metres < 1000) return `${Math.round(metres / 50) * 50} m away`;
    return `${(metres / 1000).toFixed(1)} km away`;
  })();
  // Why the courier's price is missing, when it is. Not every fallback is a
  // problem: a restaurant with no courier charges its own flat fee on purpose,
  // and that is a real price. A fallback because nobody could find the address
  // is not a price at all, and printing it — as "Free", when the flat fee is
  // zero — is how a real order came to promise free delivery it had never
  // worked out.
  const fallback = deliveryKnown ? (deliveryQuote.data?.fallback_reason ?? "") : "";
  const feeIsAGuess = fallback === "address_unknown" || fallback === "branch_unknown";
  // A courier that will not drive to this address at all. The fee falls back
  // to the branch's, so the total stays honest, but saying nothing would let
  // somebody pay for a delivery no rider is going to accept.
  const unserviceable = Boolean(
    deliveryKnown && deliveryQuote.data && !deliveryQuote.data.serviceable,
  );
  // The bill, as the server worked it out — the same code that charges the
  // customer. The 5% this page used to multiply by is gone: it was a guess
  // that happened to match the old hardcoded rate, and it would have quietly
  // lied the moment a restaurant set its own.
  const charges = deliveryKnown ? (deliveryQuote.data?.charges ?? null) : null;
  const tax = charges ? Number(charges.total) : s.subtotal * 0.05;
  // Delivery is in the total only once it is known. A total that quietly counts
  // an unknown fee as zero is a number the customer will be asked to pay more
  // than.
  const total =
    deliveryKnown && deliveryQuote.data?.total_amount != null
      ? Number(deliveryQuote.data.total_amount)
      : s.subtotal + delivery + tax;
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
  /**
   * Fill the form in from a place the customer picked.
   *
   * The coordinates are the map provider's own record for that building, so
   * they are kept and sent with the delivery quote — which is the whole point
   * of a dropdown over a text box. The address parts are filled in too, but
   * only where the provider actually returned something: overwriting a city the
   * customer typed with an empty string because the provider omitted it is a
   * worse form than the one they had.
   *
   * `landmark` is deliberately untouched. No provider knows the gate somebody
   * tells a rider to look for.
   */
  const applyPickedAddress = (picked: PickedAddress) => {
    setAddress((current) => ({
      ...current,
      // `house` is deliberately absent. The provider knows where the building
      // is; only the customer knows which door inside it, and overwriting the
      // flat number with the building's name is exactly what this field exists
      // to stop.
      line1: picked.line1 || picked.formatted || current.line1,
      line2: picked.line2 || current.line2,
      city: picked.city || current.city,
      state: picked.state || current.state,
      zip: picked.postal_code || current.zip,
    }));
    setPickedPoint({ latitude: picked.latitude, longitude: picked.longitude });
    // A picked address is a different address from the saved one that was
    // showing, so the chip stops claiming otherwise.
    setAddressId(null);
    setTouched((t) => ({ ...t, line1: true, city: true, state: true, zip: true }));
  };

  const editAddress = (part: keyof AddressFields, next: string) => {
    setAddress((a) => ({ ...a, [part]: next }));
    // The resolved coordinate described what was in the box a moment ago. Typed
    // over, it no longer does, and a stale point would price the wrong trip
    // with complete confidence.
    if (part !== "landmark") setPickedPoint(null);
    if (addressId) {
      setAddressId(null);
      setSaveAddress(true);
    }
  };

  const show = (field: keyof AddressFields | "phone" | "name") =>
    Boolean(touched[field] || submitted);

  /**
   * Put the cursor in the first box that needs fixing.
   *
   * The form is about 2,600px tall on a phone and Pay now lives in a bar
   * pinned to the bottom of the screen, so pressing it with something missing
   * did this: an error appeared 970px away, off-screen, focus stayed on the
   * body, and from where the customer was sitting nothing happened at all.
   * The natural next move is to press it again.
   *
   * In the order the fields appear on the page, not the order the checks run,
   * so somebody with two problems is taken to the top one and works down.
   * `focus()` rather than only scrolling: it moves the screen reader and the
   * on-screen keyboard too, and it is the thing that makes the next keystroke
   * land somewhere useful.
   */
  const takeThemToTheProblem = () => {
    const order: Array<[string, unknown]> = [
      ["full_name", nameProblem],
      ["phone", phoneProblem],
      ["line1", addressProblems.line1],
      ["city", addressProblems.city],
      ["state", addressProblems.state],
      ["zip", addressProblems.zip],
    ];
    const first = order.find(([, problem]) => Boolean(problem));
    if (!first) {
      return;
    }
    const field = document.getElementById(first[0]);
    // `center` rather than the default `start`: the sticky summary bar sits
    // over the bottom of the page and the header over the top, and a field
    // scrolled flush to either edge lands underneath one of them.
    field?.scrollIntoView({ block: "center" });
    // Deliberately NOT `preventScroll`. Smooth scrolling can be interrupted,
    // refused, or switched off by the reader's own motion setting, and this
    // is the error path — if the scroll above does not happen, focus's own
    // scrolling is what still puts the field on screen. A double jump is a
    // worse animation and a much better outcome than a customer looking at an
    // unchanged page.
    field?.focus();
  };

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
          {pending.method === "RAZORPAY" ? (
            <RazorpayPayment
              amount={total}
              customerEmail={profile.data?.user.email ?? null}
              customerName={fullName.trim() || profile.data?.user.full_name || null}
              customerPhone={phone.trim() || profile.data?.user.phone_number || null}
              keyId={pending.publishableKey}
              onCancel={abandonPayment}
              onPaid={s.clearCart}
              orderId={pending.orderId}
              orderNumber={pending.orderNumber}
              razorpayOrderId={pending.clientSecret}
              restaurantName={s.restaurantName ?? "your order"}
            />
          ) : (
            <CardPayment
              publishableKey={pending.publishableKey}
              clientSecret={pending.clientSecret}
              amount={total}
              returnUrl={`${window.location.origin}/orders/${pending.orderId}`}
              onCancel={abandonPayment}
              onPaid={s.clearCart}
            />
          )}
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
            Your order from {copy.name} is on its way. Track{" "}
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
      takeThemToTheProblem();
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
      // The building they chose, not the line they typed. Sent on the quote
      // since the autocomplete was built and never on the order, so the two
      // were priced from different points — the quote from the picked
      // rooftop, the order from a fresh geocode of the text that resolves to
      // a locality. The server now refuses a delivery order without them.
      latitude: pickedPoint?.latitude,
      longitude: pickedPoint?.longitude,
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
            // The house number is written into the stored line, because a
            // saved address is one line and the rider needs it first.
            address_line_1: [address.house, address.line1]
              .map((part) => part.trim())
              .filter(Boolean)
              .join(", "),
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
        // For Razorpay this carries the Razorpay ORDER id rather than a
        // secret: that gateway has no client secret, and the browser needs
        // the order id to open Checkout. The field name comes from the
        // provider contract, not from Razorpay.
        clientSecret: intent.client_secret,
        publishableKey: intent.publishable_key,
        method,
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
  // One rule for both Pay buttons, so the panel and the phone bar cannot
  // disagree about whether the order may be placed yet.
  // `payableMethods.length > 0`, not `cardAvailable`. The gate asked whether
  // STRIPE was available, which was the same question back when card was the
  // only way to pay — and silently stopped being it. A restaurant settling
  // through Razorpay alone would have had both Pay buttons disabled on a
  // checkout that was otherwise complete, with nothing on screen to say why.
  const canSubmit =
    s.cart.length > 0 &&
    !submitting &&
    payableMethods.length > 0 &&
    !(scheduling && !chosenSlot);

  return (
    <form
      className="page-pad mx-auto max-w-7xl 2xl:max-w-[88rem] pb-40 pt-10"
      onSubmit={handleSubmit}
    >
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
          <ContactStep
            isDelivery={isDelivery}
            isAuthenticated={isAuthenticated}
            filledFromAccount={filledFromAccount}
            savedAddresses={savedAddresses}
            addressId={addressId}
            onPickSavedAddress={applySavedAddress}
            fullName={fullName}
            onFullNameChange={setFullName}
            phone={phone}
            onPhoneChange={(next) => setPhone(formatPhoneAsTyped(next))}
            phoneCountryCode={s.phoneCountryCode}
            phoneProblem={phoneProblem}
            address={address}
            addressProblems={addressProblems}
            onEditAddress={editAddress}
            onPickAddress={applyPickedAddress}
            onTouch={(field) => setTouched((t) => ({ ...t, [field]: true }))}
            show={show}
            branch={branch}
            postalName={postalName}
            saveAddress={saveAddress}
            onSaveAddressChange={setSaveAddress}
          />

          <ScheduleStep
            isDelivery={isDelivery}
            mustSchedule={mustSchedule}
            unavailableReason={availability.reason}
            wantsLater={wantsLater}
            onWantsLaterChange={(later) => {
              setWantsLater(later);
              if (!later) setChosenSlot(null);
            }}
            scheduling={scheduling}
            eta={eta}
            etaAt={etaAt}
            days={days}
            maxFutureDays={branch?.max_future_days ?? 0}
            selectedDay={selectedDay}
            tz={tz}
            now={now}
            firstDay={firstDay}
            lastDay={lastDay}
            onPickDay={(day) => {
              setChosenDay(day);
              setChosenSlot(null);
            }}
            todaysWindows={todaysWindows}
            pickedEmptyDay={pickedEmptyDay}
            earliest={earliest}
            chosenSlot={chosenSlot}
            onPickSlot={setChosenSlot}
            onPickEarliest={(time) => {
              setChosenDay(time);
              setChosenSlot(time);
            }}
            slotGroups={slotGroups}
            branchName={branch?.branch_name}
          />

          <PaymentStep
            paymentConfigPending={paymentConfigPending}
            canPay={canPay}
            sessionExpired={sessionExpired}
            paymentConfigFailed={paymentConfigFailed}
            payableMethods={payableMethods}
            method={method}
            onChooseMethod={setChosenMethod}
          />
        </div>

        <OrderSummary
          isDelivery={isDelivery}
          branchName={branch?.branch_name}
          distanceLabel={distanceLabel}
          eta={eta}
          etaAt={etaAt}
          cart={s.cart}
          money={money}
          subtotal={s.subtotal}
          delivery={delivery}
          deliveryKnown={deliveryKnown}
          deliveryFetching={deliveryQuote.isFetching}
          feeIsAGuess={feeIsAGuess}
          charges={charges}
          quotedByCourier={quotedByCourier}
          travelSeconds={deliveryQuote.data?.travel_seconds}
          fallback={fallback}
          postalName={postalName}
          unserviceable={unserviceable}
          total={total}
          promoCode={promoCode}
          onPromoCodeChange={setPromoCode}
          submitting={submitting}
          payingCard={payingCard}
          canSubmit={canSubmit}
        />
      </div>

      <MobilePayBar
        totalItems={s.totalItems}
        money={money}
        total={total}
        deliveryKnown={deliveryKnown}
        submitting={submitting}
        canSubmit={canSubmit}
      />
    </form>
  );
}
