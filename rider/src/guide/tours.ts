/**
 * Everything the guide says, in one place.
 *
 * A tour is a few steps, each pointing at a control a screen registers under
 * one of these TARGETS. The copy is written for a rider reading it on a bike
 * stand: what the thing is, then what to do with it, in one line. The words
 * themselves live in `i18n/strings/account.ts`; a step holds KEYS, resolved
 * with t() where the tip is drawn, so a language switch reaches a tour that
 * was declared before it.
 */

import type { Key } from '@/i18n/strings';

export const TARGETS = {
  homeToggle: 'home.toggle',
  homeToday: 'home.today',
  tabOrders: 'tab.orders',
  ordersTake: 'orders.take',
  tripSteps: 'trip.steps',
  tripSlide: 'trip.slide',
  tripOtp: 'trip.otp',
  earningsUnpaid: 'earnings.unpaid',
} as const;

export type TargetId = (typeof TARGETS)[keyof typeof TARGETS];

export type TourStep = { target: TargetId; titleKey: Key; bodyKey: Key };
/** `tabbed`: the floating tab bar covers the bottom of this screen, so a control under it is not visible. */
export type Tour = { steps: TourStep[]; tabbed?: boolean };

const tours = {
  home: {
    tabbed: true,
    steps: [
      {
        target: TARGETS.homeToggle,
        titleKey: 'account.tip.homeToggleTitle',
        bodyKey: 'account.tip.homeToggleBody',
      },
      {
        target: TARGETS.homeToday,
        titleKey: 'account.tip.homeTodayTitle',
        bodyKey: 'account.tip.homeTodayBody',
      },
      {
        target: TARGETS.tabOrders,
        titleKey: 'account.tip.tabOrdersTitle',
        bodyKey: 'account.tip.tabOrdersBody',
      },
    ],
  },
  orders: {
    tabbed: true,
    steps: [
      {
        target: TARGETS.ordersTake,
        titleKey: 'account.tip.ordersTakeTitle',
        bodyKey: 'account.tip.ordersTakeBody',
      },
    ],
  },
  trip: {
    tabbed: false,
    steps: [
      {
        target: TARGETS.tripSteps,
        titleKey: 'account.tip.tripStepsTitle',
        bodyKey: 'account.tip.tripStepsBody',
      },
      {
        target: TARGETS.tripSlide,
        titleKey: 'account.tip.tripSlideTitle',
        bodyKey: 'account.tip.tripSlideBody',
      },
    ],
  },
  otp: {
    tabbed: false,
    steps: [
      {
        target: TARGETS.tripOtp,
        titleKey: 'account.tip.tripOtpTitle',
        bodyKey: 'account.tip.tripOtpBody',
      },
    ],
  },
  earnings: {
    tabbed: true,
    steps: [
      {
        target: TARGETS.earningsUnpaid,
        titleKey: 'account.tip.earningsUnpaidTitle',
        bodyKey: 'account.tip.earningsUnpaidBody',
      },
    ],
  },
} satisfies Record<string, Tour>;

// Widened to Tour: each step literal-typed (target AND keys) would make every
// step a different type, and GuideProvider handles them as one TourStep.
export const TOURS: Record<keyof typeof tours, Tour> = tours;

export type TourId = keyof typeof TOURS;
/** The intro cards are a tour too, for the seen-flags; they have no spotlight steps. */
export const INTRO_ID = 'intro';
