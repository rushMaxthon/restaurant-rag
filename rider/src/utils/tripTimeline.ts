import type { Key } from '@/i18n/strings';
import { translate } from '@/i18n/translate';
import type { Trip } from '@/types/api';

export type EndTone = 'success' | 'warning' | 'danger' | 'neutral';

// Keys, not words: the label is looked up when asked for, in the language then in force.
const END: Record<string, { key: Key; tone: EndTone }> = {
  DELIVERED: { key: 'money.endDelivered', tone: 'success' },
  CUSTOMER_UNAVAILABLE: { key: 'money.endCustomerUnavailable', tone: 'warning' },
  CANCELLED_BEFORE_PICKUP: { key: 'money.endCancelled', tone: 'danger' },
  CANCELLED_AFTER_PICKUP: { key: 'money.endCancelled', tone: 'danger' },
  REASSIGNED: { key: 'money.endReassigned', tone: 'neutral' },
};

/** How a trip ended, as a pill: one place for History, the detail screen and Home. */
export function endLabel(reason: string | null | undefined): {
  label: string;
  tone: EndTone;
} {
  if (!reason) return { label: translate('money.endEnded'), tone: 'neutral' };
  const end = END[reason];
  // An end reason this build does not know yet is shown as the server sent it.
  return end
    ? { label: translate(end.key), tone: end.tone }
    : { label: reason, tone: 'neutral' };
}

export type TimelineRow = { label: string; at: string | null; done: boolean };

/**
 * The five moments of a delivery with their times. A moment that never came
 * (the trip was cancelled first) stays in the list, undone, so the rider
 * can see exactly where it stopped. The last row takes the end reason's name
 * when the trip did not end in a delivery.
 */
export function tripTimeline(trip: Trip): TimelineRow[] {
  const delivered = trip.end_reason === 'DELIVERED' || trip.end_reason == null;
  const finalAt = delivered ? trip.delivered_at : trip.ended_at;
  const rows: TimelineRow[] = [
    { label: translate('money.stepAccepted'), at: trip.accepted_at },
    { label: translate('money.stepReachedRestaurant'), at: trip.arrived_pickup_at },
    { label: translate('money.stepPickedUp'), at: trip.picked_up_at },
    { label: translate('money.stepReachedCustomer'), at: trip.arrived_drop_at },
    {
      label: delivered
        ? translate('money.endDelivered')
        : endLabel(trip.end_reason).label,
      at: finalAt,
    },
  ].map(r => ({ ...r, done: r.at !== null }));
  return rows;
}
