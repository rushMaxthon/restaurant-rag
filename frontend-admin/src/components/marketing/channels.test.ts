/**
 * Invariants the channel-first flow depends on.
 *
 * Every one of these is a question that was decided while building the
 * redesign, and each would fail silently rather than loudly if it regressed:
 * a channel with no goals renders an empty step 2 that cannot be completed, a
 * social channel with merge fields offers `{first_name}` on a post that has no
 * recipient, and an SMS length that ignores the mandatory opt-out footer
 * understates the bill by exactly one message on a long text.
 */

import { describe, expect, it } from 'vitest';
import {
  CHANNELS,
  channelsInFamily,
  estimateSpend,
  getChannel,
  goalFitsChannel,
  messageParts,
  primaryChannel,
} from './channels';

describe('the channel registry', () => {
  it('covers every channel the wire can name, exactly once', () => {
    const keys = CHANNELS.map((channel) => channel.key);
    expect(new Set(keys).size).toBe(keys.length);
    expect(keys).toEqual(
      expect.arrayContaining(['PUSH', 'WHATSAPP', 'SMS', 'EMAIL', 'INSTAGRAM', 'FACEBOOK']),
    );
  });

  it('splits into the two families the flow branches on', () => {
    expect(channelsInFamily('DIRECT').length).toBeGreaterThan(0);
    expect(channelsInFamily('SOCIAL').map((channel) => channel.key)).toEqual([
      'INSTAGRAM',
      'FACEBOOK',
    ]);
  });

  it('leaves push as the only channel that needs no connecting', () => {
    // Every other channel's availability is a fact about the restaurant, not
    // about the build: it comes from `GET /marketing/channels`. This asserts
    // only that push is the one exception, which is true because its
    // credentials are the platform's shared Firebase account.
    const alwaysOn = CHANNELS.filter((channel) => channel.availability === 'ALWAYS_ON');
    expect(alwaysOn.map((channel) => channel.key)).toEqual(['PUSH']);
  });

  it('never offers personalisation on a post nobody receives individually', () => {
    for (const channel of channelsInFamily('SOCIAL')) {
      expect(channel.content.mergeFields).toBe(false);
      // A public post has no tap destination of its own, and no one to be
      // sent to — so it also cannot carry a deep link.
      expect(channel.content.deepLink).toBe(false);
    }
  });

  it('refuses the goals a broadcast post cannot deliver', () => {
    const instagram = getChannel('INSTAGRAM');
    // Winback is defined by who receives it, and an organic post cannot pick.
    expect(goalFitsChannel(instagram, 'WINBACK')).toBe(false);
    expect(goalFitsChannel(instagram, 'PROMOTE_DISH')).toBe(true);
    // An empty list means every goal, which is how the direct channels are
    // declared — a channel that filtered to nothing would strand step 2.
    expect(goalFitsChannel(getChannel('PUSH'), 'WINBACK')).toBe(true);
  });

  it('gives every social channel at least one goal to choose from', () => {
    for (const channel of channelsInFamily('SOCIAL')) {
      expect(channel.goals.length).toBeGreaterThan(0);
    }
  });

  it('falls back to push for a channel this build has never heard of', () => {
    expect(getChannel(undefined).key).toBe('PUSH');
    expect(getChannel('TELEGRAM' as never).key).toBe('PUSH');
    expect(primaryChannel([])).toBe('PUSH');
    expect(primaryChannel(undefined)).toBe('PUSH');
    expect(primaryChannel(['INSTAGRAM'])).toBe('INSTAGRAM');
  });
});

describe('what a send costs', () => {
  const sms = getChannel('SMS');

  it('counts the opt-out footer, which the operator bills for too', () => {
    const footerLength = (sms.content.footer ?? '').length + 1;
    // One character short of a second part before the footer is added, and
    // over it once the footer is counted. This is the case that was wrong.
    const text = 'x'.repeat(160 - footerLength + 1);
    expect(messageParts(text, sms.content)).toBe(2);
  });

  it('calls an empty message one part, not zero', () => {
    // "0 messages, ₹0" would read as "SMS is free" to someone who has not
    // typed yet, which is the opposite of true.
    expect(messageParts('', sms.content)).toBe(1);
  });

  it('charges nothing on the channels that are free', () => {
    expect(estimateSpend(getChannel('PUSH'), 5000, 'anything')).toBe(0);
    expect(estimateSpend(getChannel('INSTAGRAM'), 5000, 'anything')).toBe(0);
  });

  it('multiplies parts by people, not just people', () => {
    const short = estimateSpend(sms, 100, 'short');
    const long = estimateSpend(sms, 100, 'x'.repeat(400));
    expect(long).toBeGreaterThan(short);
    expect(short).toBeCloseTo(sms.content.perMessageCost * 100, 5);
  });
});
