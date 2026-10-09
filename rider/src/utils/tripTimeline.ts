import type { Trip } from '@/types/api';

export type EndTone = 'success' | 'warning' | 'danger' | 'neutral';

const END: Record<string, { label: string; tone: EndTone }> = {
  DELIVERED: { label: 'Delivered', tone: 'success' },
  CUSTOMER_UNAVAILABLE: { label: 'Customer unavailable', tone: 'warning' },
  CANCELLED_BEFORE_PICKUP: { label: 'Cancelled', tone: 'danger' },
  CANCELLED_AFTER_PICKUP: { label: 'Cancelled', tone: 'danger' },
  REASSIGNED: { label: 'Reassigned', tone: 'neutral' },
};

/** How a trip ended, as a pill: one place for History, the detail screen and Home. */
export function endLabel(reason: string | null | undefined): {
  label: string;
  tone: EndTone;
} {
  if (!reason) return { label: 'Ended', tone: 'neutral' };
  return END[reason] ?? { label: reason, tone: 'neutral' };
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
    { label: 'Accepted', at: trip.accepted_at },
    { label: 'Reached restaurant', at: trip.arrived_pickup_at },
    { label: 'Picked up', at: trip.picked_up_at },
    { label: 'Reached customer', at: trip.arrived_drop_at },
    {
      label: delivered ? 'Delivered' : endLabel(trip.end_reason).label,
      at: finalAt,
    },
  ].map(r => ({ ...r, done: r.at !== null }));
  return rows;
}
