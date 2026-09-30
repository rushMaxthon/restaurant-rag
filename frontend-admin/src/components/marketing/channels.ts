/**
 * What each place an owner can run a campaign actually is.
 *
 * This file exists because the old wizard asked for the channel *fourth*, and
 * by then three steps of push-shaped work had already happened: a 65-character
 * title, a lock-screen preview, a "where does tapping it go" dropdown. An
 * owner who wanted Instagram had written a notification. Asking first only
 * helps if the answer then changes the rest of the flow, so everything that
 * differs per channel is declared here and read by the steps, rather than
 * being `channel === 'PUSH' ?` scattered across a 1,300-line page.
 *
 * The split that matters is `family`, not the brand:
 *
 *   DIRECT (push, WhatsApp, SMS, email) — the owner picks *people*. Consent
 *     applies, reach is countable before sending, one recipient row is written
 *     per customer, and attribution is measured per recipient from their own
 *     send instant. This is what the whole Marketing Hub backend already does.
 *
 *   SOCIAL (Instagram, Facebook) — the owner picks *nobody*. There is no
 *     consent to check, no recipient row to write, and so the attribution rule
 *     the rest of the Hub is built on ("read recipient rows, never the
 *     segment") has no meaning at all. A public post is measured by a promo
 *     code or by the platform's own numbers.
 *
 * Collapsing those two into one audience step is exactly why the old step 4
 * could offer nothing but a row of disabled checkboxes.
 */

