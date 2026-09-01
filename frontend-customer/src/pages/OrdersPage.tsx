import { useCallback, useEffect, useMemo, useState } from 'react';
import { AppIcon } from '../components/AppIcon';
import { SignedOutGate } from '../components/app/SignedOutGate';
import { api, formatCurrency, formatDateTime } from '../services/api';
import { useAppConfig } from '../store/useAppConfig';
import type { Order } from '../types/app';

interface OrdersPageProps {
  token: string | null;
  onNavigate: (path: string) => void;
  onToast: (title: string, description: string, tone?: 'success' | 'error' | 'info') => void;
}

interface StatusTone {
  className: string;
  label: string;
}

/** `getStatusTone` in `mobile/src/screens/orders/orderList/OrderListScreen.tsx`. */
function statusTone(status: Order['status']): StatusTone {
  if (status === 'DELIVERED') {
    return { className: 'status-pill status-pill--done', label: 'Delivered' };
  }
  // A card order that was never paid. It is not in the kitchen queue, so it is
  // deliberately called out rather than shown as a normal live order.
  if (status === 'PAYMENT_PENDING') {
    return { className: 'status-pill status-pill--pending', label: 'Payment pending' };
  }
  if (status === 'CANCELLED') {
    return { className: 'status-pill status-pill--cancelled', label: 'Cancelled' };
  }
  if (status === 'PREPARING' || status === 'OUT_FOR_DELIVERY') {
    return {
      className: 'status-pill status-pill--live',
      label: status === 'PREPARING' ? 'Preparing' : 'On the way',
    };
  }
  return { className: 'status-pill', label: status.replaceAll('_', ' ') };
}

const ACTIVE_STATUSES = new Set<Order['status']>([
  'PLACED',
  'ACCEPTED',
  'PREPARING',
  'OUT_FOR_DELIVERY',
]);

/** `mobile/src/screens/orders/orderList/OrderListScreen.tsx`. */
export function OrdersPage({ token, onNavigate, onToast }: OrdersPageProps) {
  const { displayName, restaurantId } = useAppConfig();
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  /**
   * Fetch, then publish. Nothing is written to state before the first await:
   * a synchronous setState inside an effect makes React render twice on mount
   * for no reason, and this screen mounts on every tab switch to Orders.
   */
  const load = useCallback(async () => {
    if (!token) {
      return;
    }
    try {
      const rows = await api.getOrders(token);
      // This build is one restaurant's app, so it shows that restaurant's
      // orders. An account that has also ordered elsewhere keeps those orders —
      // they simply are not this app's history.
      setOrders(restaurantId ? rows.filter((row) => row.restaurant_id === restaurantId) : rows);
      setError(null);
    } catch (nextError) {
      const message =
        nextError instanceof Error ? nextError.message : 'Unable to load your order history.';
      setError(message);
      onToast('Orders unavailable', message, 'error');
    } finally {
      setLoading(false);
    }
  }, [onToast, restaurantId, token]);

  useEffect(() => {
    void load();
  }, [load]);

  /** The retry button, which unlike the mount path has a spinner to restore. */
  const retry = useCallback(() => {
    setLoading(true);
    void load();
  }, [load]);

  const activeCount = useMemo(
    () => orders.filter((order) => ACTIVE_STATUSES.has(order.status)).length,
    [orders],
  );
  const deliveredCount = useMemo(
    () => orders.filter((order) => order.status === 'DELIVERED').length,
    [orders],
  );

  if (!token) {
    return (
      <SignedOutGate
        icon="receipt"
        onNavigate={onNavigate}
        points={[
          'Live status from kitchen to doorstep',
          'Every bill, itemised and saved',
          'Reorder a past meal in two taps',
        ]}
        redirectPath="/orders"
        text={`Every ${displayName} order you place shows up here with live status and the full bill.`}
        title="Your orders live here"
      />
    );
  }

  return (
    <div className="screen orders-screen">
      <section className="orders-hero">
        <span aria-hidden="true" className="orders-hero__glow orders-hero__glow--primary" />
        <span aria-hidden="true" className="orders-hero__glow orders-hero__glow--secondary" />
        <span className="orders-hero__badge">
          <AppIcon name="time" size={13} />
          Live tracking
        </span>
        <h1 className="orders-hero__title">Orders that move with you.</h1>
        <p className="orders-hero__subtitle">
          Recent checkouts, delivery progress, and quick access to every bill.
        </p>
      </section>

      <div className="summary-row">
        <div className="summary-chip">
          <strong>{orders.length}</strong>
          <small>Total orders</small>
        </div>
        <div className="summary-chip">
          <strong>{activeCount}</strong>
          <small>Active</small>
        </div>
        <div className="summary-chip">
          <strong>{deliveredCount}</strong>
          <small>Delivered</small>
        </div>
      </div>

      {loading ? (
        <div className="stack">
          {Array.from({ length: 3 }, (_, index) => (
            <div className="order-row order-row--skeleton" key={index} />
          ))}
        </div>
      ) : error ? (
        <div className="empty-state">
          <p className="empty-state__title">We couldn&rsquo;t load your orders</p>
          <p className="empty-state__text">{error}</p>
          <button className="btn btn--ghost" onClick={retry} type="button">
            Retry
          </button>
        </div>
      ) : orders.length === 0 ? (
        <div className="empty-state">
          <p className="empty-state__title">No orders yet</p>
          <p className="empty-state__text">
            Once you place an order it will show up here with live status updates and bill
            details.
          </p>
          <button className="btn" onClick={() => onNavigate('/')} type="button">
            Browse the menu
          </button>
        </div>
      ) : (
        <div className="order-list">
          {orders.map((order) => {
            const tone = statusTone(order.status);
            return (
              <button
                className="order-row"
                key={order.id}
                onClick={() => onNavigate(`/orders/${order.id}`)}
                type="button"
              >
                <span className="order-row__thumb">
                  {order.restaurant.name.slice(0, 2).toUpperCase()}
                </span>
                <span className="order-row__copy">
                  <span className="order-row__title">
                    <strong>{order.restaurant.name}</strong>
                    <span className={tone.className}>{tone.label}</span>
                  </span>
                  <small className="order-row__meta">{formatDateTime(order.placed_at)}</small>
                  <span className="order-row__footer">
                    <small>
                      {order.items.length} item{order.items.length === 1 ? '' : 's'}
                    </small>
                    <strong>{formatCurrency(order.total_amount)}</strong>
                  </span>
                  {order.status === 'PAYMENT_PENDING' ? (
                    <span className="order-row__alert">
                      <AppIcon name="card" size={13} />
                      Payment pending — open to complete
                    </span>
                  ) : null}
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
