/**
 * The seed dataset behind the Marketing Hub while there is no backend.
 *
 * Everything here is *data*, never behaviour: `marketingApi.ts` owns the reads
 * and writes. Deleting this file and pointing that one at real endpoints is the
 * whole migration.
 *
 * Timestamps are computed relative to load rather than hard-coded, so the
 * dashboard always looks current no matter when the demo is opened — a fixed
 * date would have the "sent 3 days ago" campaign drift into last year.
 */

import type {
  Campaign,
  CampaignGoal,
  MarketingBranch,
  MarketingOffer,
  MarketingSegment,
  MessageTemplate,
} from './types';

const DAY_MS = 24 * 60 * 60 * 1000;

function iso(offsetDays: number, hour = 12, minute = 0): string {
  const date = new Date(Date.now() + offsetDays * DAY_MS);
  date.setHours(hour, minute, 0, 0);
  return date.toISOString();
}

export const MOCK_TIMEZONE = 'Asia/Kolkata';

/** Seven days, matching the backend's existing outcome-maturity default. */
export const ATTRIBUTION_WINDOW_DAYS = 7;

/** Below this a send is refused: too small to be useful, too small to be private. */
export const MINIMUM_SEGMENT_SIZE = 10;

/** Rolling cap used by the frequency-capping notice. */
export const FREQUENCY_CAP_PER_WEEK = 4;

export const MOCK_BRANCHES: MarketingBranch[] = [
  {
    id: 'branch-indiranagar',
    branch_name: 'Indiranagar',
    city: 'Bengaluru',
    state: 'Karnataka',
    is_active: true,
    opens_at: '11:00',
    closes_at: '23:00',
  },
  {
    id: 'branch-koramangala',
    branch_name: 'Koramangala',
    city: 'Bengaluru',
    state: 'Karnataka',
    is_active: true,
    opens_at: '12:00',
    closes_at: '22:00',
  },
  {
    id: 'branch-whitefield',
    branch_name: 'Whitefield',
    city: 'Bengaluru',
    state: 'Karnataka',
    is_active: false,
    opens_at: '12:00',
    closes_at: '21:00',
  },
];

export const MOCK_GOALS: CampaignGoal[] = [
  {
    key: 'WINBACK',
    label: 'Bring back customers who stopped ordering',
    description: 'Reach regulars who have gone quiet, usually with a small incentive.',
    default_segment: 'LAPSED_REGULARS',
    default_channels: ['PUSH'],
    success_metric: 'Orders from lapsed customers',
    suggests_offer: true,
  },
  {
    key: 'PROMOTE_DISH',
    label: 'Promote a specific dish',
    description: 'Push one item to the customers whose ordering already leans that way.',
    default_segment: 'DISH_FANS',
    default_channels: ['PUSH'],
    success_metric: 'Orders containing that dish',
    suggests_offer: true,
  },
  {
    key: 'NEW_ITEM',
    label: 'Announce a new menu item',
    description: 'Tell active customers about something that just went on the menu.',
    default_segment: 'BRANCH_CUSTOMERS',
    default_channels: ['PUSH'],
    success_metric: 'Orders containing the new item',
    suggests_offer: false,
  },
  {
    key: 'QUIET_DAY',
    label: 'Fill a quiet day or time',
    description: 'Nudge the people who already order in that window to come back to it.',
    default_segment: 'WEEKEND_DINERS',
    default_channels: ['PUSH'],
    success_metric: 'Orders in that window',
    suggests_offer: true,
  },
  {
    key: 'REWARD_VIPS',
    label: 'Reward my best customers',
    description: 'Thank the top spenders, with or without a perk.',
    default_segment: 'VIPS',
    default_channels: ['PUSH'],
    success_metric: 'Repeat rate among VIPs',
    suggests_offer: true,
  },
  {
    key: 'FIRST_TO_REGULAR',
    label: 'Turn first-timers into regulars',
    description: 'Chase the second order from people who have ordered exactly once.',
    default_segment: 'FIRST_TIME_BUYERS',
    default_channels: ['PUSH'],
    success_metric: 'Second orders placed',
    suggests_offer: true,
  },
  {
    key: 'ANNOUNCEMENT',
    label: 'General announcement',
    description: 'Hours, a closure, a new branch — news rather than a discount.',
    default_segment: 'BRANCH_CUSTOMERS',
    default_channels: ['PUSH'],
    success_metric: 'Delivered and opened',
    suggests_offer: false,
  },
  {
    key: 'CUSTOM',
    label: 'Something else',
    description: 'Write your own message and pick your own audience.',
    default_segment: 'BRANCH_CUSTOMERS',
    default_channels: ['PUSH'],
    success_metric: 'Delivered and opened',
    suggests_offer: false,
  },
];

