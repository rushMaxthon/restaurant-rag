import type { IconName } from '@components/ui/Icon';
import type { Key } from '@/i18n/strings';
import { translate } from '@/i18n/translate';
import type { TripAction, TripStep } from '@/types/api';

export type Slide = { action: TripAction; label: string; icon: IconName; tone?: 'success' };

/**
 * The one big slide at the bottom of a trip: what the rider has just done at
 * this stop. The server enforces the order (`out_of_order`); this only makes
 * sure the screen never offers a step the server would refuse. At the door
 * there is no slide - delivering takes the customer's code.
 */
const SLIDES: Partial<Record<TripStep, Omit<Slide, 'label'> & { label: Key }>> = {
  to_pickup: { action: 'arrived-pickup', label: 'trip.slideArrivedPickup', icon: 'restaurant' },
  at_pickup: { action: 'picked-up', label: 'trip.slidePickedUp', icon: 'bag-check' },
  to_drop: { action: 'arrived-drop', label: 'trip.slideArrivedDrop', icon: 'home', tone: 'success' },
};

/** The label is translated at call time, so a language switch shows at once. */
export function nextSlide(step: TripStep): Slide | null {
  const slide = SLIDES[step];
  return slide ? { ...slide, label: translate(slide.label) } : null;
}

const PROGRESS: Record<TripStep, { current: number; label: Key }> = {
  to_pickup: { current: 1, label: 'trip.stepToPickup' },
  at_pickup: { current: 2, label: 'trip.stepAtPickup' },
  to_drop: { current: 3, label: 'trip.stepToDrop' },
  at_drop: { current: 4, label: 'trip.stepAtDrop' },
  done: { current: 4, label: 'trip.stepDone' },
};

/**
 * The thin progress line at the top of a trip: "2 of 4 · At the restaurant".
 * It replaced a row of four labelled circles that took a whole card to say
 * the same thing.
 */
export function stepProgress(step: TripStep): {
  current: number;
  total: number;
  label: string;
} {
  const { current, label } = PROGRESS[step];
  return { current, total: 4, label: translate(label) };
}
