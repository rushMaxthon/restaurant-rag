import { Clock, MapPin, TicketPercent } from "lucide-react";

import { ChargesBreakdown } from "@/components/ChargesBreakdown";
import { DishImage } from "@/components/bangkok/dish-image";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { CartLine } from "@/lib/bangkok-store";
import { chosenLabels } from "@/lib/customization";
import { payButtonLabel, type PayBlock } from "@/lib/pay-gate";

type Charges = React.ComponentProps<typeof ChargesBreakdown>["charges"];

/**
 * What is being paid for, beside the form.
 *
 * Every figure arrives already decided. Which fee is shown, whether it is a
 * courier's price or the branch's flat rate, whether the address could be
 * placed on a map — the checkout works those out against the same quote the
 * order will be priced from, and this prints them. It says "So far" rather
 * than "Total" while the delivery fee is unknown, because a total that quietly
 * counts an unknown fee as zero is a number the customer will be asked to pay
 * more than.
 *
 * `MobilePayBar` below is the same total for a phone, where this panel scrolls
 * out of reach. They are in one file so they cannot disagree.
 */
export function OrderSummary({
  isDelivery,
  branchName,
  distanceLabel,
  eta,
  etaAt,
  cart,
  money,
  subtotal,
  delivery,
  deliveryKnown,
  deliveryFetching,
  feeIsAGuess,
  charges,
  quotedByCourier,
  travelSeconds,
  fallback,
  postalName,
  unserviceable,
  outOfRange = null,
  total,
  showPromoCode,
  promoCode,
  onPromoCodeChange,
  submitting,
  payingCard,
  canSubmit,
  payBlock,
}: {
  isDelivery: boolean;
  branchName: string | undefined;
  distanceLabel: string | null;
  eta: string | number | undefined;
  etaAt: string | null;
  cart: CartLine[];
  money: (value: number) => string;
  subtotal: number;
  delivery: number;
  deliveryKnown: boolean;
  deliveryFetching: boolean;
  feeIsAGuess: boolean;
  charges: Charges;
  quotedByCourier: boolean;
  travelSeconds: number | null | undefined;
  fallback: string;
  postalName: string;
  unserviceable: boolean;
  /** Further than the restaurant delivers; the order cannot be placed. */
  outOfRange?: { distanceKm: number; limitKm: number } | null;
  total: number;
  /** The restaurant's `promo_code` capability. Off, the box is not drawn. */
  showPromoCode: boolean;
  promoCode: string;
  onPromoCodeChange: (next: string) => void;
  submitting: boolean;
  payingCard: boolean;
  /** Everything the form needs before the Pay button may be pressed. */
  canSubmit: boolean;
  /** Why the button is disabled, when it is. See `lib/pay-gate.ts`. */
  payBlock: PayBlock | null;
}) {
  return (
    <aside className="elevated-panel order-summary h-fit lg:sticky lg:top-24">
      <h2 className="font-display text-xl font-extrabold">Your order</h2>
      <p className="mt-1 flex items-center gap-1.5 text-sm text-muted">
        <MapPin className="size-3.5 shrink-0 text-primary" />
        {isDelivery ? "Delivery" : "Pickup"} from {branchName ?? "your branch"}
        {distanceLabel && (
          <>
            <span aria-hidden="true">·</span>
            <span className="font-semibold text-foreground">{distanceLabel}</span>
          </>
        )}
      </p>
      {eta != null && eta !== "" && (
        <p className="mt-1.5 flex items-center gap-1.5 text-sm font-semibold">
          <Clock className="size-3.5 shrink-0 text-primary" />
          About {eta} {typeof eta === "number" ? "min" : ""}
          {etaAt && <span className="text-muted">· by {etaAt}</span>}
        </p>
      )}

      <div className="order-summary__lines mt-5 space-y-3 border-b border-border pb-5">
        {cart.map((line, i) => (
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
              {/* The size and the choices, on the last screen before paying:
                  a Large half-and-half pizza and a Small plain one were the
                  same two lines of text at different prices. */}
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
                {line.quantity} × {money(line.unitPrice)}
              </p>
            </div>
            <span className="money shrink-0 font-bold">
              {money(line.unitPrice * line.quantity)}
            </span>
          </div>
        ))}
      </div>

      <dl className="mt-5 space-y-2.5 text-sm">
        {[
          ["Subtotal", subtotal],
          [isDelivery ? "Delivery fee" : "Pickup", delivery],
        ].map(([label, value]) => {
          // The delivery row says what it does not yet know, rather than
          // printing a zero that reads as a promise of free delivery.
          const unknown = label === "Delivery fee" && !deliveryKnown;
          return (
            <div className="flex justify-between gap-3" key={String(label)}>
              <dt className="text-muted">{label}</dt>
              <dd className={unknown ? "text-right text-xs text-muted" : "money font-semibold"}>
                {label === "Delivery fee" && outOfRange
                  ? "Too far"
                  : unknown
                    ? deliveryFetching
                      ? "Working it out…"
                      : "Once you add your address"
                    : // "Free" belongs to the delivery row ALONE, and only when
                      // somebody actually decided delivery is free — never because
                      // a lookup failed and the flat fee happened to be zero.
                      Number(value) === 0 && !feeIsAGuess && String(label) !== "Subtotal"
                      ? "Free"
                      : money(Number(value))}
              </dd>
            </div>
          );
        })}
        {/* One row that opens into the parts. Falls back to a plain,
            unexpandable line when the server sent no breakdown. */}
        <ChargesBreakdown charges={charges} money={money} unknownText="Worked out at payment" />
      </dl>

      {outOfRange ? (
        <p className="inline-error mt-2 text-xs">
          This address is about {outOfRange.distanceKm.toFixed(1)} km away, and the restaurant
          delivers up to {outOfRange.limitKm} km. Choose a closer address, or pickup.
        </p>
      ) : null}
      {isDelivery && quotedByCourier && !outOfRange ? (
        <p className="mt-2 text-xs text-muted">
          Priced for your address, not a flat rate.
          {travelSeconds
            ? ` About ${Math.max(1, Math.round(travelSeconds / 60))} min of riding once your food is ready.`
            : ""}
        </p>
      ) : null}
      {fallback === "address_unknown" ? (
        <p className="inline-error mt-2 text-xs">
          We could not find that address on a map, so this is the restaurant&rsquo;s standard
          delivery charge rather than a price for your trip. Check the street and{" "}
          {postalName.toLowerCase()}, or pick your address from the suggestions as you type.
        </p>
      ) : fallback === "courier_unavailable" ? (
        // Not an `inline-error`: there is nothing here for the customer to
        // fix, and a red notice beside a field they just filled in reads as
        // an accusation. This case used to render the sentence above it —
        // "check the street and PIN code" — while the real cause was the
        // courier's login answering 503.
        <p className="mt-2 text-xs text-muted">
          We could not reach the delivery partner just now, so this is the restaurant&rsquo;s
          standard delivery charge rather than a price for your trip. Your address is fine.
        </p>
      ) : fallback === "branch_unknown" ? (
        <p className="mt-2 text-xs text-muted">
          This restaurant has not pinned its branch on a map yet, so this is their standard delivery
          charge rather than a price for your trip.
        </p>
      ) : null}
      {unserviceable ? (
        <p className="inline-error mt-2 text-xs">
          No courier covers this address right now. The restaurant may still deliver it themselves,
          or choose pickup instead.
        </p>
      ) : null}

      {/* A promo code belongs with the money it comes off, not in the middle
          of the address. It sat between the phone number and the flat number,
          which made the one block a customer has to get right read as a form
          with an advert in it — and put a field nobody has a code for in
          front of everybody. */}
      {showPromoCode ? (
        <div className="promo-row mt-4 space-y-1.5">
          <Label htmlFor="promo_code">Promo code (optional)</Label>
          <div className="field-wrap">
            <TicketPercent className="size-4" />
            <Input
              id="promo_code"
              autoCapitalize="characters"
              placeholder="Seen one on Instagram?"
              value={promoCode}
              onChange={(e) => onPromoCodeChange(e.target.value.toUpperCase())}
              className="h-11"
            />
          </div>
        </div>
      ) : null}

      <div className="total-row mt-4 flex items-end justify-between border-t border-border pt-4">
        <span className="text-lg font-extrabold">{deliveryKnown ? "Total" : "So far"}</span>
        <span className="font-display text-3xl font-extrabold">{money(total)}</span>
      </div>
      {!deliveryKnown && (
        <p className="mt-1.5 text-xs text-muted">Delivery is added once you add your address.</p>
      )}

      <Button
        className="mt-5 hidden h-12 w-full text-base lg:flex"
        disabled={!canSubmit}
        type="submit"
      >
        {payButtonLabel({
          block: payBlock,
          submitting,
          openingPayment: payingCard,
          priceLabel: `Pay ${money(total)}`,
        })}
      </Button>
      {/* Why, when the label could not carry it. A disabled button that
          explains nothing is a dead end — and this one had a state with no
          explanation anywhere on the page: a branch with no usable payment
          method. `aria-live` because the reason changes under the customer as
          they fill the form, and a screen reader would otherwise never hear
          that the button became pressable. */}
      <p aria-live="polite" className="pay-reason mt-2 hidden text-xs text-muted lg:block">
        {!submitting && payBlock?.detail ? payBlock.detail : null}
      </p>
    </aside>
  );
}

