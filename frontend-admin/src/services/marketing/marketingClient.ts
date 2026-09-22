/**
 * The live half of the Marketing Hub's data layer.
 *
 * `marketingApi.ts` is still the only module any screen imports; this is what
 * it delegates to once the data source is `live`. Keeping the two apart means
 * the mock survives intact — useful while three of the six backend slices do
 * not exist yet, and useful for reviewing the UI with no API running at all.
 *
 * The backend's response schemas were written to mirror `types.ts` field for
 * field, so almost nothing here maps or renames. Where a function does more
 * than call and return, the comment says what the mismatch was.
 */

import { request } from '../api';
import { storage } from '../storage';
import { getRestaurantScope } from './marketingApi';
import type {
  Campaign,
  CampaignDraft,
  CampaignGoal,
  ChannelConnection,
  MarketingBranch,
  MarketingChannel,
  MarketingDashboard,
  MarketingOffer,
  MarketingSegment,
  MessageTemplate,
  NoticeTone,
  ReachEstimate,
  TestSendResult,
} from './types';
import type { ReachInput } from './marketingApi';

/**
 * Every screen already reads the session from here, so the marketing calls take
 * no token parameter. That keeps the mock and live signatures identical, which
 * is what lets the façade swap between them without touching a call site.
 */
function token(): string | null {
  return storage.readAuth()?.token ?? null;
}

/**
 * Append the admin's chosen restaurant to a marketing path.
 *
 * Every `/marketing/*` route takes `restaurant_id` as an optional query
 * parameter and hands it to `resolve_insights_scope`, which requires one from
 * an ADMIN and refuses one from an OWNER. So this is the whole difference
 * between the two roles on the wire: an owner sends nothing and is pinned to
 * their own restaurant, an admin sends the restaurant they picked.
 */
function scoped(path: string): string {
  const restaurantId = getRestaurantScope();
  if (!restaurantId) {
    return path;
  }
  const separator = path.includes('?') ? '&' : '?';
  return `${path}${separator}restaurant_id=${encodeURIComponent(restaurantId)}`;
}

/** What `/marketing/reference` returns, ahead of anything a draft needs. */
export interface MarketingReferencePayload {
  goals: CampaignGoal[];
  segments: MarketingSegment[];
  branches: MarketingBranch[];
  offers: MarketingOffer[];
  templates: MessageTemplate[];
  minimum_segment_size: number;
  frequency_cap_per_week: number;
  timezone: string;
}

export function fetchReference(): Promise<MarketingReferencePayload> {
  return request<MarketingReferencePayload>(scoped('/marketing/reference'), { token: token() });
}

export function fetchReachEstimate(input: ReachInput): Promise<ReachEstimate> {
  return request<ReachEstimate>(scoped('/marketing/reach-estimate'), {
    method: 'POST',
    token: token(),
    body: {
      goal: input.goal,
      segment_key: input.segment_key,
      branch_ids: input.branch_ids,
      channels: input.channels,
      send_at: input.send_at,
    },
  });
}

/**
 * Guarantee the per-channel content bag exists on anything from the wire.
 *
 * `content.extra` is new, and a campaign written before it — or by a backend
 * that has not been redeployed — comes back without the key at all. Every
 * editor and preview reads `content.extra.image_url` directly, so an undefined
 * bag is a crash on open rather than a missing photo. Normalising once, here,
 * is cheaper than a `?.` on every read.
 */
function withExtra(campaign: Campaign): Campaign {
  return {
    ...campaign,
    content: { ...campaign.content, extra: campaign.content?.extra ?? {} },
    // Absent on every direct campaign and on anything written before social
    // channels existed. Normalised to null so the report can test one thing.
    social: campaign.social ?? null,
  };
}

/* -------------------------------------------------------------------------- */
/* Channel connections                                                         */
/* -------------------------------------------------------------------------- */

export function fetchChannels(): Promise<ChannelConnection[]> {
  return request<ChannelConnection[]>(scoped('/marketing/channels'), { token: token() });
}

/**
 * Save what a channel needs. Only the fields the owner actually typed.
 *
 * The server merges rather than replaces, so omitting a secret keeps the
 * stored one — which is what makes "correct my sender name" possible without
 * re-pasting an access token that the form could never have shown.
 */
export function saveChannel(
  channel: string,
  values: Record<string, string>,
): Promise<ChannelConnection> {
  return request<ChannelConnection>(
    scoped(`/marketing/channels/${encodeURIComponent(channel)}`),
    { method: 'PUT', token: token(), body: { values } },
  );
}

export function setChannelEnabled(
  channel: string,
  enabled: boolean,
): Promise<ChannelConnection> {
  return request<ChannelConnection>(
    scoped(`/marketing/channels/${encodeURIComponent(channel)}/enabled`),
    { method: 'POST', token: token(), body: { enabled } },
  );
}

export async function disconnectChannel(channel: string): Promise<void> {
  await request<void>(scoped(`/marketing/channels/${encodeURIComponent(channel)}`), {
    method: 'DELETE',
    token: token(),
  });
}

export async function fetchCampaigns(): Promise<Campaign[]> {
  const rows = await request<Campaign[]>(scoped('/marketing/campaigns'), { token: token() });
  return rows.map(withExtra);
}

export async function fetchCampaign(id: string): Promise<Campaign> {
  return withExtra(
    await request<Campaign>(scoped(`/marketing/campaigns/${encodeURIComponent(id)}`), {
      token: token(),
    }),
  );
}

