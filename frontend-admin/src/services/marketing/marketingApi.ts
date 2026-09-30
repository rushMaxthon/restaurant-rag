/**
 * The Marketing Hub's data layer — mock today, HTTP tomorrow.
 *
 * Every screen talks to this module and nothing else, so swapping to the real
 * backend is a rewrite of the function bodies here rather than a change to any
 * component. The shapes are the ones `types.ts` documents, the calls are
 * promise-based and can reject, and none of them is synchronous — all three
 * properties a real `fetch` layer has and a plain object does not. A component
 * written against a synchronous mock has to be rebuilt when the network
 * arrives; one written against this does not.
 *
 * `demoMode` is the other half of that: it forces the empty, slow and failing
 * paths that are otherwise impossible to reach without a broken server, so the
 * loading, empty and error states are reviewable rather than theoretical. It
 * has no counterpart in production and is the one thing here that is deleted
 * rather than rewritten.
 */

import {
  ATTRIBUTION_WINDOW_DAYS,
  FREQUENCY_CAP_PER_WEEK,
  MINIMUM_SEGMENT_SIZE,
  MOCK_BRANCHES,
  MOCK_CAMPAIGNS,
  MOCK_GOALS,
  MOCK_OFFERS,
  MOCK_REVENUE_TREND,
  MOCK_SEGMENTS,
  MOCK_TEMPLATES,
  MOCK_TIMEZONE,
} from './mockData';
import * as live from './marketingClient';
import type {
  AttributionReport,
  Campaign,
  ChannelConnection,
  CampaignDraft,
  CampaignGoal,
  CampaignGoalKey,
  CampaignNotice,
  CampaignStatus,
  ChannelReach,
  MarketingBranch,
  MarketingChannel,
  MarketingDashboard,
  MarketingOffer,
  MarketingSegment,
  MessageTemplate,
  ReachEstimate,
  SegmentKey,
  TestSendResult,
} from './types';

export class MarketingApiError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'MarketingApiError';
  }
}

/* -------------------------------------------------------------------------- */
/* Demo controls                                                              */
/* -------------------------------------------------------------------------- */

export type DemoMode = 'normal' | 'slow' | 'empty' | 'error';

const DEMO_MODE_EVENT = 'marketing-demo-mode-change';

let demoMode: DemoMode = 'normal';

export function getDemoMode(): DemoMode {
  return demoMode;
}

export function setDemoMode(mode: DemoMode): void {
  demoMode = mode;
  window.dispatchEvent(new CustomEvent(DEMO_MODE_EVENT));
}

/** Lets a page re-fetch when the reviewer flips the state selector. */
export function subscribeToDemoMode(listener: () => void): () => void {
  window.addEventListener(DEMO_MODE_EVENT, listener);
  return () => window.removeEventListener(DEMO_MODE_EVENT, listener);
}

/* -------------------------------------------------------------------------- */
/* Transport simulation                                                        */
/* -------------------------------------------------------------------------- */

function latency(): number {
  if (demoMode === 'slow') {
    return 2200;
  }
  // Enough to see a skeleton, not enough to be annoying in review.
  return 320;
}

async function respond<T>(produce: () => T): Promise<T> {
  await new Promise((resolve) => setTimeout(resolve, latency()));
  if (demoMode === 'error') {
    throw new MarketingApiError(
      'The marketing service did not respond. This is usually temporary.',
    );
  }
  return produce();
}

/* -------------------------------------------------------------------------- */
/* In-memory store                                                             */
/* -------------------------------------------------------------------------- */

/**
 * Mutations land here and survive navigation within a session, so scheduling a
 * campaign and then finding it in the list behaves the way it will against a
 * database. A reload resets it, which is the honest behaviour for mock data.
 */
let campaigns: Campaign[] = MOCK_CAMPAIGNS.map((campaign) => ({ ...campaign }));

function nextId(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 9)}`;
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function visibleCampaigns(): Campaign[] {
  return demoMode === 'empty' ? [] : campaigns;
}

/* -------------------------------------------------------------------------- */
/* Data source                                                                 */
/* -------------------------------------------------------------------------- */

/**
 * Which half of this module answers.
 *
 * `live` talks to `/api/marketing/*`. `mock` keeps the in-memory dataset, which
 * is still how the UI is reviewed without an API running, and still the only
 * source for the three calls the backend has not built yet.
 */
export type MarketingDataSource = 'live' | 'mock';

let dataSource: MarketingDataSource = 'live';

export function getDataSource(): MarketingDataSource {
  return dataSource;
}

