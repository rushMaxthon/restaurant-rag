import { useEffect, useState } from 'react';
import { ApiError, api, formatCurrency, formatDateTime } from '../services/api';
import { OrderStepper } from '../components/OrderStepper';
import { Skeleton } from '../components/Skeleton';
import type { Order } from '../types/app';

interface OrdersPageProps {
  token: string | null;
  onNavigate: (path: string) => void;
  onToast: (title: string, description: string, tone?: 'success' | 'error' | 'info') => void;
}

export function OrdersPage({ token, onNavigate, onToast }: OrdersPageProps) {
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
        onToast('Orders unavailable', message, 'error');
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
      <div className="empty-state">
        <strong>Login to track your orders.</strong>
        <button className="primary-button primary-button--small" onClick={() => onNavigate('/auth/login')} type="button">
          Login
        </button>
      </div>
    );
  }

  return (
    <div className="page-stack">
      <section className="section-card">
        <div className="section-card__header">
          <div>
            <span className="eyebrow">Orders</span>
            <h2>Live delivery tracking</h2>
          </div>
          <span className="hint-text">Updates every 30 seconds</span>
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
            <span>Your placed orders will appear here with live status updates.</span>
          </div>
        ) : null}
      </section>
    </div>
  );
}
