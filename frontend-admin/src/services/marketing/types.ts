/**
 * The Marketing Hub's domain vocabulary, as the UI needs it.
 *
 * These are deliberately shaped like the responses a `/api/marketing/*` route
 * would return rather than like React state: snake_case fields, ids not object
 * references, money as numbers. When the backend arrives, `marketingApi.ts` is
 * the only file that has to change — every component already speaks this.
 *
 * A campaign names exactly one channel. `Campaign.channels` stays a list
 * because that is the column and the wire format the backend already has, but
 * every read goes through `primaryChannel()` and every write sends a
 * single-entry list. One channel means one content format, one preview and one
 * set of rules, which is the whole reason the flow asks for it first — a draft
 * holding both an Instagram caption and a 65-character push title has no
 * coherent editor and no coherent report.
 *
 * Which channels can actually send is a fact about the restaurant, not about
 * this build: it comes from `GET /marketing/channels`, per restaurant. A
 * channel that is not connected can still be planned, written and saved in
 * full, and is refused at the send step alone.
 */

export type MarketingChannel =
  | 'PUSH'
  | 'EMAIL'
  | 'SMS'
  | 'WHATSAPP'
  | 'FACEBOOK'
  | 'INSTAGRAM';

/** Exactly the statuses the backend's campaign enum already defines. */
export type CampaignStatus =
  | 'DRAFT'
  | 'SCHEDULED'
  | 'SENDING'
  | 'SENT'
  | 'CANCELLED'
  | 'FAILED';

export type CampaignGoalKey =
  | 'WINBACK'
  | 'PROMOTE_DISH'
  | 'NEW_ITEM'
  | 'QUIET_DAY'
  | 'REWARD_VIPS'
  | 'FIRST_TO_REGULAR'
  | 'ANNOUNCEMENT'
  | 'CUSTOM';

export type SegmentKey =
  | 'LAPSED_REGULARS'
  | 'FIRST_TIME_BUYERS'
  | 'VIPS'
  | 'BIG_SPENDERS'
  | 'WEEKEND_DINERS'
  | 'DISH_FANS'
  | 'BRANCH_CUSTOMERS'
  | 'NEVER_ORDERED';

export type ScheduleMode = 'NOW' | 'SCHEDULED';

export interface CampaignGoal {
  key: CampaignGoalKey;
  /** What the owner reads. Never marketing jargon. */
  label: string;
  description: string;
  /** Pre-selected when this goal is chosen. */
  default_segment: SegmentKey;
  default_channels: MarketingChannel[];
  /** What the campaign is judged on, in the owner's words. */
  success_metric: string;
  /** Suggests a discount when true; news-style goals do not. */
  suggests_offer: boolean;
}

export interface MarketingSegment {
  key: SegmentKey;
  name: string;
  /** One line, in the owner's terms — no rule syntax. */
  definition: string;
  /** Members across every branch. Branch filtering narrows it. */
  total_members: number;
  /** Per-branch member counts, keyed by branch id. */
  members_by_branch: Record<string, number>;
  /** ISO timestamp of the last recount. */
  computed_at: string;
}

export interface MarketingBranch {
  id: string;
  branch_name: string;
  city: string;
  state: string;
  is_active: boolean;
  /** Drives the "this branch is closed then" scheduling warning. */
  opens_at: string;
  closes_at: string;
}

export interface MarketingOffer {
  id: string;
  name: string;
  discount_label: string;
  /** Percentage off, or a flat amount — `discount_type` says which. */
  discount_type: 'PERCENTAGE' | 'FLAT';
  discount_value: number;
  minimum_order_amount: number;
  /** Worst-case discount on a single order, for exposure maths. */
  max_discount_amount: number;
  valid_for_days: number;
  applies_to: string;
}

export interface MessageTemplate {
  id: string;
  name: string;
  goal: CampaignGoalKey;
  channel: MarketingChannel;
  title: string;
  body: string;
}

/**
 * One channel's reachability for a chosen audience.
 *
 * `reachable` is always lower than the segment's member count, and the gap is
 * itemised in `blockers` — the owner should never wonder where people went.
 */
