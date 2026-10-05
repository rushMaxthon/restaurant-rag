import { Bike, MapPin, RotateCcw, TriangleAlert, XCircle } from 'lucide-react';
import { useEffect, useState } from 'react';

import { ApiError, api, formatDate } from '../services/api';
import {
  SIMULATE_STAGES,
  canCancelRider,
  isBadStep,
  nextEta,
  riderMapUrl,
  stepLabel,
} from '../services/courier';
import { useMoney } from '../hooks/useMoney';
import type { OrderDelivery, ToastMessage } from '../types/app';

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
  /**
   * True for a delivery order that has not been dispatched yet.
   *
   * Without this the card renders nothing at all before the kitchen accepts,
   * and an empty space where a courier should be reads as something broken
   * rather than as something that has not happened yet.
   */
  awaiting?: boolean;
  token: string;
  orderId: string;
  /** Said when a cancel, re-book or simulate succeeds or is refused. */
  onToast?: (title: string, description: string, tone?: ToastMessage['tone']) => void;
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

export function DeliveryPanel({ token, orderId, awaiting, onToast }: DeliveryPanelProps) {
  const money = useMoney();
  const [delivery, setDelivery] = useState<OrderDelivery | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  // Two presses to call a rider off, like the live board's buttons: the first
  // says what will happen, the second does it. No browser dialog, which
  // blocks the page for everyone watching it.
  const [confirmCancel, setConfirmCancel] = useState(false);
  // Bumped after an action, so the poll restarts from the new state - a
  // re-booked trip is live again and must be watched again.
  const [round, setRound] = useState(0);

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
          // Keep looking while there is anything left to happen, and that
          // INCLUDES having no row at all: a delivery order that has just been
          // accepted has no courier for a second or two while the task runs,
          // and stopping there left the card saying "no rider yet" over a
          // rider who had already been booked. Only a finished delivery, or a
          // pickup order with nothing to watch, ends the loop.
          const stillMoving = row ? !DONE.has(row.state) : Boolean(awaiting);
          if (stillMoving) timer = setTimeout(read, 10_000);
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
  }, [token, orderId, awaiting, round]);

  const act = async (
    run: () => Promise<OrderDelivery | null>,
    done: string,
  ) => {
    setBusy(true);
    try {
      const next = await run();
      setDelivery(next);
      onToast?.(done, '', 'success');
      setRound((count) => count + 1);
    } catch (error) {
      onToast?.(
        'The courier said no',
        error instanceof ApiError ? error.message : 'Please try again.',
        'error',
      );
    } finally {
      setBusy(false);
    }
  };

  if (loading) return null;

  // Nothing dispatched. For a delivery order that is a stage, not an absence,
  // so it says what will happen. For a pickup order there is no courier in the
  // story at all and the card stays away.
  if (!delivery) {
    if (!awaiting) return null;
    return (
      <section className="admin-surface order-detail__card">
        <header className="order-detail__card-header">
          <span className="order-detail__card-icon">
            <Bike size={17} strokeWidth={2.1} />
          </span>
          <div>
            <h2>Courier</h2>
            <p>Who is carrying this order, and where they are.</p>
          </div>
        </header>
        <p className="order-detail__courier-waiting">
          No rider yet. One is booked automatically the moment this order is
          accepted, and this card then shows who they are and how far they have
          to go.
        </p>
      </section>
    );
  }

  const state = STATES[delivery.state] ?? { label: delivery.state, tone: 'busy' as const };
  const eta = nextEta({
    state: delivery.state,
    pickup_eta: delivery.pickup_eta ?? null,
    drop_eta: delivery.drop_eta ?? null,
  });
  const mapUrl = riderMapUrl({
    rider_latitude: delivery.rider_latitude ?? null,
    rider_longitude: delivery.rider_longitude ?? null,
  });
  const timeline = delivery.timeline ?? [];
  const distanceKm =
    delivery.distance_metres != null ? (delivery.distance_metres / 1000).toFixed(1) : null;

  return (
    <section className="admin-surface order-detail__card">
      <header className="order-detail__card-header">
        <span className="order-detail__card-icon">
          <Bike size={17} strokeWidth={2.1} />
        </span>
        <div>
          {/* "Courier", not "Delivery". The card beside this one is
              "Fulfillment & delivery" and holds the address and the ETA, and
              two cards both called delivery is the page asking the reader to
              work out which is which. */}
          <h2>Courier</h2>
          <p>Who is carrying this order, and where they are.</p>
        </div>
      </header>

      {/* The one state that needs a person, said before the facts rather than
          buried among them. The order is deliberately left where it was. */}
      {delivery.state === 'FAILED' && (
        <p className="order-detail__fact-inline" style={{ color: 'var(--danger)' }}>
          <TriangleAlert size={14} strokeWidth={2.1} />
          The food was sent out and came back. The order has not been changed —
          somebody needs to decide what happens next.
          {delivery.failure_reason ? ` The courier said: “${delivery.failure_reason}”.` : ''}
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

        {eta && (
          <div className="order-detail__fact">
            <span>{eta.label}</span>
            <strong>{formatDate(eta.at)}</strong>
          </div>
        )}

        {mapUrl && delivery.rider_location_at && (
          <div className="order-detail__fact">
            <span>Rider last seen</span>
            <strong className="order-detail__fact-inline">
              <MapPin size={14} strokeWidth={2.1} />
              <a href={mapUrl} target="_blank" rel="noreferrer">
                On the map
              </a>
              <em>{formatDate(delivery.rider_location_at)}</em>
            </strong>
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

        {/* Only ever present for the platform admin: the server leaves it out
            for anybody else. */}
        {delivery.courier_charge != null && (
          <div className="order-detail__fact">
            <span>Courier charge</span>
            <strong>{money.format(Number(delivery.courier_charge))}</strong>
          </div>
        )}

        {(delivery.attempt ?? 1) > 1 && (
          <div className="order-detail__fact">
            <span>Booking</span>
            <strong>Rider #{delivery.attempt}</strong>
          </div>
        )}
      </div>

      {timeline.length > 0 && (
        <ol className="courier-timeline" aria-label="What the courier reported">
          {timeline.map((step, index) => (
            <li
              className={isBadStep(step.status) ? 'courier-timeline__step courier-timeline__step--bad' : 'courier-timeline__step'}
              key={`${step.status}-${step.at ?? index}`}
            >
              <span className="courier-timeline__dot" aria-hidden="true" />
              <strong>{stepLabel(step.status)}</strong>
              <span>
                {step.at ? formatDate(step.at) : ''}
                {step.remark ? ` · ${step.remark}` : ''}
              </span>
            </li>
          ))}
        </ol>
      )}

      {(canCancelRider(delivery) || delivery.can_rebook || delivery.can_allocate) && (
        <div className="courier-actions">
          {delivery.can_allocate && (
            <button
              className="primary-button"
              disabled={busy}
              onClick={() => void act(() => api.allocateOrderDelivery(token, orderId), 'Asked for a rider')}
              title="Ask the courier's rider networks again to take this order."
              type="button"
            >
              <RotateCcw size={15} strokeWidth={2.1} />
              Find a rider
            </button>
          )}
          {canCancelRider(delivery) && (
            <button
              className="secondary-button"
              disabled={busy}
              onBlur={() => setConfirmCancel(false)}
              onClick={() => {
                if (!confirmCancel) {
                  setConfirmCancel(true);
                  return;
                }
                setConfirmCancel(false);
                void act(() => api.cancelOrderDelivery(token, orderId), 'Rider called off');
              }}
              title="Cancel the courier booking. Possible until the rider picks the food up."
              type="button"
            >
              <XCircle size={15} strokeWidth={2.1} />
              {confirmCancel ? 'Tap again to call the rider off' : 'Cancel rider'}
            </button>
          )}
          {delivery.can_rebook && (
            <button
              className="primary-button"
              disabled={busy}
              onClick={() => void act(() => api.rebookOrderDelivery(token, orderId), 'New rider requested')}
              title="Ask the courier for another rider for this order."
              type="button"
            >
              <RotateCcw size={15} strokeWidth={2.1} />
              Book a new rider
            </button>
          )}
        </div>
      )}

      {delivery.can_simulate && delivery.provider_order_id && (
        <div className="courier-simulate">
          <span>Sandbox: make the courier report</span>
          <div>
            {SIMULATE_STAGES.map((stage) => (
              <button
                className="secondary-button secondary-button--ghost"
                disabled={busy}
                key={stage.status}
                onClick={() =>
                  void act(
                    () => api.simulateOrderDelivery(token, orderId, stage.status),
                    `Courier reported: ${stage.label}`,
                  )
                }
                type="button"
              >
                {stage.label}
              </button>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
