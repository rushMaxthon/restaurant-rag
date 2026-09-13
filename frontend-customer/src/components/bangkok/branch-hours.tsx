import { Clock } from "lucide-react";
import {
  dayFromDate,
  dayLabel,
  formatSlotRange,
  weeklySlots,
  type Fulfillment,
} from "@/lib/branch-hours";
import type { RestaurantLocation } from "@/lib/bangkok-data";

/**
 * The branch's opening windows for one fulfilment type.
 *
 * Delivery and pickup keep different hours — the kitchen opens for collection
 * before it starts sending riders out — and the API has always returned both.
 * Showing them is the difference between "we're closed" and "we're closed,
 * come back at 11".
 */
export function BranchHours({
  location,
  fulfillment,
  className,
}: {
  location: RestaurantLocation | undefined;
  fulfillment: Fulfillment;
  className?: string;
}) {
  const week = weeklySlots(location, fulfillment);
  const today = dayFromDate(new Date());
  const hasAny = week.some((entry) => entry.slots.length > 0);

  if (!hasAny) return null;

  return (
    <div className={className}>
      <h3 className="flex items-center gap-2 text-sm font-black uppercase tracking-wide text-muted">
        <Clock className="size-4 text-primary" />
        {fulfillment === "DELIVERY" ? "Delivery hours" : "Pickup hours"}
      </h3>
      <dl className="mt-3 grid gap-1.5">
        {week.map(({ day, slots }) => (
          <div className="hours-row" data-today={day === today} key={day}>
            <dt>{dayLabel(day)}</dt>
            <dd>
              {slots.length === 0 ? (
                <span className="text-muted">Closed</span>
              ) : (
                slots.map((slot) => <span key={slot.id}>{formatSlotRange(slot)}</span>)
              )}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
