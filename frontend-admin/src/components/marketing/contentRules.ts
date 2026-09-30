/**
 * Whether the words an owner has written can actually go out on this channel.
 *
 * Kept out of `ContentStep.tsx` so that file exports a component and nothing
 * else, which is what React Fast Refresh needs to hot-swap it without
 * remounting the form mid-edit. Same reasoning as `noticeUtils.ts`.
 *
 * The rules themselves belong to the registry, not to this file: a channel
 * that requires a photo is the same fact as the field that asks for one. The
 * backend re-checks every one of them at send time — this is the courtesy
 * that stops an owner reaching the last screen before finding out.
 */

import { getChannel } from './channels';
import { findUnknownTokens } from './mergeFields';
import type { CampaignContent, MarketingChannel } from '../../services/marketing/types';

/** The first reason this content cannot go out, or null when it can. */
export function contentBlocker(
  channel: MarketingChannel,
  content: CampaignContent,
): string | null {
  const definition = getChannel(channel);
  const spec = definition.content;

  if (spec.title && content.title.trim().length === 0) {
    return `Write ${spec.title.label === 'Subject line' ? 'a subject line' : `a ${spec.title.label.toLowerCase()}`} — it is the line people actually read.`;
  }
  if (spec.title && content.title.length > spec.title.limit) {
    return `The ${spec.title.label.toLowerCase()} is longer than ${definition.label} will show.`;
  }
  if (content.body.trim().length === 0) {
    return `Write the ${spec.body.label.toLowerCase()}.`;
  }
  if (content.body.length > spec.body.limit) {
    return `The ${spec.body.label.toLowerCase()} is longer than ${definition.label} allows.`;
  }
  if (spec.templateOnly && !content.template_id) {
    return 'Pick one of the approved layouts — WhatsApp will not deliver anything else.';
  }
  if (spec.image === 'required' && !content.extra.image_url) {
    return `${definition.label} needs a photo or a video. Add a link to one.`;
  }
  if (spec.mergeFields) {
    const unknown = findUnknownTokens(`${content.title} ${content.body}`);
    if (unknown.length > 0) {
      return `${unknown.join(', ')} is not a field we can fill in.`;
    }
  }
  return null;
}