export const MOCK_SEGMENTS: MarketingSegment[] = [
  {
    key: 'LAPSED_REGULARS',
    name: 'Lapsed regulars',
    definition: 'Ordered 3 or more times, but nothing in the last 30 days',
    total_members: 58,
    members_by_branch: {
      'branch-indiranagar': 34,
      'branch-koramangala': 21,
      'branch-whitefield': 3,
    },
    computed_at: iso(0, 6, 0),
  },
  {
    key: 'FIRST_TIME_BUYERS',
    name: 'First-time buyers',
    definition: 'Exactly one order, placed in the last 60 days',
    total_members: 96,
    members_by_branch: {
      'branch-indiranagar': 52,
      'branch-koramangala': 38,
      'branch-whitefield': 6,
    },
    computed_at: iso(0, 6, 0),
  },
  {
    key: 'VIPS',
    name: 'VIPs',
    definition: 'Top 10% by spend over the last 90 days',
    total_members: 41,
    members_by_branch: {
      'branch-indiranagar': 24,
      'branch-koramangala': 15,
      'branch-whitefield': 2,
    },
    computed_at: iso(0, 6, 0),
  },
  {
    key: 'BIG_SPENDERS',
    name: 'Big spenders',
    definition: 'Average order value above your restaurant median',
    total_members: 73,
    members_by_branch: {
      'branch-indiranagar': 40,
      'branch-koramangala': 28,
      'branch-whitefield': 5,
    },
    computed_at: iso(0, 6, 0),
  },
  {
    key: 'WEEKEND_DINERS',
    name: 'Weekend-only diners',
    definition: 'Orders concentrated on Friday, Saturday and Sunday',
    total_members: 112,
    members_by_branch: {
      'branch-indiranagar': 61,
      'branch-koramangala': 44,
      'branch-whitefield': 7,
    },
    computed_at: iso(0, 6, 0),
  },
  {
    key: 'DISH_FANS',
    name: 'Fans of Butter Chicken Biryani',
    definition: 'Repeat orders containing your most re-ordered dish',
    total_members: 67,
    members_by_branch: {
      'branch-indiranagar': 38,
      'branch-koramangala': 25,
      'branch-whitefield': 4,
    },
    computed_at: iso(0, 6, 0),
  },
  {
    key: 'BRANCH_CUSTOMERS',
    name: 'All branch customers',
    definition: 'Anyone who has ordered from the selected branches',
    total_members: 418,
    members_by_branch: {
      'branch-indiranagar': 233,
      'branch-koramangala': 164,
      'branch-whitefield': 21,
    },
    computed_at: iso(0, 6, 0),
  },
  {
    key: 'NEVER_ORDERED',
    name: 'Registered, never ordered',
    definition: 'Has an account but has never placed an order',
    total_members: 8,
    members_by_branch: {
      'branch-indiranagar': 5,
      'branch-koramangala': 3,
      'branch-whitefield': 0,
    },
    computed_at: iso(0, 6, 0),
  },
];

