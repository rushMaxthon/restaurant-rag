import {
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
import { useOrdersChanged } from "../hooks/useRealtime";
import { useEffect, useMemo, useRef, useState } from "react";
import { Breadcrumbs } from "../components/Breadcrumbs";
import { DeliveryPanel } from "../components/DeliveryPanel";
import { EmptyPanel } from "../components/EmptyPanel";
import { ErrorPanel } from "../components/ErrorPanel";
import { StatusPill } from "../components/StatusPill";
import {
  ApiError,
  api,
  formatDate,
  toNumber,
} from "../services/api";
import { humanizeEnum } from "../services/format";
import { buildOrdersCacheKeyPrefix } from "./OrdersPage";
import { useMoney } from '../hooks/useMoney';
import { CancelOrderDialog } from '../components/CancelOrderDialog';
import { cancellationSummary, refundLine } from '../services/orderCancellation';
import {
  getPageSnapshot,
  hasPageSnapshot,
  invalidatePageSnapshotsByPrefix,
  setPageSnapshot,
  tokenScope,
} from "../services/pageCache";
import {
  ORDER_FULFILLMENT_STATUSES,
  type Order,
  type OrderItem,
  type OrderStatus,
  type UserRole,
} from "../types/app";
import { PageHelpTip } from "../components/PageHelpTip";

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



/**
 * What to say about an order, and what the next button does.
 *
 * Written in the words a kitchen uses rather than the enum's. "Advance to
 * Out for delivery" is a state machine talking to itself; "Hand it to the
 * rider" is an instruction somebody can follow.
 *
 * `delivery` differs where the step differs: a pickup order is handed over a
 * counter and never sees a courier, so telling that restaurant a rider is on
 * the way would be a lie.
 */
function nextStepFor(
  status: OrderStatus,
  isDelivery: boolean,
): { eyebrow: string; heading: string; detail: string; action: string } | null {
  switch (status) {
    case "PLACED":
      return {
        eyebrow: "Needs you",
        heading: "New order waiting to be accepted",
        detail: isDelivery
          ? "Accepting confirms it to the customer and books a rider automatically."
          : "Accepting confirms it to the customer and sends it to the kitchen.",
        action: "Accept order",
      };
    case "ACCEPTED":
      return {
        eyebrow: "Accepted",
        heading: "Ready for the kitchen",
        detail: "Mark it as preparing once somebody starts cooking.",
        action: "Start preparing",
      };
    case "PREPARING":
      return {
        eyebrow: "In the kitchen",
        heading: "Being prepared",
        detail: isDelivery
          ? "Mark it out for delivery once the rider has the food."
          : "Mark it ready once the customer can collect it.",
        action: isDelivery ? "Hand to the rider" : "Ready for collection",
      };
    case "OUT_FOR_DELIVERY":
      return {
        eyebrow: isDelivery ? "On the way" : "Ready",
        heading: isDelivery ? "Out for delivery" : "Waiting to be collected",
        detail: "Mark it delivered once the customer has the food.",
        action: "Mark delivered",
      };
    case "PAYMENT_PENDING":
      return {
        eyebrow: "Waiting",
        heading: "Not paid yet",
        detail:
          "This order stays out of the kitchen until the payment is confirmed. Nothing to do here.",
        action: "",
      };
    default:
      // DELIVERED and CANCELLED are over. A card saying so would be one more
      // thing to read on a page about an order nobody has to act on.
      return null;
  }
}

// `money` is passed in rather than imported, for the same reason as above:
// the currency belongs to the order's restaurant, not to this module.
function describeItemCustomizations(
  item: OrderItem,
  money: (value: number | string) => string,
): string[] {
  return item.selected_options_snapshot.map((option) => {
    const name = option.option_name ?? "Customization";
    const group = option.group_title ? `${option.group_title}: ` : "";
    const quantity =
      option.quantity && option.quantity > 1 ? ` ×${option.quantity}` : "";
    const extra =
      option.extra_price && toNumber(option.extra_price) > 0
        ? ` (+${money(option.extra_price)})`
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
  // Figures in whatever the restaurant in scope charges in.
  const money = useMoney();
  // An admin is platform staff supporting a tenant, and the backend now lets
  // them move an order along too. Before this the page offered them no action
  // whatsoever, which reads as a broken screen rather than a permission.
  const canAdvance = role === "OWNER" || role === "ADMIN";
  const scope = tokenScope(token);
  const orderKey = `order-detail:${scope}:${orderId}`;
  const [order, setOrder] = useState<Order | null>(
    () => getPageSnapshot<Order>(orderKey) ?? null,
  );
  // Only true when this order has never been fetched this session - not on
  // every mount, so revisiting it keeps showing its data instead of a
  // skeleton. The page is remounted with key={orderId} (see the mount effect
  // below), so a different order never inherits this one's cached state.
  const [isLoading, setIsLoading] = useState(() => !hasPageSnapshot(orderKey));
  const [loadError, setLoadError] = useState<string | null>(null);
  // Bumped by the error panel's Try again, which re-runs the fetch effect.
  const [reloadNonce, setReloadNonce] = useState(0);
  const [showCancel, setShowCancel] = useState(false);
  const [isRetryingRefund, setIsRetryingRefund] = useState(false);
  const [isUpdating, setIsUpdating] = useState(false);
  const onToastRef = useRef(onToast);

  useEffect(() => {
    onToastRef.current = onToast;
  }, [onToast]);

  // This order moved (or the socket reconnected and anything may have). The
  // realtime layer has already dropped the cached copy, so re-running the
  // fetch asks the server; the page keeps showing the old row until it lands.
  useOrdersChanged((orderIds) => {
    if (orderIds === null || orderIds.includes(orderId)) {
      setReloadNonce((current) => current + 1);
    }
  });

  // The page is mounted with key={orderId}, so loading state starts fresh
  // for every order and does not need to be reset inside the effect.
  useEffect(() => {
    if (hasPageSnapshot(orderKey)) {
      setIsLoading(false);
      return;
    }

    let active = true;

    api
      .getOrder(token, orderId)
      .then((row) => {
        if (active) {
          setOrder(row);
          setLoadError(null);
          setPageSnapshot(orderKey, row);
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
  }, [token, orderId, orderKey, reloadNonce]);

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
    if (!order || !canAdvance || isUpdating) {
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
      setPageSnapshot(orderKey, updated);
      // The global Orders list shows the same order through its own filters.
      invalidatePageSnapshotsByPrefix(buildOrdersCacheKeyPrefix(scope));
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

  // After a cancel or a refund retry: the same bookkeeping as an advance, so
  // the Orders list does not keep showing the order as it was.
  const showUpdated = (updated: Order) => {
    setOrder(updated);
    setPageSnapshot(orderKey, updated);
    invalidatePageSnapshotsByPrefix(buildOrdersCacheKeyPrefix(scope));
  };

  const retryRefund = async () => {
    if (!order || isRetryingRefund) return;
    setIsRetryingRefund(true);
    try {
      showUpdated(await api.retryOrderRefund(token, order.id));
      onToastRef.current("Refund queued", "The refund is being tried again.", "success");
    } catch (error: unknown) {
      onToastRef.current(
        "Could not retry the refund",
        error instanceof ApiError ? error.message : "Please try again.",
        "error",
      );
    } finally {
      setIsRetryingRefund(false);
    }
  };

  // The other three detail screens use breadcrumbs; this one had a bespoke
  // back button. Same navigation, one pattern.
  const backButton = (
    <Breadcrumbs
      items={[
        { label: "Orders", path: "/orders" },
        { label: order ? `#${order.id.slice(0, 8)}` : "Order" },
      ]}
      onNavigate={onNavigate}
    />
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
          {loadError ? (
            <ErrorPanel
              description={loadError}
              onRetry={() => {
                setLoadError(null);
                setReloadNonce((current) => current + 1);
              }}
              title="This order didn't load"
            />
          ) : (
            <EmptyPanel
              description="This order may not exist or is outside your restaurant scope."
              title="Order not found"
            />
          )}
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
  // The checkout number first, the account's only as a fallback. See the note
  // on the Phone row below for why the order of those two matters.
  const contactPhone = order.contact_phone?.trim() || order.customer.phone_number;
  const contactName = order.contact_name?.trim() || order.customer.full_name;

  const nextStep = nextStepFor(order.status, order.fulfillment_type === "DELIVERY");
  const refund = refundLine(order);
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
      <div className="order-detail__topbar">{backButton}</div>
      {showCancel ? (
        <CancelOrderDialog
          amount={money.format(order.total_amount, order.restaurant_id)}
          onCancelled={(updated) => {
            setShowCancel(false);
            showUpdated(updated);
          }}
          onClose={() => setShowCancel(false)}
          onToast={onToast}
          order={order}
          token={token}
        />
      ) : null}

      <header className="admin-surface order-detail__hero">
        <div className="order-detail__hero-copy">
          <span className="eyebrow">Operations · Order</span>
          <div className="order-detail__title-row">
            <h1>Order #{order.id.slice(0, 8)}</h1>
            <StatusPill status={order.status} />
            <PageHelpTip page="order-detail" />
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
            <strong>{money.format(order.total_amount, order.restaurant_id)}</strong>
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

      {/*
        * The one thing somebody opens this page to DO.
        *
        * It used to be a small button in the top bar beside the back link,
        * shown only to an owner. A restaurant looking at a new order saw a
        * status pipeline that looks clickable and is not, and no way to accept
        * anything — reported as "the restaurant has no option to accept the
        * order", which is exactly right.
        *
        * So the next step is a card of its own, above everything else, saying
        * in plain words what state the order is in and what pressing the button
        * will do.
        */}
      {nextStep ? (
        <section className="admin-surface order-detail__next">
          <div className="order-detail__next-copy">
            <p className="order-detail__next-eyebrow">{nextStep.eyebrow}</p>
            <h2>{nextStep.heading}</h2>
            <p className="order-detail__next-detail">{nextStep.detail}</p>
          </div>
          {canAdvance && order.can_be_cancelled ? (
            <button
              className="secondary-button"
              onClick={() => setShowCancel(true)}
              title="Cancel this order. A prepaid order is refunded in full and a booked rider is called off."
              type="button"
            >
              Cancel order
            </button>
          ) : null}
          {canAdvance && nextStatus ? (
            <button
              className="primary-button order-detail__next-action"
              disabled={isUpdating}
              onClick={advanceStatus}
              type="button"
            >
              {isUpdating ? "Working…" : nextStep.action}
              <ArrowRight size={17} strokeWidth={2.2} />
            </button>
          ) : null}
        </section>
      ) : null}

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
                : cancellationSummary(order)}
            </span>
            {order.status === "CANCELLED" && refund ? (
              <span className={`order-detail__refund order-detail__refund--${refund.tone}`}>
                {refund.text}
                {refund.tone === "failed" && canAdvance ? (
                  <button
                    className="secondary-button"
                    disabled={isRetryingRefund}
                    onClick={() => void retryRefund()}
                    type="button"
                  >
                    {isRetryingRefund ? "Trying again…" : "Try the refund again"}
                  </button>
                ) : null}
              </span>
            ) : null}
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
                const customizations = describeItemCustomizations(item, money.format);
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
                      {money.format(item.unit_price, order.restaurant_id)}
                      {toNumber(item.customization_total_price) > 0 ? (
                        <span className="order-detail__item-subprice">
                          incl. {money.format(item.customization_total_price, order.restaurant_id)}{" "}
                          add-ons
                        </span>
                      ) : null}
                    </td>
                    <td className="admin-table__cell--right">
                      <strong>{money.format(item.total_price, order.restaurant_id)}</strong>
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
            <strong>{money.format(order.subtotal, order.restaurant_id)}</strong>
          </div>
          {customizationTotals > 0 ? (
            <div className="order-detail__totals-row order-detail__totals-row--muted">
              <span>Includes customizations</span>
              <strong>{money.format(customizationTotals, order.restaurant_id)}</strong>
            </div>
          ) : null}
          <div className="order-detail__totals-row">
            <span>Delivery fee</span>
            <strong>{money.format(order.delivery_fee, order.restaurant_id)}</strong>
          </div>
          <div className="order-detail__totals-row">
            <span>Taxes and charges</span>
            <strong>{money.format(order.tax_amount, order.restaurant_id)}</strong>
          </div>
          {/* Opened, not hidden behind a click.
              The customer gets this as a modal because they are reading one
              bill once; a restaurant is reconciling a day of them, and the
              three parts go to three different places — their own packaging
              charge, the platform's fee, and the government's GST. A single
              figure is the one thing that cannot be reconciled. */}
          {order.charges?.lines.map((line) => (
            <div
              className="order-detail__totals-row order-detail__totals-row--muted"
              key={line.key}
            >
              <span>{line.label}</span>
              <strong>{money.format(line.amount, order.restaurant_id)}</strong>
            </div>
          ))}
          {discount > 0 ? (
            <div className="order-detail__totals-row order-detail__totals-row--discount">
              <span>Discount</span>
              <strong>-{money.format(order.discount_amount, order.restaurant_id)}</strong>
            </div>
          ) : null}
          <div className="order-detail__totals-row order-detail__totals-row--grand">
            <span>
              <ReceiptText size={15} strokeWidth={2.1} /> Total ({order.currency})
            </span>
            <strong>{money.format(order.total_amount, order.restaurant_id)}</strong>
          </div>
        </div>
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
              <strong>{contactName}</strong>
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
            {/* The number given FOR THIS ORDER first, and the account's only
                as a fallback.

                It read `customer.phone_number` alone, which is whatever is on
                the account and is routinely null — a customer can order
                without ever setting one. So a delivery with a perfectly good
                checkout number showed "Not provided" to the restaurant, while
                the courier had been sent that very number and a rider was
                about to ring it. */}
            <div className="order-detail__fact">
              <span>Phone</span>
              <strong className="order-detail__fact-inline">
                <Phone size={14} strokeWidth={2.1} />
                {contactPhone ? (
                  <a href={`tel:${contactPhone}`}>{contactPhone}</a>
                ) : (
                  "Not provided"
                )}
              </strong>
            </div>
          </div>
        </section>

        {/* Says what will happen for a delivery order with no rider yet, and
            renders nothing at all for a pickup one. */}
        <DeliveryPanel
          awaiting={order.fulfillment_type === "DELIVERY"}
          isAdmin={role === "ADMIN"}
          onToast={onToast}
          orderId={orderId}
          token={token}
        />

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
