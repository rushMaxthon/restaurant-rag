import { AlertCircle, CalendarDays, CheckCircle2, Clock, Zap } from "lucide-react";

import { StepHeader } from "@/components/checkout/step-header";
import type { FulfillmentSlot } from "@/lib/bangkok-data";
import {
  dateInputValue,
  dayChipLabel,
  dayFromInputValue,
  formatSlotRange,
  formatTimeOfDay,
  isSameDay,
} from "@/lib/branch-hours";

/** Times for one part of the day, as `groupByPartOfDay` hands them over. */
export type SlotGroup = { label: string; times: Date[] };

/**
 * Step two: now, or a time the branch can actually take.
 *
 * Stateless by design — see `ContactStep`. Which days are bookable, which
 * times, what "now" is and whether the branch is open are all decided in the
 * checkout against one clock, and this renders the answer. It holds the one
 * thing worth saying about this step's markup: the classes `.slot-chip`,
 * `.day-chip`, `.date-field` and the "Schedule for later" button are what the
 * end-to-end suite drives, so they are a contract rather than a style choice.
 */
export function ScheduleStep({
  isDelivery,
  mustSchedule,
  unavailableReason,
  wantsLater,
  onWantsLaterChange,
  scheduling,
  eta,
  etaAt,
  days,
  maxFutureDays,
  selectedDay,
  tz,
  now,
  firstDay,
  lastDay,
  onPickDay,
  todaysWindows,
  pickedEmptyDay,
  earliest,
  chosenSlot,
  onPickSlot,
  onPickEarliest,
  slotGroups,
  branchName,
}: {
  isDelivery: boolean;
  mustSchedule: boolean;
  unavailableReason: string | null | undefined;
  wantsLater: boolean;
  onWantsLaterChange: (later: boolean) => void;
  scheduling: boolean;
  eta: string | number | undefined;
  etaAt: string | null;
  days: Date[];
  maxFutureDays: number;
  selectedDay: Date | null;
  tz: string | undefined;
  now: Date;
  firstDay: Date | undefined;
  lastDay: Date;
  onPickDay: (day: Date) => void;
  todaysWindows: FulfillmentSlot[];
  pickedEmptyDay: string | null;
  earliest: Date | null;
  chosenSlot: Date | null;
  /** A time chip: sets the slot and leaves the chosen day alone. */
  onPickSlot: (time: Date) => void;
  /** The "earliest available" row: it may be on another day, so it sets both. */
  onPickEarliest: (time: Date) => void;
  slotGroups: SlotGroup[];
  branchName: string | undefined;
}) {
  return (
    <section className="elevated-panel step-panel">
      <StepHeader
        number={2}
        title="When would you like it?"
        blurb={
          mustSchedule
            ? undefined
            : `${branchName ?? "The kitchen"} can start on it now, or hold it for a time you pick.`
        }
      />

      {mustSchedule ? (
        <div className="closed-notice mt-4" data-tone="soft">
          <Clock className="mt-0.5 size-5 shrink-0 text-muted" />
          <div>
            <p className="font-bold">{isDelivery ? "Delivery" : "Pickup"} is closed right now</p>
            <p className="mt-0.5 text-sm text-muted">
              {unavailableReason ?? "This branch is outside its opening hours."} Pick a time below
              and we'll have it ready then.
            </p>
          </div>
        </div>
      ) : (
        // Offered even when the branch is open: ordering dinner from your desk
        // at 3pm is a normal thing to want, and the backend has accepted a
        // scheduled time since the beginning.
        <div className="segmented mt-4" data-active={wantsLater ? "PICKUP" : "DELIVERY"}>
          <span className="segmented-thumb" aria-hidden="true" />
          <button
            type="button"
            className="segmented-option"
            data-selected={!wantsLater}
            onClick={() => onWantsLaterChange(false)}
          >
            As soon as possible
          </button>
          <button
            type="button"
            className="segmented-option"
            data-selected={wantsLater}
            onClick={() => onWantsLaterChange(true)}
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
          {/* The clock time as well as the duration: the duration alone leaves
              the customer doing the sum themselves. */}
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
                This branch has nothing bookable in the next {maxFutureDays} days. Try{" "}
                {isDelivery ? "pickup" : "delivery"}, or another branch.
              </p>
            </div>
          </div>
        ) : (
          <>
            <div className="mt-4">
              <div className="picker-head">
                <p className="picker-label">Day</p>
                {/* The chips cover the next few days; the date field covers
                    the rest of the horizon. Bounded to what the branch
                    actually accepts, so the picker cannot offer a date the
                    server will refuse. */}
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
                      onPickDay(picked);
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
                      // Its own class as well as `slot-chip`: a day and a time
                      // are different choices, and sharing one hook meant
                      // "pick the first chip" silently picked a day.
                      className="slot-chip day-chip"
                      data-on={selectedDay?.toDateString() === day.toDateString()}
                      onClick={() => onPickDay(day)}
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
                {/* The window the times come from. Without it a short list
                    reads as "barely any availability" rather than "this branch
                    closes at 3". */}
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
                  {/* The soonest the kitchen can have it, as one tap. It is
                      what most people scheduling ahead are looking for, and a
                      wall of chips buried it. */}
                  {earliest && isSameDay(earliest, selectedDay ?? earliest, tz) && (
                    <button
                      type="button"
                      className="earliest-row mt-3"
                      data-on={chosenSlot?.getTime() === earliest.getTime()}
                      onClick={() => onPickEarliest(earliest)}
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
                      {slotGroups.length > 1 && <p className="slot-group-label">{group.label}</p>}
                      <div className="slot-grid mt-2">
                        {group.times.map((time) => (
                          <button
                            type="button"
                            key={time.toISOString()}
                            className="slot-chip"
                            data-on={chosenSlot?.toISOString() === time.toISOString()}
                            onClick={() => onPickSlot(time)}
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
                // The Pay button is disabled until a time exists. Saying why
                // beats leaving someone to work it out from a greyed rectangle
                // at the bottom of the screen.
                <p className="mt-4 text-sm text-muted">Pick a time to continue.</p>
              )}
            </div>
          </>
        ))}
    </section>
  );
}