export const MOCK_OFFERS: MarketingOffer[] = [
  {
    id: 'offer-winback-20',
    name: 'Comeback 20% off',
    discount_label: '20% off',
    discount_type: 'PERCENTAGE',
    discount_value: 20,
    minimum_order_amount: 20,
    max_discount_amount: 12,
    valid_for_days: 5,
    applies_to: 'Whole order',
  },
  {
    id: 'offer-biryani-15',
    name: 'Biryani 15% off',
    discount_label: '15% off biryani',
    discount_type: 'PERCENTAGE',
    discount_value: 15,
    minimum_order_amount: 15,
    max_discount_amount: 8,
    valid_for_days: 7,
    applies_to: 'Biryani category',
  },
  {
    id: 'offer-flat-5',
    name: 'Flat $5 off',
    discount_label: '$5 off',
    discount_type: 'FLAT',
    discount_value: 5,
    minimum_order_amount: 25,
    max_discount_amount: 5,
    valid_for_days: 3,
    applies_to: 'Whole order',
  },
  {
    id: 'offer-welcome-25',
    name: 'Second order 25% off',
    discount_label: '25% off',
    discount_type: 'PERCENTAGE',
    discount_value: 25,
    minimum_order_amount: 18,
    max_discount_amount: 10,
    valid_for_days: 10,
    applies_to: 'Whole order',
  },
];

/**
 * Starter copy, one per goal.
 *
 * `{first_name}` and `{branch}` are the merge fields the composer knows how to
 * preview; every one of them has a fallback so a customer with no name on file
 * still reads a complete sentence.
 */
export const MOCK_TEMPLATES: MessageTemplate[] = [
  {
    id: 'tpl-winback',
    name: 'We miss you',
    goal: 'WINBACK',
    channel: 'PUSH',
    title: 'We miss you, {first_name}!',
    body: 'Your favourite Butter Chicken Biryani is waiting — 20% off your next order until Sunday.',
  },
  {
    id: 'tpl-winback-short',
    name: 'Short and direct',
    goal: 'WINBACK',
    channel: 'PUSH',
    title: 'Still thinking about that biryani?',
    body: 'It has been a while, {first_name}. Here is 20% off to tempt you back to {branch}.',
  },
  {
    id: 'tpl-dish',
    name: 'Dish spotlight',
    goal: 'PROMOTE_DISH',
    channel: 'PUSH',
    title: 'Butter Chicken Biryani, fresh off the pan',
    body: 'Our most re-ordered dish is on tonight at {branch}. Order before the kitchen closes.',
  },
  {
    id: 'tpl-new-item',
    name: 'New on the menu',
    goal: 'NEW_ITEM',
    channel: 'PUSH',
    title: 'New on the menu at {branch}',
    body: 'We have added something we think you will like, {first_name}. Take a look.',
  },
  {
    id: 'tpl-quiet-day',
    name: 'Quiet night nudge',
    goal: 'QUIET_DAY',
    channel: 'PUSH',
    title: 'Tonight only at {branch}',
    body: 'The kitchen is quiet and the food is fast. Order in the next two hours and save.',
  },
  {
    id: 'tpl-vip',
    name: 'VIP thank you',
    goal: 'REWARD_VIPS',
    channel: 'PUSH',
    title: 'Thank you, {first_name}',
    body: 'You are one of our regulars, and we noticed. Here is something on us.',
  },
  {
    id: 'tpl-second-order',
    name: 'Second order nudge',
    goal: 'FIRST_TO_REGULAR',
    channel: 'PUSH',
    title: 'How was your first order?',
    body: 'Come back for a second, {first_name} — 25% off, on us.',
  },
  {
    id: 'tpl-announcement',
    name: 'Plain announcement',
    goal: 'ANNOUNCEMENT',
    channel: 'PUSH',
    title: 'A quick update from {branch}',
    body: 'Write what you need your customers to know.',
  },
  {
    id: 'tpl-blank',
    name: 'Start from blank',
    goal: 'CUSTOM',
    channel: 'PUSH',
    title: '',
    body: '',
  },
];

function trend(values: number[]): Array<{ label: string; value: number; meta?: string }> {
  return values.map((value, index) => {
    const date = new Date(Date.now() - (values.length - 1 - index) * DAY_MS);
    const label = date.toLocaleDateString('en-CA', { day: 'numeric', month: 'short' });
    return { label, value, meta: label };
  });
}

