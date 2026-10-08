import { CheckCircle2, RefreshCw, UserCheck } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

import { ApiError, api, formatDate } from '../services/api';
import type { FleetDeliveryView, FleetOfferRow, Rider, ToastMessage } from '../types/app';
import { StatusPill } from './StatusPill';

const OUTCOME_LABEL: Record<FleetOfferRow['outcome'], string> = {
  PENDING: 'Looking at it',
  ACCEPTED: 'Accepted',
  DECLINED: 'Declined',
  EXPIRED: 'No answer',
  WITHDRAWN: 'Withdrawn',
};

const STEP_LABEL: Record<string, string> = {
  to_pickup: 'Going to the restaurant',
  at_pickup: 'At the restaurant',
  to_drop: 'Going to the customer',
  at_drop: 'At the customer',
  done: 'Finished',
};

/**
 * The platform's own riders on this order - admin only, inside the Courier
 * card: who was offered it and what each did, who is carrying it, and the
 * two things only a person can do (hand it to a named rider; confirm a
 * hand-over when the customer's code is locked or lost).
 */
export function FleetDeliverySection({
  token,
  orderId,
  onToast,
  onChanged,
}: {
  token: string;
  orderId: string;
  onToast?: (title: string, description: string, tone?: ToastMessage['tone']) => void;
  onChanged: () => void;
}) {
  const [view, setView] = useState<FleetDeliveryView | null>(null);
  const [online, setOnline] = useState<Rider[]>([]);
  const [pick, setPick] = useState('');
  const [reason, setReason] = useState('');
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .getFleetDelivery(token, orderId)
      .then((next) => {
        setView(next);
        setError(null);
      })
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : 'Could not load the riders on this order.'));
    api
      .listRiders(token)
      .then((rows) => setOnline(rows.filter((r) => r.is_active && r.status === 'ONLINE')))
      .catch(() => setOnline([]));
  }, [token, orderId]);

  useEffect(() => {
    load();
    const id = window.setInterval(load, 15_000);
    return () => window.clearInterval(id);
  }, [load]);

  async function run(action: () => Promise<FleetDeliveryView>, done: string) {
    setBusy(true);
    try {
      setView(await action());
      onToast?.(done, '', 'success');
      onChanged();
    } catch (e: unknown) {
      onToast?.('That did not work', e instanceof ApiError ? e.message : 'Please try again.', 'error');
    } finally {
      setBusy(false);
    }
  }

  if (error) return <p className="hint-text">{error}</p>;
  if (!view) return <p className="hint-text">Loading our riders…</p>;

  const finished = ['DELIVERED', 'CANCELLED', 'FAILED'].includes(view.state);
  const live = view.trip && !view.trip.ended_at ? view.trip : null;

  return (
    <div className="order-detail__facts">
      <div className="order-detail__fact">
        <span>Our riders</span>
        <strong>
          {view.provider === 'unassigned'
            ? 'Nobody could take it and no courier is set up'
            : live
              ? `${STEP_LABEL[live.step] ?? live.step}`
              : view.fallback_reason
                ? `Handed to the courier: ${view.fallback_reason}`
                : view.state === 'PENDING'
                  ? 'Offering to the nearest rider'
                  : view.state}
        </strong>
      </div>

      {view.offers.length > 0 ? (
        <div className="order-detail__fact">
          <span>Offered to</span>
          <strong>
            {view.offers
              .map((o) => `${o.rider_name} · ${OUTCOME_LABEL[o.outcome]}${o.metres ? ` (${(o.metres / 1000).toFixed(1)} km)` : ''}`)
              .join(' → ')}
          </strong>
        </div>
      ) : null}

      {view.trip?.ended_at ? (
        <div className="order-detail__fact">
          <span>Trip</span>
          <strong>
            {view.trip.end_reason ? <StatusPill status={view.trip.end_reason.replace(/_/g, ' ')} /> : null} ₹
            {view.trip.earning} to the rider · ended {formatDate(view.trip.ended_at)}
          </strong>
        </div>
      ) : null}

      {view.otp_locked ? (
        <p className="order-detail__fact-inline" style={{ color: 'var(--danger)' }}>
          The customer&rsquo;s code was entered wrong five times and is locked. Call the customer, then confirm below.
        </p>
      ) : null}

      {!finished && view.provider !== 'pidge' ? (
        <div className="courier-actions">
          <select
            aria-label="Rider to hand this order to"
            className="page-search page-search--select"
            disabled={busy || online.length === 0}
            onChange={(e) => setPick(e.target.value)}
            value={pick}
          >
            <option value="">{online.length ? 'Hand to a rider…' : 'No rider is online'}</option>
            {online.map((rider) => (
              <option key={rider.user_id} value={rider.user_id}>
                {rider.full_name}
              </option>
            ))}
          </select>
          <button
            className="secondary-button"
            disabled={busy || !pick}
            onClick={() => void run(() => api.reassignFleetDelivery(token, orderId, pick), 'Offered to the rider')}
            title={pick ? 'Offer this order to the chosen rider now' : 'Choose an online rider first'}
            type="button"
          >
            <RefreshCw size={14} /> Reassign
          </button>
          {live ? (
            <button className="secondary-button" disabled={busy} onClick={() => setConfirming((c) => !c)} type="button">
              <CheckCircle2 size={14} /> Confirm delivered
            </button>
          ) : null}
        </div>
      ) : null}

      {confirming && live ? (
        <div className="courier-actions">
          <input
            aria-label="Why you are confirming this delivery"
            className="page-search"
            onChange={(e) => setReason(e.target.value)}
            placeholder="Why? e.g. Customer confirmed on a call"
            value={reason}
          />
          <button
            className="primary-button"
            disabled={busy || reason.trim().length < 5}
            onClick={() =>
              void run(() => api.confirmFleetDelivered(token, orderId, reason.trim()), 'Marked delivered').then(() => {
                setConfirming(false);
                setReason('');
              })
            }
            title={reason.trim().length < 5 ? 'Write a short reason first; it is kept with the order' : 'Mark this order delivered'}
            type="button"
          >
            <UserCheck size={14} /> Confirm
          </button>
        </div>
      ) : null}
    </div>
  );
}
