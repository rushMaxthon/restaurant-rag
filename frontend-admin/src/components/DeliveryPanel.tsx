import { Bike, TriangleAlert } from 'lucide-react';
import { useEffect, useState } from 'react';

import { api, formatDate } from '../services/api';
import type { OrderDelivery } from '../types/app';

/**
 * What the courier is doing with this order.
 *
 * Renders nothing at all when nobody was asked — a pickup order, or delivery
 * dispatch switched off. An empty "Delivery" card on every pickup order would
 * be noise on the screen somebody watches during service.
 *
 * The courier's own status word is shown beside ours on purpose. Ours is a
 * mapping of sixteen Pidge statuses onto seven, so when something unexpected
 * happens the mapped value alone cannot tell you what; `provider_status` can,
 * without anyone opening a log.
 *
 * FAILED is given the warning tone rather than the neutral one, because it is
 * the state that needs a person: the food was cooked, dispatched and came
 * back, and the order deliberately stays where it was rather than being
 * quietly closed. Nothing on this screen decides who pays for that.
 *
 * Built from the markup `OrderDetailPage` already uses for its cards, so it
 * needs no new CSS — this app has hand-written styles and no component
 * library, and a panel inventing its own classes is how that drifts.
 */
interface DeliveryPanelProps {
  token: string;
  orderId: string;
}

/** Our seven states, in words a person reads, and the tone each deserves. */
const STATES: Record<string, { label: string; tone: 'ok' | 'busy' | 'warn' }> = {
  PENDING: { label: 'Waiting for a rider', tone: 'busy' },
  ASSIGNED: { label: 'Rider on the way to the kitchen', tone: 'busy' },
  PICKED_UP: { label: 'Picked up', tone: 'busy' },
  IN_TRANSIT: { label: 'On the way to the customer', tone: 'busy' },
  DELIVERED: { label: 'Delivered', tone: 'ok' },
  CANCELLED: { label: 'Called off', tone: 'warn' },
  FAILED: { label: 'Could not be delivered', tone: 'warn' },
};

/** States a delivery cannot move on from, so there is nothing left to watch. */
const DONE = new Set(['DELIVERED', 'CANCELLED', 'FAILED']);

export function DeliveryPanel({ token, orderId }: DeliveryPanelProps) {
  const [delivery, setDelivery] = useState<OrderDelivery | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const read = () => {
      api
        .getOrderDelivery(token, orderId)
        .then((row) => {
          if (cancelled) return;
          setDelivery(row);
          // Keep watching while the rider is still moving, and STOP once the
          // delivery is over. A terminal state cannot change, so polling it
          // forever turns a fixed cost into one that grows with every order
          // this restaurant has ever completed.
          //
          // Ten seconds reads as live to somebody watching an order without
          // being a request per second per open tab. The server refreshes from
          // the courier every minute, so a faster poll here would mostly
          // re-read the same row.
          if (row && !DONE.has(row.state)) timer = setTimeout(read, 10_000);
        })
        .catch(() => {
          // A courier we cannot read about must not take the order screen down
          // with it. The rest of the page is what somebody came here for.
          if (cancelled) return;
          setDelivery(null);
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    };

    read();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [token, orderId]);

  // Nothing was dispatched, so there is nothing to say.
  if (loading || !delivery) return null;

  const state = STATES[delivery.state] ?? { label: delivery.state, tone: 'busy' as const };
  const distanceKm =
    delivery.distance_metres != null ? (delivery.distance_metres / 1000).toFixed(1) : null;

  return (
    <section className="admin-surface order-detail__card">
      <header className="order-detail__card-header">
        <span className="order-detail__card-icon">
          <Bike size={17} strokeWidth={2.1} />
        </span>
        <div>
          <h2>Delivery</h2>
          <p>What the courier is doing with this order.</p>
        </div>
      </header>

      {/* The one state that needs a person, said before the facts rather than
          buried among them. The order is deliberately left where it was. */}
      {delivery.state === 'FAILED' && (
        <p className="order-detail__fact-inline" style={{ color: 'var(--danger)' }}>
          <TriangleAlert size={14} strokeWidth={2.1} />
          The food was sent out and came back. The order has not been changed —
          somebody needs to decide what happens next.
        </p>
      )}

      {/* A dispatch that was refused. Without this, "no rider came" has no
          answer on the screen and the only record is in the worker log. */}
      {delivery.last_error && (
        <p className="order-detail__fact-inline" style={{ color: 'var(--danger)' }}>
          <TriangleAlert size={14} strokeWidth={2.1} />
          {delivery.last_error}
        </p>
      )}

      <div className="order-detail__facts">
        <div className="order-detail__fact">
          <span>Status</span>
          <strong>
            {state.label}
            {/* The courier's own word, so an unmapped status is still
                diagnosable from here. */}
            {delivery.provider_status && delivery.provider_status !== delivery.state && (
              <span className="order-detail__fact-inline"> ({delivery.provider_status})</span>
            )}
          </strong>
        </div>

        <div className="order-detail__fact">
          <span>Courier</span>
          <strong>
            {delivery.provider}
            {delivery.provider_order_id ? ` · ${delivery.provider_order_id}` : ''}
          </strong>
        </div>

        {delivery.rider_name && (
          <div className="order-detail__fact">
            <span>Rider</span>
            <strong className="order-detail__fact-inline">
              {delivery.rider_name}
              {delivery.rider_mobile && (
                <a href={`tel:${delivery.rider_mobile}`}>{delivery.rider_mobile}</a>
              )}
            </strong>
          </div>
        )}

        {distanceKm && (
          <div className="order-detail__fact">
            <span>Distance</span>
            <strong>{distanceKm} km</strong>
          </div>
        )}

        {delivery.picked_up_at && (
          <div className="order-detail__fact">
            <span>Picked up</span>
            <strong>{formatDate(delivery.picked_up_at)}</strong>
          </div>
        )}

        {delivery.delivered_at && (
          <div className="order-detail__fact">
            <span>Delivered</span>
            <strong>{formatDate(delivery.delivered_at)}</strong>
          </div>
        )}

        {delivery.tracking_url && (
          <div className="order-detail__fact">
            <span>Tracking</span>
            <strong>
              <a href={delivery.tracking_url} target="_blank" rel="noreferrer">
                Follow the rider
              </a>
            </strong>
          </div>
        )}
      </div>
    </section>
  );
}
