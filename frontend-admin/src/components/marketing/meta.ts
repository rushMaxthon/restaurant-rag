/**
 * Presentation metadata for the Hub's domain values.
 *
 * Icons live here rather than in `mockData.ts` because they are how a thing
 * *looks*, not what it is — the backend will never send a lucide component.
 * Keeping the map here means the API response stays clean and a goal added
 * server-side simply falls back to a sensible default glyph.
 */

import {
  Bell,
  CalendarClock,
  Crown,
  Facebook,
  Heart,
  Instagram,
  Mail,
  Megaphone,
  MessageCircle,
  PartyPopper,
  Repeat,
  Smartphone,
  Sparkles,
  Store,
  UserPlus,
  UserRoundX,
  Users,
  Utensils,
  Wallet,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type {
  CampaignGoalKey,
  CampaignStatus,
  MarketingChannel,
  SegmentKey,
} from '../../services/marketing/types';

export const CHANNEL_META: Record<
  MarketingChannel,
  { label: string; short: string; icon: LucideIcon; phase: 'P1' | 'P2' }
> = {
  PUSH: { label: 'Push notification', short: 'Push', icon: Bell, phase: 'P1' },
  EMAIL: { label: 'Email', short: 'Email', icon: Mail, phase: 'P2' },
  SMS: { label: 'SMS', short: 'SMS', icon: Smartphone, phase: 'P2' },
  WHATSAPP: { label: 'WhatsApp', short: 'WhatsApp', icon: MessageCircle, phase: 'P2' },
  FACEBOOK: { label: 'Facebook', short: 'Facebook', icon: Facebook, phase: 'P2' },
  INSTAGRAM: { label: 'Instagram', short: 'Instagram', icon: Instagram, phase: 'P2' },
};

export const GOAL_ICONS: Record<CampaignGoalKey, LucideIcon> = {
  WINBACK: Repeat,
  PROMOTE_DISH: Utensils,
  NEW_ITEM: Sparkles,
  QUIET_DAY: CalendarClock,
  REWARD_VIPS: Crown,
  FIRST_TO_REGULAR: UserPlus,
  ANNOUNCEMENT: Megaphone,
  CUSTOM: PartyPopper,
};

export const SEGMENT_ICONS: Record<SegmentKey, LucideIcon> = {
  LAPSED_REGULARS: Repeat,
  FIRST_TIME_BUYERS: UserPlus,
  VIPS: Crown,
  BIG_SPENDERS: Wallet,
  WEEKEND_DINERS: CalendarClock,
  DISH_FANS: Heart,
  BRANCH_CUSTOMERS: Store,
  NEVER_ORDERED: UserRoundX,
};

/** Fallback so an unknown key from a future backend still renders. */
export const FALLBACK_ICON: LucideIcon = Users;

export function statusClass(status: CampaignStatus): string {
  return `mkt-status mkt-status--${status.toLowerCase()}`;
}

export function statusLabel(status: CampaignStatus): string {
  return status.charAt(0) + status.slice(1).toLowerCase();
}