/**
 * The total and the Pay button, pinned above the tab bar on a phone.
 *
 * Rendered OUTSIDE the two-column grid, as it always was. It is
 * `position: fixed`, and a fixed element is positioned against the nearest
 * transformed ancestor rather than the viewport — which is why `page-in` is
 * deliberately opacity-only, and why this must not be nested anywhere that
 * might one day pick up a transform.
 *
 * z-[45]: above the tab bar (z-40) and below the header (z-50). At z-30 the
 * page content painted over this bar, and Playwright found the day and time
 * chips intercepting clicks meant for "Pay now" — which means a real thumb
 * would have hit them too.
 */
export function MobilePayBar({
  totalItems,
  money,
  total,
  deliveryKnown,
  submitting,
  canSubmit,
  payBlock,
}: {
  totalItems: number;
  money: (value: number) => string;
  total: number;
  deliveryKnown: boolean;
  submitting: boolean;
  canSubmit: boolean;
  /** Why the button is disabled, when it is. See `lib/pay-gate.ts`. */
  payBlock: PayBlock | null;
}) {
  return (
    <div className="above-tab-bar fixed inset-x-0 z-[45] border-t border-border bg-surface/95 p-3 backdrop-blur lg:hidden">
      {/* Above the row, not inside the button.
          The button is `flex-1` on a 393px screen, so a sentence in it would
          either shrink the tap target below the 44px floor `mobile-layout.
          spec.ts` enforces or run off the edge. The short `label` is used
          rather than `detail` for the same reason — this bar has one line to
          spare, and the labels are written to be that line. */}
      {!submitting && payBlock ? (
        <p
          aria-live="polite"
          className="pay-reason mx-auto mb-2 max-w-2xl text-xs font-bold text-muted"
        >
          {payBlock.label}
        </p>
      ) : null}
      <div className="mx-auto flex max-w-2xl items-center gap-3">
        <div className="min-w-0">
          <p className="text-xs font-bold text-muted">
            {totalItems} {totalItems === 1 ? "item" : "items"}
          </p>
          <p className="money font-display text-xl font-extrabold leading-tight">{money(total)}</p>
          {/* On a phone this bar is the only total in view, so it must not
              read as final while the delivery fee is still unknown. */}
          {!deliveryKnown && <p className="text-[11px] text-muted">before delivery</p>}
        </div>
        <Button className="h-13 flex-1 text-base" disabled={!canSubmit} type="submit">
          {submitting ? "Working…" : "Pay now"}
        </Button>
      </div>
    </div>
  );
}