/**
 * Ids the server minted are UUIDs; ids the wizard minted locally are not.
 *
 * The builder needs an id before the first save — it keys a draft that exists
 * only in the browser — so it generates `cmp-<random>`. The backend's
 * `save_draft` types that field as `uuid | null` and treats null as "create",
 * so sending the local id verbatim is a 422 on the very first keystroke of
 * every new campaign. This is the test that tells the two apart.
 */
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isServerId(id: string): boolean {
  return UUID_PATTERN.test(id);
}

export async function saveDraft(draft: CampaignDraft): Promise<Campaign> {
  const saved = await request<Campaign>(scoped('/marketing/campaigns'), {
    method: 'POST',
    token: token(),
    body: {
      // Null on the first save. The caller adopts the id that comes back, so
      // the second save updates rather than creating a duplicate.
      id: isServerId(draft.id) ? draft.id : null,
      name: draft.name,
      goal: draft.goal,
      segment_key: draft.segment_key,
      branch_ids: draft.branch_ids,
      offer_id: draft.offer_id,
      // One channel per campaign, sent as the single-entry list the column
      // and the schema already expect. See the note atop `types.ts`.
      channels: [draft.channel],
      content: draft.content,
      schedule: draft.schedule,
      last_step: draft.last_step,
    },
  });
  return withExtra(saved);
}

export async function scheduleCampaign(id: string, sendAt: string): Promise<Campaign> {
  return withExtra(
    await request<Campaign>(
      scoped(`/marketing/campaigns/${encodeURIComponent(id)}/schedule`),
      { method: 'POST', token: token(), body: { send_at: sendAt } },
    ),
  );
}

export async function cancelCampaign(id: string): Promise<Campaign> {
  return withExtra(
    await request<Campaign>(scoped(`/marketing/campaigns/${encodeURIComponent(id)}/cancel`), {
      method: 'POST',
      token: token(),
    }),
  );
}

export async function duplicateCampaign(id: string): Promise<Campaign> {
  return withExtra(
    await request<Campaign>(
      scoped(`/marketing/campaigns/${encodeURIComponent(id)}/duplicate`),
      { method: 'POST', token: token() },
    ),
  );
}

export async function deleteDraft(id: string): Promise<void> {
  await request<void>(scoped(`/marketing/campaigns/${encodeURIComponent(id)}`), {
    method: 'DELETE',
    token: token(),
  });
}


export async function sendCampaign(id: string): Promise<Campaign> {
  return withExtra(
    await request<Campaign>(scoped(`/marketing/campaigns/${encodeURIComponent(id)}/send`), {
      method: 'POST',
      token: token(),
    }),
  );
}

/** What `GET /marketing/dashboard` returns, before it is reshaped below. */
interface DashboardPayload {
  attributed_revenue_30d: number;
  attributed_revenue_previous_30d: number;
  campaigns_sent_30d: number;
  attributed_orders_30d: number;
  best_campaign: {
    id: string;
    name: string;
    net_revenue: number;
    orders: number;
    sent_at: string | null;
  } | null;
  attention: Array<{
    id: string;
    tone: string;
    title: string;
    detail: string;
    campaign_id: string | null;
  }>;
  revenue_trend: Array<{ date: string; revenue: number }>;
}

/**
 * The one response that is reshaped rather than passed through.
 *
 * Two mismatches, both deliberate on their own side: the server calls a flag's
 * body `detail` because that is what every other error-ish payload in this API
 * calls it, and returns the trend as dated money rather than as chart points,
 * because a date is a fact and a chart label is a presentation choice. The
 * mapping belongs here rather than in either of them.
 */
export async function fetchDashboard(): Promise<MarketingDashboard> {
  const payload = await request<DashboardPayload>(scoped('/marketing/dashboard'), {
    token: token(),
  });
  return {
    attributed_revenue_30d: payload.attributed_revenue_30d,
    attributed_revenue_previous_30d: payload.attributed_revenue_previous_30d,
    campaigns_sent_30d: payload.campaigns_sent_30d,
    attributed_orders_30d: payload.attributed_orders_30d,
    best_campaign: payload.best_campaign
      ? {
          id: payload.best_campaign.id,
          name: payload.best_campaign.name,
          net_revenue: payload.best_campaign.net_revenue,
        }
      : null,
    attention: payload.attention.map((flag) => ({
      id: flag.id,
      tone: flag.tone as NoticeTone,
      title: flag.title,
      description: flag.detail,
      campaign_id: flag.campaign_id,
    })),
    revenue_trend: payload.revenue_trend.map((point) => ({
      label: point.date,
      value: point.revenue,
    })),
  };
}

interface TestSendPayload {
  delivered: boolean;
  device_count: number;
  detail: string;
}

/**
 * Test-sends go to the signed-in staff member's own devices, never an address
 * they type — a test that could name any recipient is a way to push a
 * notification to a customer outside every consent rule in this module.
 *
 * So there is no destination to report and the server answers with what
 * actually happened instead. `destination` carries that sentence, because the
 * "sending is switched off in this environment" case has to reach the owner
 * and a boolean cannot say it.
 */
export async function testSend(
  channel: MarketingChannel,
  content: { title: string; body: string },
): Promise<TestSendResult> {
  const payload = await request<TestSendPayload>(scoped('/marketing/test-send'), {
    method: 'POST',
    token: token(),
    body: { title: content.title, body: content.body, channel },
  });
  return {
    channel,
    destination: payload.detail,
    sent_at: new Date().toISOString(),
  };
}