import {
  Bell,
  Facebook,
  Instagram,
  Mail,
  MessageCircle,
  Smartphone,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { CampaignGoalKey, MarketingChannel } from '../../services/marketing/types';

export type ChannelFamily = 'DIRECT' | 'SOCIAL';

/**
 * Whether this channel needs setting up before it can send.
 *
 * ALWAYS_ON is push alone: its credentials are the platform's Firebase
 * service account, shared by every restaurant, so there is nothing for an
 * owner to connect and nothing they could disconnect.
 *
 * NEEDS_CONNECTION does **not** mean "cannot send". Whether a channel can
 * actually send is a fact about the restaurant, answered by
 * `GET /marketing/channels` and held in `ChannelConnection.connected` — this
 * only says the answer has to be looked up rather than assumed. The
 * distinction matters: the previous version of this field was a build-time
 * constant that could only ever say "not connected yet", so a channel that
 * HAD been connected still rendered as unavailable.
 */
export type ChannelAvailability = 'ALWAYS_ON' | 'NEEDS_CONNECTION';

export interface ChannelContentSpec {
  /** The headline field, or null where the format has no headline. */
  title: { label: string; limit: number; placeholder: string; hint: string } | null;
  body: { label: string; limit: number; placeholder: string; rows: number; hint: string };
  /** `{first_name}` only means something when there is one named recipient. */
  mergeFields: boolean;
  /** A tap destination. A public post has a profile link and nothing else. */
  deepLink: boolean;
  image: 'required' | 'optional' | 'none';
  hashtags: boolean;
  /** A labelled button on a link card. Facebook has one; nothing else does. */
  cta: boolean;
  /** Meta approves WhatsApp layouts in advance, so free typing is impossible. */
  templateOnly: boolean;
  /** Added by the carrier or platform, not editable, but it still counts. */
  footer: string | null;
  /** SMS is billed per 160-character part; null where length costs nothing. */
  segmentLength: number | null;
  /** Shown beside the body count, so the owner sees the bill as they type. */
  perMessageCost: number;
}

export interface ChannelDefinition {
  key: MarketingChannel;
  label: string;
  short: string;
  icon: LucideIcon;
  family: ChannelFamily;
  availability: ChannelAvailability;
  /** One plain line on the picker card. No jargon, no feature list. */
  tagline: string;
  /** What it costs, in the words an owner would use. */
  cost: string;
  /** The thing being made: "notification", "post". Used all over the copy. */
  noun: string;
  /** The button verb: "Send", "Post". A post is not sent and vice versa. */
  verb: string;
  /** Goals this channel can honestly deliver. Empty means all of them. */
  goals: CampaignGoalKey[];
  content: ChannelContentSpec;
  /** What switching this on involves, for the panel under the picker. */
  setup: string[];
}

/** Merge fields are meaningless in a public post; every DIRECT channel has them. */
const DIRECT_DEFAULTS = {
  mergeFields: true,
  hashtags: false,
  cta: false,
  templateOnly: false,
} as const;

/**
 * Goals a broadcast post can actually deliver.
 *
 * WINBACK, REWARD_VIPS and FIRST_TO_REGULAR are absent on purpose: all three
 * are defined by who receives them, and an organic post cannot pick who. The
 * old flow offered them for every channel and would have quietly delivered
 * something else. Not offering a goal is kinder than failing it.
 */
const SOCIAL_GOALS: CampaignGoalKey[] = [
  'PROMOTE_DISH',
  'NEW_ITEM',
  'QUIET_DAY',
  'ANNOUNCEMENT',
  'CUSTOM',
];

export const CHANNELS: ChannelDefinition[] = [
  {
    key: 'PUSH',
    label: 'Push notification',
    short: 'Push',
    icon: Bell,
    family: 'DIRECT',
    availability: 'ALWAYS_ON',
    tagline: 'Pops up on the phones of people who have your app.',
    cost: 'Free',
    noun: 'notification',
    verb: 'Send',
    goals: [],
    setup: [],
    content: {
      ...DIRECT_DEFAULTS,
      // 65 and 240 are not the protocol's limits, they are the phone's: past
      // roughly this much, Android and iOS both cut the line off mid-word on a
      // lock screen. The preview is the real check; these drive the counter.
      title: {
        label: 'Title',
        limit: 65,
        placeholder: 'We miss you, {first_name}!',
        hint: 'The one line people read without unlocking their phone.',
      },
      body: {
        label: 'Message',
        limit: 240,
        placeholder: 'Your favourite dish is waiting.',
        rows: 3,
        hint: 'Watch the phone on the right as you type.',
      },
      deepLink: true,
      image: 'none',
      footer: null,
      segmentLength: null,
      perMessageCost: 0,
    },
  },
  {
    key: 'WHATSAPP',
    label: 'WhatsApp',
    short: 'WhatsApp',
    icon: MessageCircle,
    family: 'DIRECT',
    availability: 'NEEDS_CONNECTION',
    tagline: 'Lands in their WhatsApp, next to messages from friends.',
    cost: 'Meta charges per message',
    noun: 'message',
    verb: 'Send',
    goals: [],
    setup: [
      'Sign in with Meta and pick the business number you already use.',
      'Meta has to approve each message layout before you can send it — usually a day.',
      'Meta bills you per message, not us.',
    ],
    content: {
      ...DIRECT_DEFAULTS,
      // Free typing is genuinely impossible here: WhatsApp only delivers
      // business-initiated messages that match a layout Meta approved in
      // advance. An editor that let an owner write anything would be promising
      // a send that WhatsApp refuses.
      templateOnly: true,
      title: {
        label: 'Header',
        limit: 60,
        placeholder: 'A little something from us',
        hint: 'The bold line at the top of the message.',
      },
      body: {
        label: 'Message',
        limit: 700,
        placeholder: 'Hi {first_name}, we have not seen you in a while…',
        rows: 5,
        hint: 'Only the blanks in the approved layout can change.',
      },
      deepLink: true,
      image: 'optional',
      footer: 'Reply STOP to stop receiving these',
      segmentLength: null,
      perMessageCost: 0.85,
    },
  },
  {
    key: 'SMS',
    label: 'SMS',
    short: 'SMS',
    icon: Smartphone,
    family: 'DIRECT',
    availability: 'NEEDS_CONNECTION',
    tagline: 'A plain text message. Works even without your app.',
    cost: 'Charged per message',
    noun: 'text',
    verb: 'Send',
    goals: [],
    setup: [
      'Register a sender name with your telecom operator.',
      'Operators approve the wording of each message before it can go out.',
      'You are billed per 160 characters, so a long text costs more than one.',
    ],
    content: {
      ...DIRECT_DEFAULTS,
      // No headline: a text message is one block of characters, and pretending
      // otherwise would cost the owner money for a line nobody sees as a title.
      title: null,
      body: {
        label: 'Your text',
        limit: 480,
        placeholder: 'Hi {first_name}, 20% off at Indiranagar tonight. Order: ',
        rows: 4,
        hint: 'Every 160 characters is one message, and one message is one charge.',
      },
      deepLink: true,
      image: 'none',
      // Not optional and not editable — the opt-out line is a legal
      // requirement, and it is counted in the length because the operator
      // counts it. Hiding it would understate the bill.
      footer: 'Reply STOP to opt out',
      segmentLength: 160,
      perMessageCost: 0.85,
    },
  },
  {
    key: 'EMAIL',
    label: 'Email',
    short: 'Email',
    icon: Mail,
    family: 'DIRECT',
    availability: 'NEEDS_CONNECTION',
    tagline: 'Room for photos and a longer story.',
    cost: 'Free',
    noun: 'email',
    verb: 'Send',
    goals: [],
    setup: [
      'Verify the domain you send from, so your mail does not land in spam.',
      'Add an unsubscribe link — every email needs one by law.',
    ],
    content: {
      ...DIRECT_DEFAULTS,
      title: {
        label: 'Subject line',
        limit: 90,
        placeholder: 'A table is waiting, {first_name}',
        hint: 'The only thing most people read before deciding to open it.',
      },
      body: {
        label: 'Email',
        limit: 2000,
        placeholder: 'Tell them what is new, and why it is worth coming back for.',
        rows: 8,
        hint: 'Keep the important part in the first two lines.',
      },
      deepLink: true,
      image: 'optional',
      footer: 'Unsubscribe',
      segmentLength: null,
      perMessageCost: 0,
    },
  },
  {
    key: 'INSTAGRAM',
    label: 'Instagram',
    short: 'Instagram',
    icon: Instagram,
    family: 'SOCIAL',
    availability: 'NEEDS_CONNECTION',
    tagline: 'A photo post for the people who follow you.',
    cost: 'Free, or set a budget to reach more',
    noun: 'post',
    verb: 'Post',
    goals: SOCIAL_GOALS,
    setup: [
      'Connect the Instagram account through Meta. It has to be a business or creator account.',
      'Posting needs a photo or a video — Instagram will not accept text on its own.',
      'Paying to reach more people is billed by Meta, not by us.',
    ],
    content: {
      mergeFields: false,
      templateOnly: false,
      title: null,
      body: {
        label: 'Caption',
        limit: 2200,
        placeholder: 'Slow-cooked, eight hours, every morning. Back on the menu today.',
        rows: 6,
        hint: 'The first two lines show before "more" — put the good part there.',
      },
      deepLink: false,
      image: 'required',
      hashtags: true,
      cta: false,
      footer: null,
      segmentLength: null,
      perMessageCost: 0,
    },
  },
  {
    key: 'FACEBOOK',
    label: 'Facebook',
    short: 'Facebook',
    icon: Facebook,
    family: 'SOCIAL',
    availability: 'NEEDS_CONNECTION',
    tagline: 'A post on your Page, for the people who like it.',
    cost: 'Free, or set a budget to reach more',
    noun: 'post',
    verb: 'Post',
    goals: SOCIAL_GOALS,
    setup: [
      'Connect the Facebook Page you already run.',
      'Paying to reach more people is billed by Meta, not by us.',
    ],
    content: {
      mergeFields: false,
      templateOnly: false,
      title: {
        label: 'Headline',
        limit: 80,
        placeholder: 'Back on the menu',
        hint: 'Sits on the link card under the post. Optional.',
      },
      body: {
        label: 'Post',
        limit: 1500,
        placeholder: 'Tell people what is happening at the restaurant this week.',
        rows: 6,
        hint: 'Past about 80 characters Facebook hides the rest behind "See more".',
      },
      deepLink: false,
      image: 'optional',
      hashtags: true,
      cta: true,
      footer: null,
      segmentLength: null,
      perMessageCost: 0,
    },
  },
];

const BY_KEY = new Map(CHANNELS.map((channel) => [channel.key, channel]));

/**
 * Push, always, for an unknown key.
 *
 * A campaign saved before this redesign has `channels: ["PUSH"]`, and a
 * campaign saved by a future version may name a channel this build has never
 * heard of. Both have to render something rather than crash the editor, and
 * push is the only channel whose behaviour is certainly implemented.
 */
export function getChannel(key: MarketingChannel | undefined | null): ChannelDefinition {
  return (key ? BY_KEY.get(key) : undefined) ?? BY_KEY.get('PUSH')!;
}

export function channelsInFamily(family: ChannelFamily): ChannelDefinition[] {
  return CHANNELS.filter((channel) => channel.family === family);
}

/** True where the goal makes sense on this channel. Empty `goals` means all. */
export function goalFitsChannel(channel: ChannelDefinition, goal: CampaignGoalKey): boolean {
  return channel.goals.length === 0 || channel.goals.includes(goal);
}

/**
 * How many billable parts a text of this length is, footer included.
 *
 * Returns 1 for an empty message rather than 0: an owner reading "0 messages,
 * ₹0" before they have typed would reasonably conclude SMS is free.
 */
export function messageParts(text: string, spec: ChannelContentSpec): number {
  if (!spec.segmentLength) {
    return 1;
  }
  const total = text.length + (spec.footer ? spec.footer.length + 1 : 0);
  return Math.max(1, Math.ceil(total / spec.segmentLength));
}

/** What sending to this many people costs on this channel, in whole currency. */
export function estimateSpend(
  channel: ChannelDefinition,
  recipients: number,
  bodyText: string,
): number {
  if (channel.content.perMessageCost <= 0) {
    return 0;
  }
  return channel.content.perMessageCost * recipients * messageParts(bodyText, channel.content);
}

/**
 * The one channel a campaign runs on, read from the list the wire still uses.
 *
 * Defaults to push for an empty list, which is what every campaign created
 * before the Hub stored channels at all looks like.
 */
export function primaryChannel(channels: MarketingChannel[] | undefined): MarketingChannel {
  return channels && channels.length > 0 ? channels[0] : 'PUSH';
}