export function setDataSource(next: MarketingDataSource): void {
  dataSource = next;
  // Reference data differs between the two, so a switch must not leave the
  // previous source's goals and branches on screen.
  referenceCache = null;
  window.dispatchEvent(new CustomEvent(DEMO_MODE_EVENT));
}

/**
 * Calls the backend has not implemented yet.
 *
 * Empty as of the dispatch, scheduling and attribution slices: every call in
 * this module now has a route behind it. Kept rather than deleted because the
 * UI reads it to decide what to warn about, and the next unbacked call should
 * be listed here rather than discovered by a user.
 */
export const UNBACKED_CALLS = [] as const;

/* -------------------------------------------------------------------------- */
/* Restaurant scope                                                            */
/* -------------------------------------------------------------------------- */

/**
 * Which restaurant the Hub is reading, for an ADMIN.
 *
 * An OWNER is pinned to their own restaurant by the backend and must leave this
 * null — `resolve_insights_scope` refuses an owner who names any restaurant,
 * even their own. An ADMIN has no implicit restaurant, so every marketing call
 * made without one comes back
 * `400 "restaurant_id is required for admin insights requests"`, which is what
 * the Hub showed instead of loading.
 *
 * Module state rather than a parameter on every call: the screens reach the
 * data layer through a façade whose signatures are shared with the mock, and
 * threading a scope through all of them would have split the two apart. It is
 * seeded from localStorage so a deep link straight to a campaign editor —
 * which has no restaurant picker of its own — is scoped before its first
 * fetch.
 */
const RESTAURANT_SCOPE_KEY = 'marketing:restaurant';

/**
 * Only a UUID is a usable scope.
 *
 * Whatever is here is appended to every `/marketing/*` request as
 * `restaurant_id`, where the backend types it as a UUID — so anything else
 * makes every call in the Hub fail validation, including the ones that would
 * let the admin pick a different restaurant. That is an unrecoverable state
 * reached by editing one localStorage key, so a malformed value is discarded
 * rather than sent.
 */
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

let restaurantScope: string | null = readStoredScope();

function readStoredScope(): string | null {
  try {
    const stored = window.localStorage.getItem(RESTAURANT_SCOPE_KEY);
    if (!stored) {
      return null;
    }
    if (!UUID_PATTERN.test(stored)) {
      window.localStorage.removeItem(RESTAURANT_SCOPE_KEY);
      return null;
    }
    return stored;
  } catch {
    // Private windows and blocked site data both throw here. An unscoped Hub
    // is the admin re-picking a restaurant, not a crashed screen.
    return null;
  }
}

export function getRestaurantScope(): string | null {
  return restaurantScope;
}

/**
 * Point the Hub at a restaurant, or clear it for an owner.
 *
 * Returns whether the scope actually changed, so a caller can avoid a reload
 * it does not need. Reference data is dropped on a real change: branches,
 * offers and segment counts all belong to the restaurant that was selected.
 */
export function setRestaurantScope(next: string | null): boolean {
  if (restaurantScope === next) {
    return false;
  }
  restaurantScope = next;
  referenceCache = null;
  try {
    if (next) {
      window.localStorage.setItem(RESTAURANT_SCOPE_KEY, next);
    } else {
      window.localStorage.removeItem(RESTAURANT_SCOPE_KEY);
    }
  } catch {
    // Remembering the choice is a convenience; failing to is not an error.
  }
  return true;
}

/* -------------------------------------------------------------------------- */
/* Reference data                                                              */
/* -------------------------------------------------------------------------- */

/**
 * Reference data is fetched once and then read synchronously.
 *
 * Goals, segments, branches, offers and templates are looked up *during render*
 * all over the Hub — `getSegment(campaign.segment_key).name` inside a table
 * cell, for instance. Making those lookups async would mean rewriting every
 * call site and threading loading state through components that have no
 * business knowing about it. Instead every async call below awaits
 * `ensureReference()` first, so by the time a page clears its loading flag the
 * cache is warm and the sync readers are correct.
 *
 * The readers fail soft rather than throwing: a render that somehow happens
 * before the cache is filled shows a placeholder, never a crashed screen.
 */
let referenceCache: live.MarketingReferencePayload | null = null;

function mockReference(): live.MarketingReferencePayload {
  return {
    goals: MOCK_GOALS,
    segments: MOCK_SEGMENTS,
    branches: MOCK_BRANCHES,
    offers: MOCK_OFFERS,
    templates: MOCK_TEMPLATES,
    minimum_segment_size: MINIMUM_SEGMENT_SIZE,
    frequency_cap_per_week: FREQUENCY_CAP_PER_WEEK,
    timezone: MOCK_TIMEZONE,
  };
}

