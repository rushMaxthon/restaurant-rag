/**
 * Everything the guide says, in one place.
 *
 * A tour is a few steps, each pointing at a control a screen registers under
 * one of these TARGETS. The copy is written for a rider reading it on a bike
 * stand: what the thing is, then what to do with it, in one line. Keeping it
 * all here is also what makes a translation layer later a one-file job.
 */

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

export type TourStep = { target: TargetId; title: string; body: string };
export type Tour = { steps: TourStep[] };

export const TOURS = {
  home: {
    steps: [
      {
        target: TARGETS.homeToggle,
        title: 'Go online to get orders',
        body: "Tap here at the start of your shift. Orders only come while you're online.",
      },
      {
        target: TARGETS.homeToday,
        title: "What you've made today",
        body: 'Updates after every delivery. The Earnings tab has the whole week.',
      },
      {
        target: TARGETS.tabOrders,
        title: 'Orders waiting near you',
        body: "Any order nobody has taken yet. Take one from here when you're online and free.",
      },
    ],
  },
  orders: {
    steps: [
      {
        target: TARGETS.ordersTake,
        title: 'Take an order',
        body: 'Looking is free. Taking needs you online with no delivery in hand.',
      },
    ],
  },
  trip: {
    steps: [
      {
        target: TARGETS.tripSteps,
        title: 'Your four stops',
        body: 'Restaurant, collect, customer, deliver. The bar fills as you go.',
      },
      {
        target: TARGETS.tripSlide,
        title: "Slide when you're there",
        body: "Only slide once you've actually arrived. It tells the customer where their food is.",
      },
    ],
  },
  otp: {
    steps: [
      {
        target: TARGETS.tripOtp,
        title: 'Ask for the code',
        body: "The customer has a 4-digit code on their order page. Type it and you're paid.",
      },
    ],
  },
  earnings: {
    steps: [
      {
        target: TARGETS.earningsUnpaid,
        title: 'To be paid',
        body: "Everything you've earned that hasn't reached your bank yet. Payments appear below.",
      },
    ],
  },
} satisfies Record<string, Tour>;

export type TourId = keyof typeof TOURS;
/** The intro cards are a tour too, for the seen-flags; they have no spotlight steps. */
export const INTRO_ID = 'intro';