export interface ChannelReach {
  channel: MarketingChannel;
  available: boolean;
  /** Why the channel cannot be used at all, when `available` is false. */
  unavailable_reason?: string;
  reachable: number;
  blockers: Array<{ reason: string; count: number }>;
  /** Estimated spend in the restaurant's currency. Zero for push. */
  estimated_cost: number;
}

export type NoticeTone = 'block' | 'warn' | 'info';

/**
 * A pre-send check result. `block` stops the send; `warn` and `info` do not.
 *
 * In production these are re-run server-side — the UI only surfaces them.
 */
export interface CampaignNotice {
  id: string;
  tone: NoticeTone;
  title: string;
  description: string;
}

export interface ReachEstimate {
  segment_members: number;
  /** After branch filtering, before per-channel consent. */
  audience_size: number;
  channels: ChannelReach[];
  notices: CampaignNotice[];
  /** Below this the send is blocked outright. */
  minimum_segment_size: number;
}

export interface CampaignContent {
  /** Headline, subject or WhatsApp header. Empty on channels with none. */
  title: string;
  body: string;
  /** Where tapping the notification lands the customer. */
  deep_link: CampaignDeepLink;
  template_id: string | null;
  /** Everything this channel needs that a push notification does not. */
  extra: CampaignContentExtra;
}

/**
 * The per-channel tail of a campaign, as one open bag rather than six columns.
 *
 * A photo, a hashtag block and a boost budget are each meaningful on exactly
 * one or two channels, and adding a nullable column per channel would mean a
 * migration every time a channel is added. The backend carries this through to
 * `push_notification_campaigns.data_payload` — JSONB that already exists —
 * without interpreting it, so a field can be added here alone.
 *
 * The boost fields live here rather than beside the segment because a boosted
 * post has no segment: `segment_key` is still stored for a social campaign,
 * but nothing reads it. Two passthrough bags would be worse than one.
 */
export interface CampaignContentExtra {
  /** The photo a post is built around. Required on Instagram. */
  image_url?: string | null;
  hashtags?: string | null;
  /** Hashtags in the first comment keeps the caption clean — an IG habit. */
  hashtags_in_comment?: boolean;
  /** The button on a Facebook link card. */
  cta_label?: string | null;
  link_url?: string | null;
  /** How a public post is attributed, since it writes no recipient rows. */
  promo_code?: string | null;
  /** Null when the post is organic. Money, so it is never inferred. */
  boost_budget?: number | null;
  boost_days?: number | null;
  boost_radius_km?: number | null;
}

export type CampaignDeepLink =
  | 'RESTAURANT_HOME'
  | 'MENU_ITEM'
  | 'OFFERS'
  | 'CART';

export interface CampaignSchedule {
  mode: ScheduleMode;
  /** ISO timestamp. Null when `mode` is NOW. */
  send_at: string | null;
  timezone: string;
}

export interface CampaignDraft {
  id: string;
  name: string;
  /** Chosen first, and never a list: see the note at the top of this file. */
  channel: MarketingChannel;
  goal: CampaignGoalKey;
  segment_key: SegmentKey;
  branch_ids: string[];
  offer_id: string | null;
  content: CampaignContent;
  schedule: CampaignSchedule;
  /**
   * How far through the wizard this draft got, so it resumes in place.
   *
   * 1-6, matching the six questions: where, what for, who, what, when, ready.
   * The channel screen is step 1 and is stored like any other, so a draft
   * abandoned on it reopens there rather than on a goal for no channel.
   */
  last_step: number;
}

export interface DeliveryBreakdown {
  sent: number;
  delivered: number;
  opened: number;
  clicked: number;
  failed: number;
  unsubscribed: number;
}

export interface FailureReason {
  reason: string;
  count: number;
}