export async function ensureReference(): Promise<void> {
  if (referenceCache) {
    return;
  }
  referenceCache =
    dataSource === 'live' ? await live.fetchReference() : mockReference();
  syncReferenceView();
}

/**
 * What `reference()` answers before anything has loaded, in live mode.
 *
 * Emphatically not the mock. Falling back to `mockReference()` meant that for
 * the window between mount and the first `/reference` response, every reader
 * got the demo dataset — and `emptyDraft()` reads branches during exactly that
 * window. The result was a new campaign seeded with `branch-indiranagar`,
 * which the backend rejects as "not a valid UUID". Mock data must never be
 * able to reach the wire in live mode, so the honest answer here is nothing.
 */
const EMPTY_REFERENCE: live.MarketingReferencePayload = {
  goals: [],
  segments: [],
  branches: [],
  offers: [],
  templates: [],
  minimum_segment_size: MINIMUM_SEGMENT_SIZE,
  frequency_cap_per_week: FREQUENCY_CAP_PER_WEEK,
  timezone: MOCK_TIMEZONE,
};

function reference(): live.MarketingReferencePayload {
  if (referenceCache) {
    return referenceCache;
  }
  return dataSource === 'live' ? EMPTY_REFERENCE : mockReference();
}

/** Whether real reference data has landed, so callers can wait for it. */
export function hasReference(): boolean {
  return referenceCache !== null;
}

export function listGoals(): CampaignGoal[] {
  return reference().goals;
}

/**
 * A placeholder goal, for the window before reference data has landed.
 *
 * Returning this rather than throwing is deliberate: these are called from
 * render, and an unknown key is a stale draft or a slow first paint, neither of
 * which should take the screen down.
 */
function placeholderGoal(key: CampaignGoalKey): CampaignGoal {
  return {
    key,
    label: 'Campaign',
    description: '',
    default_segment: 'BRANCH_CUSTOMERS',
    default_channels: ['PUSH'],
    success_metric: 'Delivered and opened',
    suggests_offer: false,
  };
}

export function getGoal(key: CampaignGoalKey): CampaignGoal {
  return reference().goals.find((entry) => entry.key === key) ?? placeholderGoal(key);
}

export function getSegment(key: SegmentKey): MarketingSegment {
  return (
    reference().segments.find((entry) => entry.key === key) ?? {
      key,
      name: 'Audience',
      definition: '',
      total_members: 0,
      members_by_branch: {},
      computed_at: new Date().toISOString(),
    }
  );
}

export function getBranch(id: string): MarketingBranch | null {
  return reference().branches.find((branch) => branch.id === id) ?? null;
}

export function getOffer(id: string | null): MarketingOffer | null {
  if (!id) {
    return null;
  }
  return reference().offers.find((offer) => offer.id === id) ?? null;
}

export function templatesForGoal(goal: CampaignGoalKey): MessageTemplate[] {
  const all = reference().templates;
  const matching = all.filter((template) => template.goal === goal);
  const blank = all.filter((template) => template.goal === 'CUSTOM');
  return matching.length > 0 ? [...matching, ...blank] : blank;
}

/**
 * The same object every render, mutated in place when reference data arrives.
 *
 * Screens read `marketingReference.branches` as a property during render, so
 * replacing the object would leave them holding the old one. Mutating keeps
 * one identity and lets the next render pick up real values.
 */
export const marketingReference = {
  goals: reference().goals,
  segments: reference().segments,
  branches: reference().branches,
  offers: reference().offers,
  templates: reference().templates,
  timezone: reference().timezone,
  // Not served by `/reference`: the attribution window belongs to slice 6 and
  // is still a client-side constant used only for wording.
  attributionWindowDays: ATTRIBUTION_WINDOW_DAYS,
  minimumSegmentSize: MINIMUM_SEGMENT_SIZE,
  frequencyCapPerWeek: FREQUENCY_CAP_PER_WEEK,
};

function syncReferenceView(): void {
  const next = reference();
  marketingReference.goals = next.goals;
  marketingReference.segments = next.segments;
  marketingReference.branches = next.branches;
  marketingReference.offers = next.offers;
  marketingReference.templates = next.templates;
  marketingReference.timezone = next.timezone;
  marketingReference.minimumSegmentSize = next.minimum_segment_size;
  marketingReference.frequencyCapPerWeek = next.frequency_cap_per_week;
}

/* -------------------------------------------------------------------------- */
/* Reach and pre-send checks                                                   */
/* -------------------------------------------------------------------------- */

