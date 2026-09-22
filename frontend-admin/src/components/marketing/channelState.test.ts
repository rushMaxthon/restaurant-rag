/**
 * What the picker claims about a channel, and what the send gate allows.
 *
 * These exist because a screenshot showed all six channels badged "NEEDS
 * SETUP" — including push, which is on by definition and had just been used
 * to send. Two separate pieces of logic read the same registry, and only one
 * of them was honouring `ALWAYS_ON`:
 *
 *   the badge      read `connection?.connected` alone, so a connections call
 *                  that had not answered yet, or had failed, rendered every
 *                  channel as needing setup — push included.
 *
 *   the send gate  read `availability !== 'ALWAYS_ON' && !connected`, which
 *                  is correct: push was never actually blocked from sending.
 *
 * So the product worked and the screen said it did not, which is the kind of
 * disagreement that costs an owner a support ticket rather than a campaign.
 * Both rules are pinned here, together, because the bug was the gap between
 * them.
 */

import { describe, expect, it } from 'vitest';
import { getChannel } from './channels';
import type { ChannelConnection, MarketingChannel } from '../../services/marketing/types';

/** The picker's badge rule, as `ChannelPicker` applies it. */
function badge(
  key: MarketingChannel,
  connections: Map<MarketingChannel, ChannelConnection> | undefined,
): 'ready' | 'checking' | 'paused' | 'needs-setup' {
  const channel = getChannel(key);
  const connection = connections?.get(key);
  const alwaysOn = channel.availability === 'ALWAYS_ON';
  if (alwaysOn || connection?.connected) {
    return 'ready';
  }
  if (connections === undefined) {
    return 'checking';
  }
  return connection?.status === 'DISABLED' ? 'paused' : 'needs-setup';
}

/** The editor's send rule, as `CampaignEditorPage` applies it. */
function blocked(
  key: MarketingChannel,
  connections: Map<MarketingChannel, ChannelConnection> | undefined,
): boolean {
  const channel = getChannel(key);
  const connection = connections?.get(key) ?? null;
  return channel.availability !== 'ALWAYS_ON' && !connection?.connected;
}

function connection(
  channel: MarketingChannel,
  overrides: Partial<ChannelConnection> = {},
): ChannelConnection {
  return {
    channel,
    family: 'DIRECT',
    connected: true,
    status: 'CONNECTED',
    config: {},
    identity: null,
    connected_at: null,
    verified_at: null,
    last_error: null,
    requirements: [],
    ...overrides,
  };
}

describe('what the picker claims', () => {
  it('shows push as ready before the channel list has answered', () => {
    // The screenshot bug. Push has no connection row and never will.
    expect(badge('PUSH', undefined)).toBe('ready');
  });

  it('shows push as ready even when the channel list failed', () => {
    expect(badge('PUSH', new Map())).toBe('ready');
  });

  it('does not guess about the other channels while it is still asking', () => {
    // "Needs setup" would be a claim we cannot support, and it is the claim
    // that sends an owner to a settings screen they did not need.
    expect(badge('WHATSAPP', undefined)).toBe('checking');
  });

  it('says needs setup once it actually knows', () => {
    expect(badge('WHATSAPP', new Map())).toBe('needs-setup');
  });

  it('says ready for a channel the restaurant connected', () => {
    const map = new Map([['WHATSAPP' as MarketingChannel, connection('WHATSAPP')]]);
    expect(badge('WHATSAPP', map)).toBe('ready');
  });

  it('distinguishes paused from never connected', () => {
    const map = new Map([
      [
        'SMS' as MarketingChannel,
        connection('SMS', { connected: false, status: 'DISABLED' }),
      ],
    ]);
    expect(badge('SMS', map)).toBe('paused');
  });

  it('never calls push paused, whatever the server says', () => {
    // There is no row to disable, so a row claiming otherwise is noise.
    const map = new Map([
      [
        'PUSH' as MarketingChannel,
        connection('PUSH', { connected: false, status: 'DISABLED' }),
      ],
    ]);
    expect(badge('PUSH', map)).toBe('ready');
  });
});

describe('what the send gate allows', () => {
  it('never blocks push, which is what kept it working through the bug', () => {
    expect(blocked('PUSH', undefined)).toBe(false);
    expect(blocked('PUSH', new Map())).toBe(false);
  });

  it('blocks a channel that is not connected', () => {
    expect(blocked('WHATSAPP', new Map())).toBe(true);
  });

  it('allows a channel the restaurant connected', () => {
    const map = new Map([['SMS' as MarketingChannel, connection('SMS')]]);
    expect(blocked('SMS', map)).toBe(false);
  });

  it('blocks a paused channel', () => {
    const map = new Map([
      [
        'SMS' as MarketingChannel,
        connection('SMS', { connected: false, status: 'DISABLED' }),
      ],
    ]);
    expect(blocked('SMS', map)).toBe(true);
  });
});

describe('the badge and the gate agree about push', () => {
  it('agrees in every state the connections call can be in', () => {
    // The bug was precisely that they did not.
    for (const connections of [
      undefined,
      new Map<MarketingChannel, ChannelConnection>(),
      new Map([['PUSH' as MarketingChannel, connection('PUSH')]]),
    ]) {
      expect(badge('PUSH', connections)).toBe('ready');
      expect(blocked('PUSH', connections)).toBe(false);
    }
  });
});
