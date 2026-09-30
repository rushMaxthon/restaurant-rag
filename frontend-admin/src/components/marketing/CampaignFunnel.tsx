import type { AttributionReport, DeliveryBreakdown } from '../../services/marketing/types';

interface CampaignFunnelProps {
  audienceSize: number;
  delivery: DeliveryBreakdown;
  attribution: AttributionReport | null;
}

interface FunnelRow {
  label: string;
  value: number;
  /** Rate against the previous stage, already worded. Null on the first row. */
  rate: string | null;
  /** Metrics a channel cannot report show a dash and a reason, never a zero. */
  unavailable?: string;
  /** The row the whole campaign was for. */
  goal?: boolean;
}

function rate(value: number, base: number): string | null {
  if (base <= 0) {
    return null;
  }
  return `${Math.round((value / base) * 100)}% of previous`;
}

/**
 * The chain from "we sent it" to "they ordered".
 *
 * Each stage is measured against the stage above it rather than against the
 * audience, because that is the question an owner is actually asking: not
 * "what fraction of everyone clicked" but "of the people who opened it, how
 * many acted". The last row carries the emphasis colour — it is the only one
 * that pays for the campaign.
 */
export function CampaignFunnel({
  audienceSize,
  delivery,
  attribution,
}: CampaignFunnelProps) {
  const rows: FunnelRow[] = [
    { label: 'Targeted', value: audienceSize, rate: null },
    { label: 'Sent', value: delivery.sent, rate: rate(delivery.sent, audienceSize) },
    {
      label: 'Delivered',
      value: delivery.delivered,
      rate: rate(delivery.delivered, delivery.sent),
    },
    {
      label: 'Opened',
      value: delivery.opened,
      rate: rate(delivery.opened, delivery.delivered),
    },
    {
      label: 'Clicked',
      value: delivery.clicked,
      rate: rate(delivery.clicked, delivery.opened),
    },
    {
      label: 'Ordered',
      value: attribution?.orders ?? 0,
      rate: attribution ? rate(attribution.orders, delivery.clicked) : null,
      unavailable: attribution ? undefined : 'No window open yet',
      goal: true,
    },
  ];

  const max = Math.max(...rows.map((row) => row.value), 1);

  return (
    <ol className="mkt-funnel">
      {rows.map((row) => (
        <li
          className={row.goal ? 'mkt-funnel__row mkt-funnel__row--goal' : 'mkt-funnel__row'}
          key={row.label}
        >
          <span className="mkt-funnel__label">{row.label}</span>
          <span className="mkt-funnel__track">
            <span
              className="mkt-funnel__bar"
              style={{
                width: `${Math.max((row.value / max) * 100, row.value > 0 ? 5 : 0)}%`,
              }}
            />
          </span>
          <span className="mkt-funnel__value">
            <strong>{row.unavailable ? '—' : row.value.toLocaleString('en-CA')}</strong>
            {row.unavailable ? (
              <small>{row.unavailable}</small>
            ) : row.rate ? (
              <small>{row.rate}</small>
            ) : null}
          </span>
        </li>
      ))}
    </ol>
  );
}