export interface AttributionReport {
  /** Days after the send in which an order still counts. */
  window_days: number;
  /** True while the window is still open and figures may still rise. */
  window_open: boolean;
  orders: number;
  revenue: number;
  discount_given: number;
  net_revenue: number;
  average_order_value: number;
  /** Baseline for the same audience without a campaign, for comparison. */
  baseline_orders: number;
  returning_customers: number;
  new_customers: number;
  /** Day-by-day attributed revenue, for the trend chart. */
  daily: Array<{ label: string; revenue: number; orders: number }>;
}

export interface Campaign {
  id: string;
  name: string;
  goal: CampaignGoalKey;
  segment_key: SegmentKey;
  branch_ids: string[];
  offer_id: string | null;
  /** One entry. Read it with `primaryChannel`, which copes with none. */
  channels: MarketingChannel[];
  content: CampaignContent;
  schedule: CampaignSchedule;
  status: CampaignStatus;
  created_at: string;
  updated_at: string;
  /** Set once the campaign actually went out. */
  sent_at: string | null;
  created_by: string;
  audience_size: number;
  /** Null until the campaign has sent. */
  delivery: DeliveryBreakdown | null;
  failure_reasons: FailureReason[];
  attribution: AttributionReport | null;
  /** Populated when status is FAILED. */
  last_error: string | null;
  /** Progress 0-1 while SENDING, so the list can show a live bar. */
  sending_progress: number | null;
  /** Set only on a social campaign. See `SocialPost`. */
  social: SocialPost | null;
}

export interface MarketingDashboard {
  attributed_revenue_30d: number;
  attributed_revenue_previous_30d: number;
  campaigns_sent_30d: number;
  attributed_orders_30d: number;
  /** Null when nothing has been sent yet — drives the empty state. */
  best_campaign: { id: string; name: string; net_revenue: number } | null;
  /** Things the owner should act on: a send tomorrow, a failure, a draft. */
  attention: Array<{
    id: string;
    tone: NoticeTone;
    title: string;
    description: string;
    campaign_id: string | null;
  }>;
  revenue_trend: Array<{ label: string; value: number; meta?: string }>;
}

export type ChannelFamily = 'DIRECT' | 'SOCIAL';

/** How far a restaurant has got with switching a channel on. */
export type ChannelConnectionStatus = 'CONNECTED' | 'DISABLED' | 'ERROR';

/**
 * One thing the owner has to supply before a channel can send.
 *
 * `secret` is why the connect form can show a saved sender name and leave the
 * saved token blank: a stored credential cannot be displayed, and re-saving
 * without retyping it must not blank it. The backend merges rather than
 * replaces for exactly that reason.
 */
export interface ConnectionField {
  key: string;
  label: string;
  example: string;
  secret: boolean;
  required: boolean;
  help: string;
}

/**
 * One channel's state for the current restaurant.
 *
 * Carries `config` and never credentials — enough to render "sending as
 * @spiceroute", never enough to send as them from somewhere else.
 */
export interface ChannelConnection {
  channel: MarketingChannel;
  family: ChannelFamily;
  /** Whether a campaign on this channel can actually leave the building. */
  connected: boolean;
  status: ChannelConnectionStatus | null;
  config: Record<string, string | number | null>;
  /** Who the customer sees it from. Null when nothing identifies it yet. */
  identity: string | null;
  connected_at: string | null;
  /** When the credentials were last proven against the real provider. */
  verified_at: string | null;
  last_error: string | null;
  requirements: ConnectionField[];
}

/**
 * The public post a social campaign produced.
 *
 * Null on every direct campaign, and the two are never both set: a campaign
 * is a message to people or a post to nobody.
 */
export interface SocialPost {
  state: 'PENDING' | 'PUBLISHED' | 'FAILED' | null;
  post_id: string | null;
  permalink: string | null;
  published_at: string | null;
  /** True when sending was switched off, so nothing was actually posted. */
  dry_run: boolean;
  reason: string | null;
  /** How this post is attributed, since it writes no recipient rows. */
  promo_code: string | null;
  /** Whatever the platform served. A metric it dropped is absent, not zero. */
  insights: Record<string, number>;
  insights_updated_at: string | null;
}

export interface TestSendResult {
  channel: MarketingChannel;
  destination: string;
  sent_at: string;
}
