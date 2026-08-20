import { useEffect, useState } from 'react';
import { ApiError, api, formatCurrency, formatDateTime } from '../services/api';
import { OrderStepper } from '../components/OrderStepper';
import { Skeleton } from '../components/Skeleton';
import type { Order } from '../types/app';

interface ProfileOrdersPageProps {
  token: string | null;
  onNavigate: (path: string) => void;
  onToast: (title: string, description: string, tone?: 'success' | 'error' | 'info') => void;
}

export function ProfileOrdersPage({ token, onNavigate, onToast }: ProfileOrdersPageProps) {
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(Boolean(token));

  useEffect(() => {
    let active = true;

    const loadOrders = async () => {
      if (!token) {
        if (active) {
          setLoading(false);
        }
        return;
      }

      try {
        const rows = await api.getOrders(token);
        if (active) {
          setOrders(rows);
        }
      } catch (error: unknown) {
        if (!active) {
          return;
        }

        const message = error instanceof ApiError ? error.message : 'Unable to fetch your orders.';
        onToast('Order history unavailable', message, 'error');
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    };

    void loadOrders();
    const intervalId = window.setInterval(() => {
      void loadOrders();
    }, 30000);

    return () => {
      active = false;
      window.clearInterval(intervalId);
    };
  }, [onToast, token]);

  if (!token) {
    return (
      <div className="page-stack">
        <section className="hero-panel hero-panel--compact">
          <div className="hero-panel__copy">
            <span className="eyebrow">Order history</span>
            <h1>Login to follow every delivery.</h1>
            <p>Track live statuses, review your previous meals, and keep your reorder flow close to profile.</p>
            <div className="hero-panel__actions">
              <button className="primary-button" onClick={() => onNavigate('/auth/login')} type="button">
                Login
              </button>
              <button className="secondary-button" onClick={() => onNavigate('/auth/register')} type="button">
                Create account
              </button>
            </div>
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="page-stack">
      <section className="hero-panel hero-panel--compact">
        <div className="hero-panel__copy">
          <span className="eyebrow">Order history</span>
          <h1>Your food timeline, all in one place.</h1>
          <p>See every recent order, live delivery step, and total spend without leaving your profile flow.</p>
          <div className="profile-subnav">
            <button className="secondary-button" onClick={() => onNavigate('/profile')} type="button">
              Back to profile
            </button>
            <div className="profile-meta-pill">Updates every 30 seconds</div>
          </div>
        </div>
      </section>

      <section className="section-card">
        <div className="section-card__header">
          <div>
            <span className="eyebrow">Orders</span>
            <h2>Recent and active deliveries</h2>
          </div>
        </div>
        <div className="orders-list">
          {loading
            ? Array.from({ length: 3 }).map((_, index) => (
                <Skeleton className="order-card order-card--skeleton" key={index} />
              ))
            : orders.map((order) => (
                <button
                  className="order-card order-card--interactive"
                  key={order.id}
                  onClick={() => onNavigate(`/orders/${order.id}`)}
                  type="button"
                >
                  <div className="order-card__header">
                    <div>
                      <strong>{order.restaurant.name}</strong>
                      <span>{formatDateTime(order.placed_at)}</span>
                    </div>
                    <div className="order-card__amount">
                      <strong>{formatCurrency(order.total_amount)}</strong>
                      <span>{order.items.length} items</span>
                    </div>
                  </div>
                  <div className="order-card__items">
                    {order.items.map((item) => item.item_name_snapshot).slice(0, 3).join(' • ')}
                  </div>
                  <OrderStepper status={order.status} />
                </button>
              ))}
        </div>
        {!loading && orders.length === 0 ? (
          <div className="empty-state">
            <strong>No orders yet.</strong>
            <span>Your placed orders will appear here with live status updates and reorder context.</span>
          </div>
        ) : null}
      </section>
    </div>
  );
}