export const MOCK_REVENUE_TREND = trend([
  0, 0, 210, 180, 90, 0, 0, 340, 520, 410, 260, 120, 60, 0, 0, 0, 180, 640, 880,
  720, 430, 210, 90, 0, 0, 260, 540, 760, 610, 380,
]);

/**
 * Three campaigns in three different states, so every screen has something
 * real to render: one sent with a full report, one scheduled, one draft.
 */
export const MOCK_CAMPAIGNS: Campaign[] = [
  {
    id: 'cmp-winback-sep',
    name: 'September winback — Indiranagar',
    goal: 'WINBACK',
    segment_key: 'LAPSED_REGULARS',
    branch_ids: ['branch-indiranagar'],
    offer_id: 'offer-winback-20',
    channels: ['PUSH'],
    content: {
      title: 'We miss you, {first_name}!',
      body: 'Your favourite Butter Chicken Biryani is waiting — 20% off your next order until Sunday.',
      deep_link: 'OFFERS',
      template_id: 'tpl-winback',
      extra: {},
    },
    schedule: { mode: 'SCHEDULED', send_at: iso(-9, 18, 30), timezone: MOCK_TIMEZONE },
    status: 'SENT',
    created_at: iso(-11, 15, 20),
    updated_at: iso(-9, 18, 30),
    sent_at: iso(-9, 18, 30),
    created_by: 'You',
    audience_size: 34,
    delivery: {
      sent: 34,
      delivered: 31,
      opened: 19,
      clicked: 14,
      failed: 3,
      unsubscribed: 1,
    },
    failure_reasons: [
      { reason: 'App uninstalled', count: 2 },
      { reason: 'Notifications turned off', count: 1 },
    ],
    attribution: {
      window_days: ATTRIBUTION_WINDOW_DAYS,
      window_open: false,
      orders: 6,
      revenue: 1218,
      discount_given: 214,
      net_revenue: 1004,
      average_order_value: 203,
      baseline_orders: 1,
      returning_customers: 6,
      new_customers: 0,
      daily: [
        { label: 'Day 1', revenue: 486, orders: 2 },
        { label: 'Day 2', revenue: 312, orders: 2 },
        { label: 'Day 3', revenue: 210, orders: 1 },
        { label: 'Day 4', revenue: 0, orders: 0 },
        { label: 'Day 5', revenue: 210, orders: 1 },
        { label: 'Day 6', revenue: 0, orders: 0 },
        { label: 'Day 7', revenue: 0, orders: 0 },
      ],
    },
    last_error: null,
    sending_progress: null,
    social: null,
  },
  {
    id: 'cmp-biryani-friday',
    name: 'Friday biryani push',
    goal: 'PROMOTE_DISH',
    segment_key: 'DISH_FANS',
    branch_ids: ['branch-indiranagar', 'branch-koramangala'],
    offer_id: 'offer-biryani-15',
    channels: ['PUSH'],
    content: {
      title: 'Butter Chicken Biryani, fresh off the pan',
      body: 'Our most re-ordered dish is on tonight at {branch}. Order before the kitchen closes.',
      deep_link: 'MENU_ITEM',
      template_id: 'tpl-dish',
      extra: {},
    },
    schedule: { mode: 'SCHEDULED', send_at: iso(2, 18, 0), timezone: MOCK_TIMEZONE },
    status: 'SCHEDULED',
    created_at: iso(-1, 11, 5),
    updated_at: iso(-1, 11, 5),
    sent_at: null,
    created_by: 'You',
    audience_size: 63,
    delivery: null,
    failure_reasons: [],
    attribution: null,
    last_error: null,
    sending_progress: null,
    social: null,
  },
  {
    id: 'cmp-vip-draft',
    name: 'VIP thank you (draft)',
    goal: 'REWARD_VIPS',
    segment_key: 'VIPS',
    branch_ids: ['branch-indiranagar'],
    offer_id: null,
    channels: ['PUSH'],
    content: {
      title: 'Thank you, {first_name}',
      body: 'You are one of our regulars, and we noticed. Here is something on us.',
      deep_link: 'RESTAURANT_HOME',
      template_id: 'tpl-vip',
      extra: {},
    },
    schedule: { mode: 'NOW', send_at: null, timezone: MOCK_TIMEZONE },
    status: 'DRAFT',
    created_at: iso(-3, 16, 45),
    updated_at: iso(-2, 9, 10),
    sent_at: null,
    created_by: 'You',
    audience_size: 24,
    delivery: null,
    failure_reasons: [],
    attribution: null,
    last_error: null,
    sending_progress: null,
    social: null,
  },
  {
    id: 'cmp-newitem-aug',
    name: 'New paneer roll launch',
    goal: 'NEW_ITEM',
    segment_key: 'BRANCH_CUSTOMERS',
    branch_ids: ['branch-indiranagar', 'branch-koramangala'],
    offer_id: null,
    channels: ['PUSH'],
    content: {
      title: 'New on the menu at {branch}',
      body: 'We have added something we think you will like, {first_name}. Take a look.',
      deep_link: 'MENU_ITEM',
      template_id: 'tpl-new-item',
      extra: {},
    },
    schedule: { mode: 'SCHEDULED', send_at: iso(-24, 17, 0), timezone: MOCK_TIMEZONE },
    status: 'SENT',
    created_at: iso(-26, 10, 0),
    updated_at: iso(-24, 17, 0),
    sent_at: iso(-24, 17, 0),
    created_by: 'You',
    audience_size: 397,
    delivery: {
      sent: 397,
      delivered: 361,
      opened: 174,
      clicked: 88,
      failed: 36,
      unsubscribed: 4,
    },
    failure_reasons: [
      { reason: 'App uninstalled', count: 29 },
      { reason: 'Notifications turned off', count: 7 },
    ],
    attribution: {
      window_days: ATTRIBUTION_WINDOW_DAYS,
      window_open: false,
      orders: 23,
      revenue: 2894,
      discount_given: 0,
      net_revenue: 2894,
      average_order_value: 126,
      baseline_orders: 11,
      returning_customers: 19,
      new_customers: 4,
      daily: [
        { label: 'Day 1', revenue: 1120, orders: 9 },
        { label: 'Day 2', revenue: 638, orders: 5 },
        { label: 'Day 3', revenue: 392, orders: 3 },
        { label: 'Day 4', revenue: 254, orders: 2 },
        { label: 'Day 5', revenue: 264, orders: 2 },
        { label: 'Day 6', revenue: 126, orders: 1 },
        { label: 'Day 7', revenue: 100, orders: 1 },
      ],
    },
    last_error: null,
    sending_progress: null,
    social: null,
  },
  {
    id: 'cmp-failed-test',
    name: 'Whitefield reopening notice',
    goal: 'ANNOUNCEMENT',
    segment_key: 'BRANCH_CUSTOMERS',
    branch_ids: ['branch-whitefield'],
    offer_id: null,
    channels: ['PUSH'],
    content: {
      title: 'A quick update from {branch}',
      body: 'Whitefield is back open from Monday. We have missed you.',
      deep_link: 'RESTAURANT_HOME',
      template_id: 'tpl-announcement',
      extra: {},
    },
    schedule: { mode: 'NOW', send_at: null, timezone: MOCK_TIMEZONE },
    status: 'FAILED',
    created_at: iso(-5, 14, 0),
    updated_at: iso(-5, 14, 2),
    sent_at: iso(-5, 14, 2),
    created_by: 'You',
    audience_size: 21,
    delivery: {
      sent: 21,
      delivered: 0,
      opened: 0,
      clicked: 0,
      failed: 21,
      unsubscribed: 0,
    },
    failure_reasons: [{ reason: 'No active devices for this audience', count: 21 }],
    attribution: null,
    last_error:
      'None of the 21 customers at this branch have the app installed with notifications on.',
    sending_progress: null,
    social: null,
  },
];
