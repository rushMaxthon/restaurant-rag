import { useEffect, useMemo, useState } from 'react';
import { ApiError, api, formatCurrency, formatDateTime } from '../services/api';
import { OrderStepper } from '../components/OrderStepper';
import { Skeleton } from '../components/Skeleton';
import { useAppStore } from '../hooks/useAppStore';

interface OrderDetailPageProps {
  orderId: string;
  token: string | null;
  onNavigate: (path: string) => void;
  onToast: (title: string, description: string, tone?: 'success' | 'error' | 'info') => void;
}

export function OrderDetailPage({
  orderId,
  token,
  onNavigate,
  onToast,
}: OrderDetailPageProps) {
  const { setPendingAuthRedirectPath } = useAppStore();
  const [order, setOrder] = useState<Awaited<ReturnType<typeof api.getOrder>> | null>(null);
  const [loading, setLoading] = useState(Boolean(token));
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function loadOrderDetail() {
      if (!token) {
        if (active) {
          setLoading(false);
        }
        return;
      }

      setLoading(true);
      setError(null);

      try {
        const response = await api.getOrder(token, orderId);
        if (active) {
          setOrder(response);
        }
      } catch (nextError: unknown) {
        if (!active) {
          return;
        }
        const message =
          nextError instanceof ApiError ? nextError.message : 'Unable to load this order right now.';
        setError(message);
        onToast('Order unavailable', message, 'error');
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void loadOrderDetail();

    return () => {
      active = false;
    };
  }, [onToast, orderId, token]);

  const shortId = useMemo(
    () => `#${orderId.replaceAll('-', '').slice(-8).toUpperCase()}`,
    [orderId],
  );

  if (!token) {
    return (
      <div className="page-stack">
        <section className="section-card">
          <div className="empty-state empty-state--with-actions">
            <strong>Login to view this order.</strong>
            <span>Tracking, bill details, and delivery history are available after login.</span>
            <div className="empty-state__actions">
              <button
                className="primary-button primary-button--small"
                onClick={() => {
                  setPendingAuthRedirectPath(`/orders/${orderId}`);
                  onNavigate('/auth/login');
                }}
                type="button"
              >
                Login
              </button>
            </div>
          </div>
        </section>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="page-stack">
        <section className="section-card order-detail-page">
          <Skeleton className="order-detail-hero order-detail-hero--skeleton" />
          <Skeleton className="order-detail-section" />
          <Skeleton className="order-detail-section" />
          <Skeleton className="order-detail-section" />
        </section>
      </div>
    );
  }

  if (error || !order) {
    return (
      <div className="page-stack">
        <section className="section-card">
          <div className="empty-state empty-state--with-actions">
            <strong>We couldn’t load this order.</strong>
            <span>{error ?? 'The order may no longer be available.'}</span>
            <div className="empty-state__actions">
              <button
                className="primary-button primary-button--small"
                onClick={() => onNavigate('/orders')}
                type="button"
              >
                Back to orders
              </button>
            </div>
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="page-stack">
      <section className="section-card order-detail-page">
        <div className="order-detail-hero">
          <div>
            <span className="eyebrow">Order tracking</span>
            <h1>{order.restaurant.name}</h1>
            <p>{shortId} • {formatDateTime(order.placed_at)}</p>
          </div>
          <button className="secondary-button secondary-button--small" onClick={() => onNavigate('/orders')} type="button">
            Back to orders
          </button>
        </div>

        <div className="order-detail-grid">
          <div className="order-detail-section">
            <div className="order-detail-section__header">
              <strong>Status</strong>
              <span>{order.status.replaceAll('_', ' ')}</span>
            </div>
            <OrderStepper status={order.status} />
          </div>

          <div className="order-detail-section">
            <div className="order-detail-section__header">
              <strong>Delivery</strong>
              <span>{order.payment_status.replaceAll('_', ' ')}</span>
            </div>
            <p>{order.delivery_address}</p>
            {order.special_instructions ? (
              <p className="order-detail-note">Notes: {order.special_instructions}</p>
            ) : null}
          </div>
        </div>

        <div className="order-detail-grid">
          <div className="order-detail-section">
            <div className="order-detail-section__header">
              <strong>Items</strong>
              <span>{order.items.length}</span>
            </div>
            <div className="order-detail-items">
              {order.items.map((item) => (
                <div className="order-detail-item" key={item.id}>
                  <div>
                    <strong>{item.item_name_snapshot}</strong>
                    <span>{item.quantity} × {formatCurrency(item.unit_price)}</span>
                  </div>
                  <strong>{formatCurrency(item.total_price)}</strong>
                </div>
              ))}
            </div>
          </div>

          <div className="order-detail-section">
            <div className="order-detail-section__header">
              <strong>Bill summary</strong>
              <span>{order.currency}</span>
            </div>
            <div className="order-detail-summary-row"><span>Subtotal</span><strong>{formatCurrency(order.subtotal)}</strong></div>
            <div className="order-detail-summary-row"><span>Delivery fee</span><strong>{formatCurrency(order.delivery_fee)}</strong></div>
            <div className="order-detail-summary-row"><span>Tax</span><strong>{formatCurrency(order.tax_amount)}</strong></div>
            {Number(order.discount_amount) > 0 ? (
              <div className="order-detail-summary-row"><span>Discount</span><strong>-{formatCurrency(order.discount_amount)}</strong></div>
            ) : null}
            <div className="order-detail-summary-row order-detail-summary-row--total">
              <span>Total</span>
              <strong>{formatCurrency(order.total_amount)}</strong>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
