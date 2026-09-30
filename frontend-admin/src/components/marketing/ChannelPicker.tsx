/**
 * "Where do you want to run your campaign?" — the first question now.
 *
 * It used to be the fourth, and it was a row of six checkboxes, five of them
 * `disabled` with the words "arrives in Phase 2". An owner cannot act on that:
 * it reads as a broken screen rather than a roadmap, and by the time they saw
 * it they had already written push copy against a lock screen.
 *
 * Three things make this screen work:
 *
 *   - Two headings do the teaching. "Send it straight to your customers" and
 *     "Post it for your followers" is the whole DIRECT/SOCIAL distinction, in
 *     words an owner already owns. Nobody has to learn what a channel family is.
 *   - Every card carries its own number and its own cost. Reach and money are
 *     what the choice is actually made on, so they are on the card and not
 *     two screens later.
 *   - Nothing is dead. A channel that cannot send yet says so, says what it
 *     would take, and still lets the owner build the campaign and save it.
 *     Refusing at the send step is honest; refusing at the door is a wall.
 */

import { Check, Clock, Info } from 'lucide-react';
import { channelsInFamily, getChannel, type ChannelFamily } from './channels';
import { pluralize } from '../../services/format';
import type { ChannelConnection, MarketingChannel } from '../../services/marketing/types';

interface ChannelPickerProps {
  selected: MarketingChannel | null;
  onSelect: (channel: MarketingChannel) => void;
  /**
   * How many people this channel could reach, keyed by channel.
   *
   * Absent while the count is still loading, and absent entirely for the
   * social channels — a follower count is not a reach estimate and pretending
   * otherwise is the mistake this whole redesign is trying to undo.
   */
  reachByChannel: Partial<Record<MarketingChannel, number>>;
  loading?: boolean;
  /**
   * What this restaurant has actually connected, from the server.
   *
   * Absent while it loads, which is why the cards fall back to the registry's
   * "needs connection" rather than claiming either state — showing "Ready"
   * for a second and then taking it away is worse than showing nothing.
   */
  connections?: Map<MarketingChannel, ChannelConnection>;
  /** Opens the screen where a channel actually gets connected. */
  onManage?: () => void;
}

const FAMILY_COPY: Record<ChannelFamily, { title: string; sub: string }> = {
  DIRECT: {
    title: 'Send it straight to your customers',
    sub: 'You choose who gets it. Only people who agreed to hear from you.',
  },
  SOCIAL: {
    title: 'Post it for your followers',
    sub: 'Anyone can see it. You cannot choose who — you can pay to reach more.',
  },
};

export function ChannelPicker({
  selected,
  onSelect,
  reachByChannel,
  loading = false,
  connections,
  onManage,
}: ChannelPickerProps) {
  const chosen = selected ? getChannel(selected) : null;
  const chosenConnection = selected ? connections?.get(selected) : undefined;
  const chosenIsLive = Boolean(chosenConnection?.connected);

  return (
    <>
      {(['DIRECT', 'SOCIAL'] as ChannelFamily[]).map((family) => (
        <div className="mkt-section" key={family}>
          <span className="mkt-section__label">
            {FAMILY_COPY[family].title} <span>{FAMILY_COPY[family].sub}</span>
          </span>

          <div className="mkt-grid mkt-grid--2">
            {channelsInFamily(family).map((channel) => {
              const Icon = channel.icon;
              const isSelected = selected === channel.key;
              const reach = reachByChannel[channel.key];
              const connection = connections?.get(channel.key);
              // Push is on by definition — its credentials are the
              // platform's shared Firebase account, there is no row for it
              // and nothing an owner could disconnect. Reading its state off
              // the connections response made it render "needs setup"
              // whenever that call had not answered yet or had failed, which
              // is the one channel where that can never be true.
              const alwaysOn = channel.availability === 'ALWAYS_ON';
              const live = alwaysOn || Boolean(connection?.connected);
              const paused = !alwaysOn && connection?.status === 'DISABLED';
              // We have not been told yet. "Needs setup" would be a claim we
              // cannot support, and it is the claim that costs an owner a
              // trip to a settings screen they did not need.
              const unknown = !alwaysOn && connections === undefined;

              return (
                <button
                  aria-pressed={isSelected}
                  className={[
                    'mkt-pick',
                    'mkt-channel',
                    isSelected ? 'mkt-pick--selected' : null,
                  ]
                    .filter(Boolean)
                    .join(' ')}
                  key={channel.key}
                  onClick={() => onSelect(channel.key)}
                  type="button"
                >
                  <span aria-hidden="true" className="mkt-pick__tick">
                    <Check size={12} strokeWidth={3.4} />
                  </span>

                  <span className="mkt-pick__row">
                    <span aria-hidden="true" className="mkt-pick__icon">
                      <Icon size={19} strokeWidth={2.1} />
                    </span>
                    {live ? (
                      <span className="mkt-status mkt-status--sent">Ready to use</span>
                    ) : unknown ? (
                      <span className="mkt-status mkt-status--draft">Checking…</span>
                    ) : paused ? (
                      <span className="mkt-status mkt-status--cancelled">Paused</span>
                    ) : (
                      <span className="mkt-status mkt-status--scheduled">
                        <Clock size={11} strokeWidth={2.6} />
                        Needs setup
                      </span>
                    )}
                  </span>

                  <span className="mkt-pick__title">{channel.label}</span>
                  <span className="mkt-pick__text">{channel.tagline}</span>

                  <span className="mkt-channel__facts">
                    <span className="mkt-channel__reach">
                      {/* Three different answers, because there are three
                          different truths. A social post has followers, not a
                          reachable count. A channel that is not switched on
                          has no count either — and printing "0 people" for it,
                          which is what a naive reach call returns, would read
                          as "nobody uses SMS" rather than "SMS is off". */}
                      {channel.family === 'SOCIAL'
                        ? connection?.identity
                          ? `Posting as ${connection.identity}`
                          : 'Everyone who follows you'
                        : !live
                          ? 'Counted once it is switched on'
                          : loading || reach === undefined
                            ? 'Counting…'
                            : `${pluralize(reach, 'person', 'people')} you can reach`}
                    </span>
                    <span className="mkt-channel__cost">{channel.cost}</span>
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      ))}

      {/* The old flow's dead end, turned into a task. Shown only once a
          channel that needs work is chosen, so it never pre-empts the choice. */}
      {chosen && chosen.availability === 'NEEDS_CONNECTION' && !chosenIsLive ? (
        <div className="mkt-setup-panel">
          <span aria-hidden="true" className="mkt-notice__icon">
            <Info size={15} strokeWidth={2.3} />
          </span>
          <div className="mkt-setup-panel__copy">
            <strong>{chosen.label} is not switched on yet</strong>
            <p>
              You can still build the whole campaign now and we will save it. It only
              needs these before it can go out:
            </p>
            <ul>
              {chosen.setup.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
            {onManage ? (
              <button className="mkt-btn mkt-btn--ghost mkt-btn--sm" onClick={onManage} type="button">
                Connect {chosen.label} now
              </button>
            ) : null}
            <p className="mkt-field__hint">
              {chosenConnection?.last_error
                ? chosenConnection.last_error
                : 'Push notifications work today if you would rather send something now.'}
            </p>
          </div>
        </div>
      ) : null}
    </>
  );
}
