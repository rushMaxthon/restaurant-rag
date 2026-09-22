import { Users } from 'lucide-react';
import { formatCurrency } from '../../services/api';
import { pluralize } from '../../services/format';
import { CHANNEL_META } from './meta';
import type { ChannelReach } from '../../services/marketing/types';

interface ReachSummaryProps {
  /** Total in the audience before per-channel consent and device checks. */
  audienceSize: number;
  segmentName: string;
  channels: ChannelReach[];
  loading?: boolean;
}

/**
 * Who this will actually get to, per channel, with the gap itemised.
 *
 * Showing "34 customers" and then delivering to 31 is how a marketing tool
 * loses an owner's trust on day one. Every person who will not receive the
 * message is accounted for by name of reason, before anything is sent.
 */
export function ReachSummary({
  audienceSize,
  segmentName,
  channels,
  loading = false,
}: ReachSummaryProps) {
  return (
    <div className="mkt-section">
      <div className="mkt-reach-head">
        <span className="mkt-reach-head__label">
          <Users size={13} strokeWidth={2.3} />
          {segmentName}
        </span>
        <strong className="mkt-reach-head__value">
          {loading ? '—' : audienceSize.toLocaleString('en-CA')}
        </strong>
        <span className="mkt-reach-head__note">
          in your selected branches
        </span>
      </div>

      <ul className="mkt-reach">
        {channels.map((channel) => {
          const meta = CHANNEL_META[channel.channel];
          const Icon = meta.icon;

          return (
            <li
              className={
                channel.available
                  ? 'mkt-reach__item'
                  : 'mkt-reach__item mkt-reach__item--off'
              }
              key={channel.channel}
            >
              <span aria-hidden="true" className="mkt-reach__icon">
                <Icon size={14} strokeWidth={2.2} />
              </span>

              <div className="mkt-reach__copy">
                <strong>{meta.label}</strong>
                {channel.available ? (
                  <span>
                    {loading
                      ? 'Counting…'
                      : `${pluralize(channel.reachable, 'person', 'people')} reachable`}
                    {channel.estimated_cost > 0
                      ? ` · about ${formatCurrency(channel.estimated_cost)}`
                      : ' · free'}
                  </span>
                ) : (
                  <span>{channel.unavailable_reason}</span>
                )}

                {channel.available && channel.blockers.length > 0 && !loading ? (
                  <ul className="mkt-reach__blockers">
                    {channel.blockers.map((blocker) => (
                      <li key={blocker.reason}>
                        <span>{blocker.reason}</span>
                        <span>{blocker.count}</span>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>

              {channel.available ? (
                <strong className="mkt-reach__count">
                  {loading ? '—' : channel.reachable}
                </strong>
              ) : (
                <span className="mkt-status mkt-status--draft">Phase 2</span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
