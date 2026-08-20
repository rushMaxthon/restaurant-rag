import {
  ArrowLeft,
  ArrowRight,
  Banknote,
  CalendarClock,
  Check,
  ChefHat,
  ChevronDown,
  ClipboardList,
  Copy,
  CreditCard,
  History,
  Mail,
  MapPin,
  PackageCheck,
  Phone,
  ReceiptText,
  ShoppingBag,
  Store,
  StickyNote,
  Truck,
  User,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { EmptyPanel } from "../components/EmptyPanel";
import { StatusPill } from "../components/StatusPill";
import {
  ApiError,
  api,
  formatCurrency,
  formatDate,
  toNumber,
} from "../services/api";
import { humanizeEnum } from "../services/format";
import {
  ORDER_FULFILLMENT_STATUSES,
  type Order,
  type OrderItem,
  type OrderStatus,
  type UserRole,
} from "../types/app";

interface OrderDetailPageProps {
  token: string;
  role: UserRole;
  orderId: string;
  onNavigate: (path: string) => void;
  onToast: (
    title: string,
    description: string,
    tone?: "success" | "error" | "info",
  ) => void;
}

const STATUS_FLOW: OrderStatus[] = ORDER_FULFILLMENT_STATUSES;

// PAYMENT_PENDING and CANCELLED are absent by design — neither can be advanced,
// and the backend refuses the transition for an order that is not paid.
const nextStatusMap: Partial<Record<OrderStatus, OrderStatus>> = {
  PLACED: "ACCEPTED",
  ACCEPTED: "PREPARING",
  PREPARING: "OUT_FOR_DELIVERY",
  OUT_FOR_DELIVERY: "DELIVERED",
};

const STATUS_STEPS: Array<{
  status: OrderStatus;
  label: string;
  description: string;
  icon: typeof ShoppingBag;
}> = [
  {
    status: "PLACED",
    label: "Placed",
    description: "Order received from the customer",
    icon: ShoppingBag,
  },
  {
    status: "ACCEPTED",
    label: "Accepted",
    description: "Restaurant confirmed the order",
    icon: Check,
  },
  {
    status: "PREPARING",
    label: "Preparing",
    description: "Kitchen is working on the items",
    icon: ChefHat,
  },
  {
    status: "OUT_FOR_DELIVERY",
    label: "Out for delivery",
    description: "Order is on its way",
    icon: Truck,
  },
  {
    status: "DELIVERED",
    label: "Delivered",
    description: "Order completed successfully",
    icon: PackageCheck,
  },
];



function describeItemCustomizations(item: OrderItem): string[] {
  return item.selected_options_snapshot.map((option) => {
    const name = option.option_name ?? "Customization";
    const group = option.group_title ? `${option.group_title}: ` : "";
    const quantity =
      option.quantity && option.quantity > 1 ? ` ×${option.quantity}` : "";
    const extra =
      option.extra_price && toNumber(option.extra_price) > 0
        ? ` (+${formatCurrency(option.extra_price)})`
        : "";
    return `${group}${name}${quantity}${extra}`;
  });
}

export function OrderDetailPage({
  token,
  role,
  orderId,
  onNavigate,
  onToast,
}: OrderDetailPageProps) {
  const isOwner = role === "OWNER";
  const [order, setOrder] = useState<Order | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isUpdating, setIsUpdating] = useState(false);
  const onToastRef = useRef(onToast);

  useEffect(() => {
    onToastRef.current = onToast;
  }, [onToast]);

  // The page is mounted with key={orderId}, so loading state starts fresh
  // for every order and does not need to be reset inside the effect.
  useEffect(() => {
    let active = true;

    api
      .getOrder(token, orderId)
      .then((row) => {
        if (active) {
          setOrder(row);
        }
      })
      .catch((error: unknown) => {
        if (!active) {
          return;
        }
        const message =
          error instanceof ApiError
            ? error.message
            : "Unable to load this order.";
        setLoadError(message);
        onToastRef.current("Order unavailable", message, "error");
      })
      .finally(() => {
        if (active) {
          setIsLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [token, orderId]);

  const currentStepIndex = useMemo(
    () => (order ? STATUS_FLOW.indexOf(order.status) : -1),
    [order],
  );

  const copyOrderId = async () => {
    if (!order) {
      return;
    }
    try {
      await navigator.clipboard.writeText(order.id);
      onToastRef.current(
        "Order ID copied",
        "The full order ID is on your clipboard.",
        "success",
      );
    } catch {
      onToastRef.current(
        "Copy failed",
        "Your browser blocked clipboard access.",
        "error",
      );
    }
  };

  const advanceStatus = async () => {
    if (!order || !isOwner || isUpdating) {
      return;
    }
    const nextStatus = nextStatusMap[order.status];
    if (!nextStatus) {
      return;
    }

    setIsUpdating(true);
    try {
      const updated = await api.updateOrderStatus(token, order.id, nextStatus);
      setOrder(updated);
      onToastRef.current(
        "Order updated",
        `Order moved to ${humanizeEnum(nextStatus)}.`,
        "success",
      );
    } catch (error: unknown) {
      const message =
        error instanceof ApiError ? error.message : "Unable to update order.";
      onToastRef.current("Status update failed", message, "error");
    } finally {
      setIsUpdating(false);
    }
  };

  const backButton = (
    <button
      className="secondary-button order-detail__back"
      onClick={() => onNavigate("/orders")}
      type="button"
    >
      <ArrowLeft size={16} strokeWidth={2.2} />
      Back to orders
    </button>
  );

  if (isLoading) {
    return (
      <div className="page-stack">
        {backButton}
        <section className="admin-surface order-detail__skeleton">
          <span className="table-skeleton table-skeleton--title" />
          <span className="table-skeleton table-skeleton--line" />
          <span className="table-skeleton table-skeleton--line" />
          <span className="table-skeleton table-skeleton--line" />
        </section>
      </div>
    );
  }

  if (loadError || !order) {
    return (
      <div className="page-stack">
        {backButton}
        <section className="admin-surface">
          <EmptyPanel
            description={
              loadError ??
              "This order may not exist or is outside your restaurant scope."
            }
            title="Order not found"
          />
        </section>
      </div>
    );
  }

  // Mirrors the backend rule ("This order has not been paid yet"): money must
  // be committed before the kitchen can be told to start. Without this an owner
  // could tap Advance and only learn it was refused from an error toast.
  const isSettled =
    order.payment_status === "PAID" || order.payment_status === "COD";
  const nextStatus = isSettled ? nextStatusMap[order.status] : undefined;
  const discount = toNumber(order.discount_amount);
  const customizationTotals = order.items.reduce(
    (sum, item) => sum + toNumber(item.customization_total_price) * item.quantity,
    0,
  );
  const totalItemCount = order.items.reduce(
    (sum, item) => sum + item.quantity,
    0,
  );

  return (
    <div className="page-stack order-detail">
      <div className="order-detail__topbar">
        {backButton}
        {isOwner && nextStatus ? (
          <button
            className="primary-button"
            disabled={isUpdating}
            onClick={advanceStatus}
            type="button"
          >
            {isUpdating ? "Updating..." : `Advance to ${humanizeEnum(nextStatus)}`}
            <ArrowRight size={16} strokeWidth={2.2} />
          </button>
        ) : null}
      </div>

      <header className="admin-surface order-detail__hero">
        <div className="order-detail__hero-copy">
          <span className="eyebrow">Operations · Order</span>
          <div className="order-detail__title-row">
            <h1>Order #{order.id.slice(0, 8)}</h1>
            <StatusPill status={order.status} />
          </div>
          <p className="order-detail__hero-meta">
            <span className="order-detail__hero-id" title={order.id}>
              {order.id}
            </span>
            <button
              aria-label="Copy full order ID"
              className="table-icon-button"
              onClick={copyOrderId}
              title="Copy full order ID"
              type="button"
            >
              <Copy size={14} strokeWidth={2.1} />
            </button>
          </p>
          <p className="order-detail__hero-sub">
            Placed {formatDate(order.placed_at)} · {order.restaurant.name} (
            {order.restaurant_location.branch_name})
          </p>
        </div>
        <div className="order-detail__metrics">
          <div className="order-detail__metric">
            <span>Total amount</span>
            <strong>{formatCurrency(order.total_amount)}</strong>
          </div>
          <div className="order-detail__metric">
            <span>Items</span>
            <strong>
              {totalItemCount} {totalItemCount === 1 ? "item" : "items"}
            </strong>
          </div>
          <div className="order-detail__metric">
            <span>Payment</span>
            <strong>{humanizeEnum(order.payment_method)}</strong>
            <StatusPill status={order.payment_status} />
          </div>
          <div className="order-detail__metric">
            <span>Fulfillment</span>
            <strong>{humanizeEnum(order.fulfillment_type)}</strong>
            <em>{humanizeEnum(order.schedule_type)}</em>
          </div>
        </div>
      </header>

      <section className="admin-surface order-detail__card">
        <header className="order-detail__card-header">
          <span className="order-detail__card-icon">
            <History size={17} strokeWidth={2.1} />
          </span>
          <div>
            <h2>Order progress</h2>
            <p>Live status pipeline for this order.</p>
          </div>
        </header>
        {order.status === "PAYMENT_PENDING" || order.status === "CANCELLED" ? (
          // Neither state sits on the fulfillment pipeline: an unpaid order has
          // not entered it, and a cancelled one never will. Rendering the
          // stepper here would show every step as "upcoming", implying the
          // kitchen is about to start.
          <div
            className={`order-detail__status-notice order-detail__status-notice--${
              order.status === "PAYMENT_PENDING" ? "pending" : "cancelled"
            }`}
          >
            <strong>
              {order.status === "PAYMENT_PENDING"
                ? "Waiting for payment"
                : "Order cancelled"}
            </strong>
            <span>
              {order.status === "PAYMENT_PENDING"
                ? "The customer has not completed the card payment yet, so this order is not in the kitchen queue and cannot be advanced."
                : "This order was cancelled and will not be prepared."}
            </span>
          </div>
        ) : (
        <ol className="order-timeline">
          {STATUS_STEPS.map((step, index) => {
            const Icon = step.icon;
            const state =
              index < currentStepIndex
                ? "done"
                : index === currentStepIndex
                  ? "current"
                  : "upcoming";
            return (
              <li className={`order-timeline__step order-timeline__step--${state}`} key={step.status}>
                <span className="order-timeline__marker">
                  {state === "done" ? (
                    <Check size={15} strokeWidth={2.4} />
                  ) : (
                    <Icon size={15} strokeWidth={2.1} />
                  )}
                </span>
                <div className="order-timeline__copy">
                  <strong>{step.label}</strong>
                  <span>{step.description}</span>
                  {step.status === "PLACED" ? (
                    <em>{formatDate(order.placed_at)}</em>
                  ) : state === "current" ? (
                    <em>Last updated {formatDate(order.updated_at)}</em>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ol>
        )}
      </section>

      <div className="order-detail__grid">
        <section className="admin-surface order-detail__card">
          <header className="order-detail__card-header">
            <span className="order-detail__card-icon">
              <User size={17} strokeWidth={2.1} />
            </span>
            <div>
              <h2>Customer</h2>
              <p>Who placed this order.</p>
            </div>
          </header>
          <div className="order-detail__facts">
            <div className="order-detail__fact">
              <span>Name</span>
              <strong>{order.customer.full_name}</strong>
            </div>
            <div className="order-detail__fact">
              <span>Email</span>
              <strong className="order-detail__fact-inline">
                <Mail size={14} strokeWidth={2.1} />
                <a href={`mailto:${order.customer.email}`}>
                  {order.customer.email}
                </a>
              </strong>
            </div>
            <div className="order-detail__fact">
              <span>Phone</span>
              <strong className="order-detail__fact-inline">
                <Phone size={14} strokeWidth={2.1} />
                {order.customer.phone_number ? (
                  <a href={`tel:${order.customer.phone_number}`}>
                    {order.customer.phone_number}
                  </a>
                ) : (
                  "Not provided"
                )}
              </strong>
            </div>
          </div>
        </section>

        <section className="admin-surface order-detail__card">
          <header className="order-detail__card-header">
            <span className="order-detail__card-icon">
              <Store size={17} strokeWidth={2.1} />
            </span>
            <div>
              <h2>Restaurant & branch</h2>
              <p>Where this order is fulfilled from.</p>
            </div>
          </header>
          <div className="order-detail__facts">
            <div className="order-detail__fact">
              <span>Restaurant</span>
              <strong>{order.restaurant.name}</strong>
              <em>{order.restaurant.cuisine_type}</em>
            </div>
            <div className="order-detail__fact">
              <span>Branch</span>
              <strong>{order.restaurant_location.branch_name}</strong>
              <em>
                {order.restaurant_location.address_line_1},{" "}
                {order.restaurant_location.city}
              </em>
            </div>
            <div className="order-detail__fact">
              <span>Branch state</span>
              <strong className="order-detail__pill-row">
                <StatusPill
                  status={order.restaurant_location.is_open ? "OPEN" : "CLOSED"}
                />
                <StatusPill
                  status={
                    order.restaurant_location.is_active ? "ACTIVE" : "INACTIVE"
                  }
                />
              </strong>
            </div>
          </div>
        </section>

        <section className="admin-surface order-detail__card">
          <header className="order-detail__card-header">
            <span className="order-detail__card-icon">
              <Truck size={17} strokeWidth={2.1} />
            </span>
            <div>
              <h2>Fulfillment & delivery</h2>
              <p>How and where the order reaches the customer.</p>
            </div>
          </header>
          <div className="order-detail__facts">
            <div className="order-detail__fact">
              <span>Type & schedule</span>
              <strong>
                {humanizeEnum(order.fulfillment_type)} ·{" "}
                {humanizeEnum(order.schedule_type)}
              </strong>
              <em className="order-detail__fact-inline">
                <CalendarClock size={14} strokeWidth={2.1} />
                {formatDate(order.scheduled_at)}
              </em>
            </div>
            <div className="order-detail__fact">
              <span>
                {order.fulfillment_type === "PICKUP"
                  ? "Pickup handled at branch"
                  : "Delivery address"}
              </span>
              <strong className="order-detail__fact-inline">
                <MapPin size={14} strokeWidth={2.1} />
                {order.delivery_address}
              </strong>
            </div>
            <div className="order-detail__fact">
              <span>Estimated time</span>
              <strong>
                {order.fulfillment_type === "PICKUP"
                  ? `${order.restaurant_location.estimated_pickup_time} min pickup`
                  : `${order.restaurant_location.estimated_delivery_time} min delivery`}
              </strong>
            </div>
          </div>
        </section>

        <section className="admin-surface order-detail__card">
          <header className="order-detail__card-header">
            <span className="order-detail__card-icon">
              <CreditCard size={17} strokeWidth={2.1} />
            </span>
            <div>
              <h2>Payment</h2>
              <p>Method, provider and settlement state.</p>
            </div>
          </header>
          <div className="order-detail__facts">
            <div className="order-detail__fact">
              <span>Method</span>
              <strong className="order-detail__fact-inline">
                <Banknote size={14} strokeWidth={2.1} />
                {humanizeEnum(order.payment_method)}
              </strong>
            </div>
            <div className="order-detail__fact">
              <span>Status</span>
              <strong>
                <StatusPill status={order.payment_status} />
              </strong>
            </div>
            <div className="order-detail__fact">
              <span>Provider</span>
              <strong>{humanizeEnum(order.payment_provider)}</strong>
              <em>
                {order.payment_reference
                  ? `Ref: ${order.payment_reference}`
                  : "No payment reference"}
              </em>
            </div>
          </div>
        </section>
      </div>

      {order.special_instructions ? (
        <section className="admin-surface order-detail__card order-detail__notes">
          <header className="order-detail__card-header">
            <span className="order-detail__card-icon">
              <StickyNote size={17} strokeWidth={2.1} />
            </span>
            <div>
              <h2>Order notes</h2>
              <p>Special instructions from the customer.</p>
            </div>
          </header>
          <blockquote>{order.special_instructions}</blockquote>
        </section>
      ) : null}

      <section className="admin-surface order-detail__card">
        <header className="order-detail__card-header">
          <span className="order-detail__card-icon">
            <ClipboardList size={17} strokeWidth={2.1} />
          </span>
          <div>
            <h2>Ordered items</h2>
            <p>
              {order.items.length} line {order.items.length === 1 ? "item" : "items"},{" "}
              {totalItemCount} {totalItemCount === 1 ? "unit" : "units"} in total.
            </p>
          </div>
        </header>
        <div className="table-scroll">
          <table className="admin-table order-detail__items-table">
            <thead>
              <tr>
                <th>Item</th>
                <th className="admin-table__cell--right">Qty</th>
                <th className="admin-table__cell--right">Unit price</th>
                <th className="admin-table__cell--right">Line total</th>
              </tr>
            </thead>
            <tbody>
              {order.items.map((item) => {
                const customizations = describeItemCustomizations(item);
                return (
                  <tr key={item.id}>
                    <td>
                      <div className="order-detail__item-name">
                        <strong>{item.item_name_snapshot}</strong>
                        {item.size_name_snapshot ? (
                          <span className="order-detail__item-size">
                            Size: {item.size_name_snapshot}
                          </span>
                        ) : null}
                        {customizations.length > 0 ? (
                          <ul className="order-detail__item-options">
                            {customizations.map((entry, index) => (
                              <li key={`${item.id}-option-${index}`}>{entry}</li>
                            ))}
                          </ul>
                        ) : null}
                      </div>
                    </td>
                    <td className="admin-table__cell--right">{item.quantity}</td>
                    <td className="admin-table__cell--right">
                      {formatCurrency(item.unit_price)}
                      {toNumber(item.customization_total_price) > 0 ? (
                        <span className="order-detail__item-subprice">
                          incl. {formatCurrency(item.customization_total_price)}{" "}
                          add-ons
                        </span>
                      ) : null}
                    </td>
                    <td className="admin-table__cell--right">
                      <strong>{formatCurrency(item.total_price)}</strong>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="order-detail__totals">
          <div className="order-detail__totals-row">
            <span>Subtotal</span>
            <strong>{formatCurrency(order.subtotal)}</strong>
          </div>
          {customizationTotals > 0 ? (
            <div className="order-detail__totals-row order-detail__totals-row--muted">
              <span>Includes customizations</span>
              <strong>{formatCurrency(customizationTotals)}</strong>
            </div>
          ) : null}
          <div className="order-detail__totals-row">
            <span>Delivery fee</span>
            <strong>{formatCurrency(order.delivery_fee)}</strong>
          </div>
          <div className="order-detail__totals-row">
            <span>Taxes</span>
            <strong>{formatCurrency(order.tax_amount)}</strong>
          </div>
          {discount > 0 ? (
            <div className="order-detail__totals-row order-detail__totals-row--discount">
              <span>Discount</span>
              <strong>-{formatCurrency(order.discount_amount)}</strong>
            </div>
          ) : null}
          <div className="order-detail__totals-row order-detail__totals-row--grand">
            <span>
              <ReceiptText size={15} strokeWidth={2.1} /> Total ({order.currency})
            </span>
            <strong>{formatCurrency(order.total_amount)}</strong>
          </div>
        </div>
      </section>

      <details className="admin-surface order-detail__collapsible">
        <summary>
          <span className="order-detail__card-icon">
            <History size={17} strokeWidth={2.1} />
          </span>
          <div>
            <h2>Status history & timestamps</h2>
            <p>Recorded lifecycle timestamps for this order.</p>
          </div>
          <ChevronDown
            className="order-detail__chevron"
            size={18}
            strokeWidth={2.1}
          />
        </summary>
        <div className="order-detail__collapsible-body">
          <div className="detail-grid">
            <div>
              <strong>Placed at</strong>
              <span>{formatDate(order.placed_at)}</span>
            </div>
            <div>
              <strong>Scheduled for</strong>
              <span>{formatDate(order.scheduled_at)}</span>
            </div>
            <div>
              <strong>Created at</strong>
              <span>{formatDate(order.created_at)}</span>
            </div>
            <div>
              <strong>Last updated</strong>
              <span>{formatDate(order.updated_at)}</span>
            </div>
          </div>
          <p className="hint-text">
            The current status is {humanizeEnum(order.status)}. Per-step
            timestamps are not stored yet, so the last update reflects the most
            recent status change.
          </p>
        </div>
      </details>

      <details className="admin-surface order-detail__collapsible">
        <summary>
          <span className="order-detail__card-icon">
            <ClipboardList size={17} strokeWidth={2.1} />
          </span>
          <div>
            <h2>Record metadata</h2>
            <p>Identifiers useful for support and debugging.</p>
          </div>
          <ChevronDown
            className="order-detail__chevron"
            size={18}
            strokeWidth={2.1}
          />
        </summary>
        <div className="order-detail__collapsible-body">
          <div className="detail-grid">
            <div>
              <strong>Order ID</strong>
              <span className="order-detail__mono">{order.id}</span>
            </div>
            <div>
              <strong>Customer ID</strong>
              <span className="order-detail__mono">{order.customer_id}</span>
            </div>
            <div>
              <strong>Restaurant ID</strong>
              <span className="order-detail__mono">{order.restaurant_id}</span>
            </div>
            <div>
              <strong>Branch ID</strong>
              <span className="order-detail__mono">
                {order.restaurant_location_id}
              </span>
            </div>
            <div>
              <strong>Currency</strong>
              <span>{order.currency}</span>
            </div>
            <div>
              <strong>Payment provider</strong>
              <span>
                {humanizeEnum(order.payment_provider)}
                {order.payment_reference
                  ? ` · ${order.payment_reference}`
                  : ""}
              </span>
            </div>
          </div>
        </div>
      </details>
    </div>
  );
}