export interface ReachInput {
  segment_key: SegmentKey;
  branch_ids: string[];
  channels: MarketingChannel[];
  goal: CampaignGoalKey;
  /** ISO timestamp, or null for "send now". Drives the timing warnings. */
  send_at: string | null;
}

/** What the mock pretends is connected: push, and nothing else. */
const MOCK_UNCONNECTED: Record<Exclude<MarketingChannel, 'PUSH'>, string> = {
  EMAIL: 'Email is not connected yet.',
  SMS: 'SMS is not connected yet.',
  WHATSAPP: 'WhatsApp is not connected yet.',
  FACEBOOK: 'Facebook is not connected yet.',
  INSTAGRAM: 'Instagram is not connected yet.',
};

function audienceFor(segmentKey: SegmentKey, branchIds: string[]): number {
  const segment = getSegment(segmentKey);
  if (branchIds.length === 0) {
    return 0;
  }
  return branchIds.reduce(
    (total, branchId) => total + (segment.members_by_branch[branchId] ?? 0),
    0,
  );
}

/**
 * Push reach, itemised.
 *
 * The proportions are fixed rather than random so the same audience always
 * produces the same number — a reach estimate that moved on every keystroke
 * would read as a bug.
 */
function pushReach(audience: number): ChannelReach {
  const noApp = Math.round(audience * 0.06);
  const notificationsOff = Math.round(audience * 0.04);
  const notOptedIn = Math.round(audience * 0.03);
  const reachable = Math.max(audience - noApp - notificationsOff - notOptedIn, 0);

  const blockers = [
    { reason: 'App not installed', count: noApp },
    { reason: 'Notifications turned off', count: notificationsOff },
    { reason: 'Not opted in to marketing', count: notOptedIn },
  ].filter((blocker) => blocker.count > 0);

  return {
    channel: 'PUSH',
    available: true,
    reachable,
    blockers,
    estimated_cost: 0,
  };
}

function timingNotices(sendAt: string | null, branchIds: string[]): CampaignNotice[] {
  if (!sendAt) {
    return [];
  }
  const when = new Date(sendAt);
  if (Number.isNaN(when.getTime())) {
    return [
      {
        id: 'schedule-invalid',
        tone: 'block',
        title: 'That send time is not valid',
        description: 'Pick a date and time in the future.',
      },
    ];
  }

  const notices: CampaignNotice[] = [];
  if (when.getTime() <= Date.now()) {
    notices.push({
      id: 'schedule-past',
      tone: 'block',
      title: 'That time has already passed',
      description: 'Choose a future time, or send now instead.',
    });
    return notices;
  }

  const hour = when.getHours();
  if (hour < 8 || hour >= 22) {
    notices.push({
      id: 'quiet-hours',
      tone: 'block',
      title: 'That lands inside quiet hours',
      description:
        'Marketing messages can only go out between 8:00 and 22:00. A notification at that hour loses customers for good.',
    });
  }

  const closedBranches = branchIds
    .map((id) => getBranch(id))
    .filter((branch): branch is MarketingBranch => branch !== null)
    .filter((branch) => {
      const [openHour] = branch.opens_at.split(':').map(Number);
      const [closeHour] = branch.closes_at.split(':').map(Number);
      return hour < openHour || hour >= closeHour;
    });

  if (closedBranches.length > 0) {
    notices.push({
      id: 'branch-closed',
      tone: 'warn',
      title: `${closedBranches.map((branch) => branch.branch_name).join(', ')} will be closed`,
      description:
        'Customers who tap through will not be able to order. Consider a time inside opening hours.',
    });
  }

  return notices;
}

