import type { IconName } from '@components/ui/Icon';
import type { TripAction, TripStep } from '@/types/api';

export type Slide = { action: TripAction; label: string; icon: IconName; tone?: 'success' };

/**
 * The one big slide at the bottom of a trip: what the rider has just done at
 * this stop. The server enforces the order (`out_of_order`); this only makes
 * sure the screen never offers a step the server would refuse. At the door
 * there is no slide - delivering takes the customer's code.
 */
const SLIDES: Partial<Record<TripStep, Slide>> = {
  to_pickup: { action: 'arrived-pickup', label: 'Arrived at restaurant', icon: 'restaurant' },
  at_pickup: { action: 'picked-up', label: 'Picked up the order', icon: 'bag-check' },
  to_drop: { action: 'arrived-drop', label: 'Arrived at customer', icon: 'home', tone: 'success' },
};

export function nextSlide(step: TripStep): Slide | null {
  return SLIDES[step] ?? null;
}