export async function estimateReach(input: ReachInput): Promise<ReachEstimate> {
  if (dataSource === 'live') {
    await ensureReference();
    return live.fetchReachEstimate(input);
  }
  return respond(() => {
    const segment = getSegment(input.segment_key);
    const audience = audienceFor(input.segment_key, input.branch_ids);

    const channels: ChannelReach[] = input.channels.map((channel) => {
      if (channel === 'PUSH') {
        return pushReach(audience);
      }
      return {
        channel,
        available: false,
        unavailable_reason: MOCK_UNCONNECTED[channel as Exclude<MarketingChannel, 'PUSH'>],
        reachable: 0,
        blockers: [],
        estimated_cost: 0,
      };
    });

    const notices: CampaignNotice[] = [];

    if (input.branch_ids.length === 0) {
      notices.push({
        id: 'no-branch',
        tone: 'block',
        title: 'Pick at least one branch',
        description: 'A campaign always goes to the customers of specific branches.',
      });
    }

    if (audience > 0 && audience < MINIMUM_SEGMENT_SIZE) {
      notices.push({
        id: 'segment-too-small',
        tone: 'block',
        title: 'This audience is too small to send to',
        description: `Campaigns need at least ${MINIMUM_SEGMENT_SIZE} people. Widen the branches or choose another audience.`,
      });
    }

    const reachableTotal = channels
      .filter((channel) => channel.available)
      .reduce((total, channel) => total + channel.reachable, 0);

    if (input.branch_ids.length > 0 && audience >= MINIMUM_SEGMENT_SIZE && reachableTotal === 0) {
      notices.push({
        id: 'nobody-reachable',
        tone: 'block',
        title: 'Nobody in this audience can be reached',
        description:
          'None of these customers have the app installed with notifications on. Try a wider audience.',
      });
    }

    // Frequency capping. Scaled off the audience so the number moves with the
    // selection rather than looking like a fixed decoration.
    const recentlyMessaged = Math.round(audience * 0.09);
    if (recentlyMessaged > 0) {
      notices.push({
        id: 'frequency-cap',
        tone: 'info',
        title: `${recentlyMessaged} ${recentlyMessaged === 1 ? 'person' : 'people'} will be skipped`,
        description: `They have already had ${FREQUENCY_CAP_PER_WEEK} marketing messages this week. The cap protects your list and is applied automatically.`,
      });
    }

    const inactiveBranches = input.branch_ids
      .map((id) => getBranch(id))
      .filter((branch): branch is MarketingBranch => branch !== null)
      .filter((branch) => !branch.is_active);

    if (inactiveBranches.length > 0) {
      notices.push({
        id: 'branch-inactive',
        tone: 'warn',
        title: `${inactiveBranches.map((branch) => branch.branch_name).join(', ')} is not currently active`,
        description: 'Customers of an inactive branch cannot place an order right now.',
      });
    }

    if (input.goal === 'PROMOTE_DISH' && input.branch_ids.includes('branch-whitefield')) {
      notices.push({
        id: 'dish-unavailable',
        tone: 'warn',
        title: 'Butter Chicken Biryani is not on the Whitefield menu',
        description:
          'The dish link will be left out for that branch. Consider removing it from this campaign.',
      });
    }

    const unavailable = channels.filter((channel) => !channel.available);
    if (unavailable.length > 0) {
      notices.push({
        id: 'channels-unavailable',
        tone: 'info',
        title: 'Some channels are not connected yet',
        description: `${unavailable
          .map((channel) => channel.channel.charAt(0) + channel.channel.slice(1).toLowerCase())
          .join(', ')} will be available once set up. Push works today.`,
      });
    }

    notices.push(...timingNotices(input.send_at, input.branch_ids));

    return {
      segment_members: segment.total_members,
      audience_size: audience,
      channels,
      notices,
      minimum_segment_size: MINIMUM_SEGMENT_SIZE,
    };
  });
}

/* -------------------------------------------------------------------------- */
/* Dashboard                                                                   */
/* -------------------------------------------------------------------------- */

export async function getDashboard(): Promise<MarketingDashboard> {
  if (dataSource === 'live') {
    // Every figure attributed against the recipients a send actually reached.
    // This used to fall through to the mock, so a workspace that had never
    // sent a campaign showed thousands in "attributed revenue".
    await ensureReference();
    return live.fetchDashboard();
  }
  await ensureReference();
  return respond(() => {
    const rows = visibleCampaigns();
    const sent = rows.filter((campaign) => campaign.status === 'SENT');

    if (rows.length === 0) {
      return {
        attributed_revenue_30d: 0,
        attributed_revenue_previous_30d: 0,
        campaigns_sent_30d: 0,
        attributed_orders_30d: 0,
        best_campaign: null,
        attention: [],
        revenue_trend: [],
      };
    }

    const revenue = sent.reduce(
      (total, campaign) => total + (campaign.attribution?.net_revenue ?? 0),
      0,
    );
    const orders = sent.reduce(
      (total, campaign) => total + (campaign.attribution?.orders ?? 0),
      0,
    );

    const best = sent
      .slice()
      .sort(
        (a, b) => (b.attribution?.net_revenue ?? 0) - (a.attribution?.net_revenue ?? 0),
      )[0];

    const attention: MarketingDashboard['attention'] = [];

    for (const campaign of rows) {
      if (campaign.status === 'SCHEDULED' && campaign.schedule.send_at) {
        attention.push({
          id: `scheduled-${campaign.id}`,
          tone: 'info',
          title: `"${campaign.name}" is scheduled`,
          description: `Goes out ${new Date(campaign.schedule.send_at).toLocaleString('en-CA', {
            dateStyle: 'medium',
            timeStyle: 'short',
          })}. You can still edit or cancel it.`,
          campaign_id: campaign.id,
        });
      }
      if (campaign.status === 'FAILED') {
        attention.push({
          id: `failed-${campaign.id}`,
          tone: 'warn',
          title: `"${campaign.name}" did not send`,
          description: campaign.last_error ?? 'The send failed.',
          campaign_id: campaign.id,
        });
      }
      if (campaign.status === 'DRAFT') {
        attention.push({
          id: `draft-${campaign.id}`,
          tone: 'info',
          title: `"${campaign.name}" is still a draft`,
          description: 'Pick it up where you left off.',
          campaign_id: campaign.id,
        });
      }
    }

    return {
      attributed_revenue_30d: revenue,
      attributed_revenue_previous_30d: Math.round(revenue * 0.72),
      campaigns_sent_30d: sent.length,
      attributed_orders_30d: orders,
      best_campaign: best
        ? {
            id: best.id,
            name: best.name,
            net_revenue: best.attribution?.net_revenue ?? 0,
          }
        : null,
      attention,
      revenue_trend: MOCK_REVENUE_TREND,
    };
  });
}

/* -------------------------------------------------------------------------- */
/* Campaign reads                                                              */
/* -------------------------------------------------------------------------- */

export interface CampaignQuery {
  status?: CampaignStatus | 'ALL';
  search?: string;
}

export async function listCampaigns(query: CampaignQuery = {}): Promise<Campaign[]> {
  if (dataSource === 'live') {
    await ensureReference();
    const rows = await live.fetchCampaigns();
    // The route takes no filters; the Hub filters in the page anyway, and
    // duplicating that server-side would be two places to keep in step.
    const search = (query.search ?? '').trim().toLowerCase();
    return rows
      .filter((campaign) =>
        !query.status || query.status === 'ALL' ? true : campaign.status === query.status,
      )
      .filter((campaign) =>
        search.length === 0 ? true : campaign.name.toLowerCase().includes(search),
      );
  }
  return respond(() => {
    const search = (query.search ?? '').trim().toLowerCase();
    return visibleCampaigns()
      .filter((campaign) =>
        !query.status || query.status === 'ALL' ? true : campaign.status === query.status,
      )
      .filter((campaign) =>
        search.length === 0 ? true : campaign.name.toLowerCase().includes(search),
      )
      .slice()
      .sort(
        (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
      )
      .map(clone);
  });
}

export async function getCampaign(id: string): Promise<Campaign> {
  if (dataSource === 'live') {
    await ensureReference();
    return live.fetchCampaign(id);
  }
  return respond(() => {
    const campaign = campaigns.find((entry) => entry.id === id);
    if (!campaign) {
      throw new MarketingApiError('That campaign no longer exists.');
    }
    return clone(campaign);
  });
}

/* -------------------------------------------------------------------------- */
/* Campaign writes                                                             */
/* -------------------------------------------------------------------------- */

function draftToCampaign(draft: CampaignDraft, existing: Campaign | undefined): Campaign {
  const now = new Date().toISOString();
  return {
    id: draft.id,
    name: draft.name,
    goal: draft.goal,
    segment_key: draft.segment_key,
    branch_ids: [...draft.branch_ids],
    offer_id: draft.offer_id,
    // The wire still carries a list; the draft carries the one entry in it.
    channels: [draft.channel],
    content: { ...draft.content, extra: { ...draft.content.extra } },
    schedule: { ...draft.schedule },
    status: existing?.status ?? 'DRAFT',
    created_at: existing?.created_at ?? now,
    updated_at: now,
    sent_at: existing?.sent_at ?? null,
    created_by: existing?.created_by ?? 'You',
    audience_size: audienceFor(draft.segment_key, draft.branch_ids),
    delivery: existing?.delivery ?? null,
    failure_reasons: existing?.failure_reasons ?? [],
    attribution: existing?.attribution ?? null,
    last_error: existing?.last_error ?? null,
    sending_progress: null,
    social: existing?.social ?? null,
  };
}

export async function saveDraft(draft: CampaignDraft): Promise<Campaign> {
  if (dataSource === 'live') {
    await ensureReference();
    return live.saveDraft(draft);
  }
  return respond(() => {
    const existing = campaigns.find((entry) => entry.id === draft.id);
    if (existing && existing.status !== 'DRAFT' && existing.status !== 'SCHEDULED') {
      throw new MarketingApiError('A campaign that has already sent cannot be edited.');
    }
    const next = draftToCampaign(draft, existing);
    campaigns = existing
      ? campaigns.map((entry) => (entry.id === draft.id ? next : entry))
      : [next, ...campaigns];
    return clone(next);
  });
}

export function createDraftId(): string {
  return nextId('cmp');
}

/**
 * Sending is modelled, not faked away: the campaign goes SENDING, a delivery
 * breakdown appears, and the attribution window opens with zero orders in it.
 * That is what the owner sees in the real product in the first minute, and it
 * is the state the detail screen has to render well.
 */
export async function sendNow(id: string): Promise<Campaign> {
  if (dataSource === 'live') {
    // Returns as soon as the server has claimed the campaign, with it in
    // SENDING — the dispatch runs on a worker. The Hub polls the row, which is
    // what `sending_progress` is for.
    await ensureReference();
    return live.sendCampaign(id);
  }
  return respond(() => {
    const campaign = campaigns.find((entry) => entry.id === id);
    if (!campaign) {
      throw new MarketingApiError('That campaign no longer exists.');
    }
    const reach = pushReach(campaign.audience_size);
    const delivered = Math.round(reach.reachable * 0.92);
    const failed = reach.reachable - delivered;
    const now = new Date().toISOString();

    const next: Campaign = {
      ...campaign,
      status: 'SENT',
      sent_at: now,
      updated_at: now,
      schedule: { ...campaign.schedule, mode: 'NOW', send_at: null },
      delivery: {
        sent: reach.reachable,
        delivered,
        opened: 0,
        clicked: 0,
        failed,
        unsubscribed: 0,
      },
      failure_reasons:
        failed > 0 ? [{ reason: 'App uninstalled', count: failed }] : [],
      attribution: freshAttribution(),
      sending_progress: null,
    };

    campaigns = campaigns.map((entry) => (entry.id === id ? next : entry));
    return clone(next);
  });
}

function freshAttribution(): AttributionReport {
  return {
    window_days: ATTRIBUTION_WINDOW_DAYS,
    window_open: true,
    orders: 0,
    revenue: 0,
    discount_given: 0,
    net_revenue: 0,
    average_order_value: 0,
    baseline_orders: 0,
    returning_customers: 0,
    new_customers: 0,
    daily: [],
  };
}

export async function scheduleCampaign(id: string, sendAt: string): Promise<Campaign> {
  if (dataSource === 'live') {
    return live.scheduleCampaign(id, sendAt);
  }
  return respond(() => {
    const campaign = campaigns.find((entry) => entry.id === id);
    if (!campaign) {
      throw new MarketingApiError('That campaign no longer exists.');
    }
    const now = new Date().toISOString();
    const next: Campaign = {
      ...campaign,
      status: 'SCHEDULED',
      updated_at: now,
      schedule: { mode: 'SCHEDULED', send_at: sendAt, timezone: MOCK_TIMEZONE },
    };
    campaigns = campaigns.map((entry) => (entry.id === id ? next : entry));
    return clone(next);
  });
}

export async function cancelCampaign(id: string): Promise<Campaign> {
  if (dataSource === 'live') {
    return live.cancelCampaign(id);
  }
  return respond(() => {
    const campaign = campaigns.find((entry) => entry.id === id);
    if (!campaign) {
      throw new MarketingApiError('That campaign no longer exists.');
    }
    if (campaign.status !== 'SCHEDULED' && campaign.status !== 'SENDING') {
      throw new MarketingApiError('Only a scheduled or sending campaign can be cancelled.');
    }
    const next: Campaign = {
      ...campaign,
      status: 'CANCELLED',
      updated_at: new Date().toISOString(),
    };
    campaigns = campaigns.map((entry) => (entry.id === id ? next : entry));
    return clone(next);
  });
}

/**
 * A duplicate rebuilds its audience rather than copying the original's, and
 * clears the schedule — so nothing sends by accident and the list is current.
 */
export async function duplicateCampaign(id: string): Promise<Campaign> {
  if (dataSource === 'live') {
    return live.duplicateCampaign(id);
  }
  return respond(() => {
    const campaign = campaigns.find((entry) => entry.id === id);
    if (!campaign) {
      throw new MarketingApiError('That campaign no longer exists.');
    }
    const now = new Date().toISOString();
    const copy: Campaign = {
      ...clone(campaign),
      id: nextId('cmp'),
      name: `${campaign.name} (copy)`,
      status: 'DRAFT',
      created_at: now,
      updated_at: now,
      sent_at: null,
      audience_size: audienceFor(campaign.segment_key, campaign.branch_ids),
      schedule: { mode: 'NOW', send_at: null, timezone: MOCK_TIMEZONE },
      delivery: null,
      failure_reasons: [],
      attribution: null,
      last_error: null,
      sending_progress: null,
    };
    campaigns = [copy, ...campaigns];
    return clone(copy);
  });
}

export async function deleteDraft(id: string): Promise<void> {
  if (dataSource === 'live') {
    return live.deleteDraft(id);
  }
  return respond(() => {
    const campaign = campaigns.find((entry) => entry.id === id);
    if (!campaign) {
      throw new MarketingApiError('That campaign no longer exists.');
    }
    if (campaign.status !== 'DRAFT') {
      throw new MarketingApiError('Only a draft can be deleted.');
    }
    campaigns = campaigns.filter((entry) => entry.id !== id);
  });
}

export async function sendTest(
  channel: MarketingChannel,
  content?: { title: string; body: string },
): Promise<TestSendResult> {
  if (dataSource === 'live') {
    if (!content) {
      throw new MarketingApiError('Write the message before testing it.');
    }
    return live.testSend(channel, content);
  }
  return respond(() => ({
    channel,
    destination: 'your own device',
    sent_at: new Date().toISOString(),
  }));
}

/* -------------------------------------------------------------------------- */
/* Channel connections                                                         */
/* -------------------------------------------------------------------------- */

/**
 * The mock's answer: push is on, nothing else is.
 *
 * Deliberately not "everything connected". The mock exists so the UI can be
 * reviewed without a server, and the state worth reviewing is the one most
 * restaurants are actually in — one live channel and five that need setting
 * up, which is the screen this whole feature is about.
 */
const MOCK_CHANNEL_ORDER: MarketingChannel[] = [
  'PUSH',
  'WHATSAPP',
  'SMS',
  'EMAIL',
  'INSTAGRAM',
  'FACEBOOK',
];

let mockConnections: ChannelConnection[] | null = null;

function mockChannels(): ChannelConnection[] {
  if (mockConnections) {
    return clone(mockConnections);
  }
  mockConnections = MOCK_CHANNEL_ORDER.map((channel) => ({
    channel,
    family: channel === 'INSTAGRAM' || channel === 'FACEBOOK' ? 'SOCIAL' : 'DIRECT',
    connected: channel === 'PUSH',
    status: channel === 'PUSH' ? 'CONNECTED' : null,
    config: {},
    identity: channel === 'PUSH' ? 'Your app' : null,
    connected_at: null,
    verified_at: null,
    last_error: null,
    requirements: [],
  }));
  return clone(mockConnections);
}

export async function listChannels(): Promise<ChannelConnection[]> {
  if (dataSource === 'live') {
    return live.fetchChannels();
  }
  return respond(() => mockChannels());
}

export async function connectChannel(
  channel: MarketingChannel,
  values: Record<string, string>,
): Promise<ChannelConnection> {
  if (dataSource === 'live') {
    return live.saveChannel(channel, values);
  }
  return respond(() => {
    const rows = mockChannels();
    const next = rows.map((row) =>
      row.channel === channel
        ? {
            ...row,
            connected: true,
            status: 'CONNECTED' as const,
            config: { ...row.config, ...values },
            identity: Object.values(values)[0] ?? row.identity,
            connected_at: new Date().toISOString(),
          }
        : row,
    );
    mockConnections = next;
    return clone(next.find((row) => row.channel === channel)!);
  });
}

export async function setChannelEnabled(
  channel: MarketingChannel,
  enabled: boolean,
): Promise<ChannelConnection> {
  if (dataSource === 'live') {
    return live.setChannelEnabled(channel, enabled);
  }
  return respond(() => {
    const next = mockChannels().map((row) =>
      row.channel === channel
        ? {
            ...row,
            connected: enabled,
            status: enabled ? ('CONNECTED' as const) : ('DISABLED' as const),
          }
        : row,
    );
    mockConnections = next;
    return clone(next.find((row) => row.channel === channel)!);
  });
}

export async function disconnectChannel(channel: MarketingChannel): Promise<void> {
  if (dataSource === 'live') {
    return live.disconnectChannel(channel);
  }
  return respond(() => {
    mockConnections = mockChannels().map((row) =>
      row.channel === channel
        ? { ...row, connected: false, status: null, config: {}, identity: null }
        : row,
    );
    return undefined;
  });
}

/** Resets the in-memory store. Used by the demo controls, never in production. */
export function resetMarketingMockData(): void {
  mockConnections = null;
  campaigns = MOCK_CAMPAIGNS.map((campaign) => ({ ...campaign }));
}
