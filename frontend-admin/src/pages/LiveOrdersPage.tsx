import {
  Bike,
  CalendarClock,
  ChefHat,
  CircleCheckBig,
  Clock,
  ExternalLink,
  Inbox,
  type LucideIcon,
  Phone,
  RefreshCw,
  Search,
  ShoppingBag,
  Store,
  Truck,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { HelpRows, InfoTip } from "../components/InfoTip";
import { PageIntro } from "../components/PageIntro";
import { useMoney } from "../hooks/useMoney";
import { useOrdersChanged } from "../hooks/useRealtime";
import { ApiError, api } from "../services/api";
import { humanizeEnum, pluralize } from "../services/format";
import {
  CARD_HELP,
  type LiveColumn,
  type LiveColumnKey,
  type LiveFilter,
  NO_FILTER,
  STATIC_HELP,
  buildColumns,
  columnHelp,
  deliveryLine,
  formatDuration,
  isFiltering,
  itemsSummary,
  orderClock,
  restaurantBreakdown,
  startOfToday,
  summarise,
} from "../services/liveOrders";
import type { LiveOrder, LiveOrdersBoard, UserRole } from "../types/app";

interface LiveOrdersPageProps {
  token: string;
  role: UserRole;
  onNavigate: (path: string) => void;
  onToast: (
    title: string,
    description: string,
    tone?: "success" | "error" | "info",
  ) => void;
}

/**
 * How often the board asks again with nobody pushing it. A realtime push
 * refetches at once; this is the safety net for a socket that is off or has
 * dropped, and it also moves the clocks on the cards.
 */
const REFRESH_MS = 30_000;

const COLUMN_ICONS: Record<LiveColumnKey, LucideIcon> = {
  new: ShoppingBag,
  kitchen: ChefHat,
  road: Truck,
  done: CircleCheckBig,
};

function paymentTag(order: LiveOrder): { label: string; paid: boolean; help: string } {
  if (order.payment_status === "PAID") {
    return { label: "Paid", paid: true, help: "The customer has already paid online." };
  }
  if (order.payment_method === "COD") {
    return {
      label: "Cash on delivery",
      paid: false,
      help: "Not paid yet. The customer pays in cash when the order arrives.",
    };
  }
  return {
    label: humanizeEnum(order.payment_status),
    paid: false,
    help: "The payment for this order is not complete. Open the order to see its payment status.",
  };
}

function slotLabel(order: LiveOrder): string {
  return new Date(order.scheduled_at).toLocaleString(undefined, {
    weekday: "short",
    hour: "numeric",
    minute: "2-digit",
  });
}

interface LiveCardProps {
  order: LiveOrder;
  column: LiveColumn;
  now: Date;
  showRestaurant: boolean;
  amount: string;
  /** In the backlog section, where "late" has stopped meaning anything. */
  stale?: boolean;
  onOpen: (order: LiveOrder) => void;
}

function LiveCard({ order, column, now, showRestaurant, amount, stale, onOpen }: LiveCardProps) {
  const clock = orderClock(order, column, now);
  const delivery = deliveryLine(order);
  const payment = paymentTag(order);
  const customer = order.contact_name || order.customer.full_name;
  const shortId = order.id.slice(0, 8);
  const late = clock.late && !stale;
  const isDelivery = order.fulfillment_type === "DELIVERY";

  return (
    <article
      className={`live-card${late ? " live-card--late" : ""}${stale ? " live-card--stale" : ""}`}
    >
      {/* The card opens the order. The rider's phone and the tracking link sit
          outside this button, in the strip below, so each is its own target. */}
      <button
        aria-label={`Open order ${shortId} for ${customer}`}
        className="live-card__open"
        onClick={() => onOpen(order)}
        title="Open this order to see the full bill, its history and the delivery details"
        type="button"
      >
        <span className="live-card__top">
          <strong className="live-card__id">#{shortId}</strong>
          <span
            className={`live-card__clock${late ? " live-card__clock--late" : ""}`}
            title={clock.help}
          >
            <Clock aria-hidden="true" size={13} />
            {late ? `${clock.label} · late` : clock.label}
          </span>
        </span>
        {showRestaurant ? (
          <span className="live-card__restaurant" title="The restaurant and branch this order belongs to">
            <Store aria-hidden="true" size={13} />
            <span>
              {order.restaurant.name}
              <em> · {order.restaurant_location.branch_name}</em>
            </span>
          </span>
        ) : null}
        <span className="live-card__who">
          <span title="The customer who placed the order">{customer}</span>
          <strong title="What the customer pays in total, with fees and tax">{amount}</strong>
        </span>
        <span className="live-card__items">{itemsSummary(order)}</span>
        <span className="live-card__tags">
          <span
            className="live-tag"
            title={
              isDelivery
                ? "Delivery: a rider takes this order to the customer."
                : "Pickup: the customer collects this order at the restaurant."
            }
          >
            {isDelivery ? "Delivery" : "Pickup"}
          </span>
          <span
            className={`live-tag${payment.paid ? " live-tag--paid" : " live-tag--due"}`}
            title={payment.help}
          >
            {payment.label}
          </span>
          {column.key === "kitchen" ? (
            <span
              className="live-tag live-tag--stage"
              title={
                order.status === "ACCEPTED"
                  ? "Accepted: the kitchen has confirmed the order but not started it."
                  : "Preparing: the kitchen is cooking or packing the order."
              }
            >
              {humanizeEnum(order.status)}
            </span>
          ) : null}
          {order.schedule_type === "SCHEDULED" ? (
            <span
              className="live-tag live-tag--slot"
              title="The customer booked this order for this time slot, not for right away."
            >
              <CalendarClock aria-hidden="true" size={12} />
              {slotLabel(order)}
            </span>
          ) : null}
        </span>
      </button>
      <div
        className={`live-card__delivery live-card__delivery--${delivery.tone}`}
        title={delivery.help}
      >
        {isDelivery ? (
          <Bike aria-hidden="true" className="live-card__delivery-icon" size={15} />
        ) : (
          <ShoppingBag aria-hidden="true" className="live-card__delivery-icon" size={15} />
        )}
        <span className="live-card__delivery-text">
          <strong>{delivery.label}</strong>
          {delivery.riderName ? <span>Rider: {delivery.riderName}</span> : null}
        </span>
        {delivery.riderPhone ? (
          <a
            aria-label={`Call the rider${delivery.riderName ? `, ${delivery.riderName}` : ""}`}
            className="live-card__call"
            href={`tel:${delivery.riderPhone}`}
            title={`Call the rider on ${delivery.riderPhone}`}
          >
            <Phone aria-hidden="true" size={14} />
          </a>
        ) : null}
        {delivery.trackingUrl ? (
          <a
            className="live-card__track"
            href={delivery.trackingUrl}
            rel="noopener noreferrer"
            target="_blank"
            title="Open the delivery partner's live tracking page in a new tab"
          >
            Track
            <ExternalLink aria-hidden="true" size={12} />
          </a>
        ) : null}
      </div>
    </article>
  );
}

export function LiveOrdersPage({ token, role, onNavigate, onToast }: LiveOrdersPageProps) {
  const money = useMoney();
  const isAdmin = role === "ADMIN";
  const [board, setBoard] = useState<LiveOrdersBoard | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [filter, setFilter] = useState<LiveFilter>(NO_FILTER);
  // The restaurant an admin picked. Sent to the server rather than filtered
  // here: a column carries its newest hundred cards, so on a busy platform
  // a quieter restaurant's orders are not in the list to be filtered.
  const [restaurantId, setRestaurantId] = useState<string | null>(null);
  // Which column a phone shows. On a wide screen all four are visible and
  // this only decides which stat tile is highlighted.
  const [activeColumn, setActiveColumn] = useState<LiveColumnKey>("new");
  const [now, setNow] = useState(() => new Date());
  const onToastRef = useRef(onToast);
  const hasBoard = useRef(false);

  useEffect(() => {
    onToastRef.current = onToast;
  }, [onToast]);

  const load = useCallback(
    async (mode: "first" | "silent" | "manual") => {
      if (mode === "manual") {
        setIsRefreshing(true);
      }
      try {
        const next = await api.getLiveOrders(token, {
          completedFrom: startOfToday(new Date()),
          restaurantId,
        });
        setBoard(next);
        hasBoard.current = true;
        setLoadError(null);
        setNow(new Date());
      } catch (error: unknown) {
        const message =
          error instanceof ApiError ? error.message : "Unable to load live orders.";
        // A refresh that fails while a board is on screen keeps the board: a
        // stale list beats a blank one mid-service. The banner says it is stale.
        setLoadError(message);
        if (mode !== "silent" || !hasBoard.current) {
          onToastRef.current("Live orders unavailable", message, "error");
        }
      } finally {
        setIsLoading(false);
        setIsRefreshing(false);
      }
    },
    [token, restaurantId],
  );

  useEffect(() => {
    // Also runs when the picked restaurant changes, with the board already
    // on screen: the Refresh spinner turns rather than the cards blanking.
    void load(hasBoard.current ? "manual" : "first");
    const handle = window.setInterval(() => void load("silent"), REFRESH_MS);
    return () => window.clearInterval(handle);
  }, [load]);

  // An order moved somewhere in this account's scope. The push carries no
  // data, so the board asks the server — the only source of rows.
  useOrdersChanged(() => {
    void load("silent");
  });

  const columns = useMemo(() => buildColumns(board, filter, now), [board, filter, now]);
  const summary = useMemo(() => summarise(columns), [columns]);
  const restaurants = useMemo(() => restaurantBreakdown(board), [board]);
  const filtering = isFiltering(filter);
  const clearAll = () => {
    setFilter(NO_FILTER);
    setRestaurantId(null);
  };
  const nothingAtAll = columns.every(
    (column) => column.orders.length === 0 && column.staleTotal === 0,
  );
  const updatedLabel = board
    ? formatDuration((now.getTime() - new Date(board.generated_at).getTime()) / 60000)
    : null;
  const staleDays = Math.max(1, Math.round((board?.stale_after_minutes ?? 1440) / 1440));
  const staleWords = staleDays === 1 ? "a day" : `${staleDays} days`;

  const openOrder = (order: LiveOrder) => onNavigate(`/orders/${order.id}`);

  const emptyCopy = (column: LiveColumn): { title: string; text: string } => {
    if (filtering) {
      return { title: "Nothing matches", text: "No order here matches the current filters." };
    }
    switch (column.key) {
      case "new":
        return { title: "All clear", text: "No orders are waiting to be accepted." };
      case "kitchen":
        return { title: "All clear", text: "Nothing is being prepared right now." };
      case "road":
        return { title: "All clear", text: "No orders are out for delivery." };
      default:
        return {
          title: "Nothing finished yet",
          text: "Finished orders will appear here through the day.",
        };
    }
  };

  return (
    <div className="page-stack live-page">
      <PageIntro
        actions={
          <div className="live-status">
            <span
              className={`live-status__dot${loadError ? " live-status__dot--stale" : ""}`}
              title={
                loadError
                  ? "The last refresh failed, so this list may be out of date."
                  : "This board refreshes by itself whenever an order changes, and every 30 seconds."
              }
            />
            <span className="live-status__text">
              {loadError
                ? "Not updating"
                : updatedLabel === null
                  ? "Loading"
                  : updatedLabel === "just now"
                    ? "Updated just now"
                    : `Updated ${updatedLabel} ago`}
            </span>
            <button
              className="secondary-button live-status__refresh"
              disabled={isRefreshing}
              onClick={() => void load("manual")}
              title="Load the latest orders now. The board also refreshes by itself."
              type="button"
            >
              <RefreshCw
                aria-hidden="true"
                className={isRefreshing ? "live-spin" : undefined}
                size={15}
              />
              Refresh
            </button>
          </div>
        }
        description={
          isAdmin
            ? "Every order in progress across all restaurants. Read it left to right: new, cooking, on the way, done."
            : "Every order in progress at your restaurant. Read it left to right: new, cooking, on the way, done."
        }
        eyebrow="Operations"
        title="Live orders"
      />

      {loadError && board ? (
        <div className="live-banner" role="status">
          <strong>Showing the last list we loaded.</strong> {loadError}
          <button className="live-banner__retry" onClick={() => void load("manual")} type="button">
            Try again
          </button>
        </div>
      ) : null}

      <section aria-label="Today at a glance" className="live-stats">
        {columns.map((column) => {
          const Icon = COLUMN_ICONS[column.key];
          const help = columnHelp(column.key, role);
          return (
            <div
              className={`live-stat live-stat--${column.key}${
                activeColumn === column.key ? " live-stat--active" : ""
              }`}
              key={column.key}
            >
              <button
                aria-pressed={activeColumn === column.key}
                className="live-stat__main"
                onClick={() => setActiveColumn(column.key)}
                type="button"
              >
                <span className="live-stat__icon">
                  <Icon aria-hidden="true" size={18} />
                </span>
                <span className="live-stat__body">
                  <span className="live-stat__label">{column.title}</span>
                  <strong className="live-stat__value">{isLoading ? "…" : column.total}</strong>
                  <span className="live-stat__hint">{column.hint}</span>
                </span>
              </button>
              <InfoTip label={column.title}>
                <HelpRows title={column.title} {...help} />
              </InfoTip>
            </div>
          );
        })}
        <div className="live-progress">
          <div className="live-progress__head">
            <span className="live-progress__label">
              <span className="live-stat__label">Still to finish</span>
              <InfoTip label="Still to finish">
                <HelpRows title="Still to finish" {...STATIC_HELP.progress} />
              </InfoTip>
            </span>
            <strong className="live-stat__value">{isLoading ? "…" : summary.open}</strong>
          </div>
          <div
            aria-label={`${summary.progress}% of today's orders are done`}
            aria-valuemax={100}
            aria-valuemin={0}
            aria-valuenow={summary.progress}
            className="live-progress__track"
            role="progressbar"
          >
            <span className="live-progress__fill" style={{ width: `${summary.progress}%` }} />
          </div>
          <span className="live-stat__hint">
            {summary.open + summary.done === 0
              ? "No orders yet today"
              : `${summary.done} of ${summary.open + summary.done} done today · ${summary.progress}%`}
            {summary.stale > 0
              ? ` · ${summary.stale} older than ${staleWords} listed separately`
              : ""}
          </span>
        </div>
      </section>

      {isAdmin && restaurants.length > 0 ? (
        <section aria-label="Orders by restaurant" className="live-restaurants">
          <div className="live-section-head">
            <h2>By restaurant</h2>
            <InfoTip label="the restaurant list">
              <HelpRows title="By restaurant" {...STATIC_HELP.restaurants} />
            </InfoTip>
          </div>
          <div className="live-restaurants__row">
            <button
              aria-pressed={restaurantId === null}
              className={`live-rest${restaurantId === null ? " live-rest--active" : ""}`}
              onClick={() => setRestaurantId(null)}
              title="Show the orders of every restaurant"
              type="button"
            >
              <strong>All restaurants</strong>
              <span>{pluralize(restaurants.length, "restaurant")} with orders</span>
            </button>
            {restaurants.map((entry) => (
              <button
                aria-pressed={restaurantId === entry.restaurantId}
                className={`live-rest${
                  restaurantId === entry.restaurantId ? " live-rest--active" : ""
                }`}
                key={entry.restaurantId}
                onClick={() =>
                  setRestaurantId((current) =>
                    current === entry.restaurantId ? null : entry.restaurantId,
                  )
                }
                title={`Show only ${entry.name}'s orders`}
                type="button"
              >
                <strong>{entry.name}</strong>
                {/* Only what there is. Four pills on every chip, most of them
                    zero, is a row of noise to read past. */}
                <span className="live-rest__counts">
                  {entry.new > 0 ? (
                    <span className="live-rest__count live-rest__count--new">{entry.new} new</span>
                  ) : null}
                  {entry.kitchen > 0 ? (
                    <span className="live-rest__count live-rest__count--kitchen">
                      {entry.kitchen} cooking
                    </span>
                  ) : null}
                  {entry.road > 0 ? (
                    <span className="live-rest__count live-rest__count--road">
                      {entry.road} on the way
                    </span>
                  ) : null}
                  {entry.done > 0 ? (
                    <span className="live-rest__count live-rest__count--done">
                      {entry.done} done
                    </span>
                  ) : null}
                  {entry.stale > 0 ? (
                    <span className="live-rest__count live-rest__count--stale">
                      {entry.stale} older
                    </span>
                  ) : null}
                  {entry.open + entry.done + entry.stale === 0 ? (
                    <span className="live-rest__count live-rest__count--stale">Nothing open</span>
                  ) : null}
                </span>
              </button>
            ))}
          </div>
        </section>
      ) : null}

      <section className="live-toolbar">
        <label className="live-search">
          <Search aria-hidden="true" size={16} />
          <span className="visually-hidden">Search live orders</span>
          <input
            onChange={(event) =>
              setFilter((current) => ({ ...current, query: event.target.value }))
            }
            placeholder={
              isAdmin
                ? "Search order, customer, restaurant or rider"
                : "Search order, customer or rider"
            }
            type="search"
            value={filter.query}
          />
        </label>
        <div aria-label="Order type" className="live-segment" role="group">
          {(["ALL", "DELIVERY", "PICKUP"] as const).map((value) => (
            <button
              aria-pressed={filter.fulfillment === value}
              className={`live-segment__item${
                filter.fulfillment === value ? " live-segment__item--active" : ""
              }`}
              key={value}
              onClick={() => setFilter((current) => ({ ...current, fulfillment: value }))}
              title={
                value === "ALL"
                  ? "Show delivery and pickup orders"
                  : value === "DELIVERY"
                    ? "Show only orders a rider delivers"
                    : "Show only orders the customer collects"
              }
              type="button"
            >
              {value === "ALL" ? "All" : value === "DELIVERY" ? "Delivery" : "Pickup"}
            </button>
          ))}
        </div>
        {filtering || restaurantId !== null ? (
          <button className="live-clear" onClick={clearAll} type="button">
            Clear filters
          </button>
        ) : null}
        <span className="live-guide-toggle">
          How to read this board
          <InfoTip label="how to read this board" wide>
            <strong className="tip__title">How to read this board</strong>
            <p className="tip__lead">
              {isAdmin
                ? "For the platform admin: where every restaurant's orders are right now. An order moves left to right as the restaurant works on it. You watch; the restaurant and the rider do the work."
                : "For you and your staff: where each of your orders is right now. An order moves left to right as your kitchen and the rider work on it."}
            </p>
            <dl className="tip__rows">
              {CARD_HELP.map((entry) => (
                <div key={entry.term}>
                  <dt>{entry.term}</dt>
                  <dd>{entry.meaning}</dd>
                </div>
              ))}
            </dl>
          </InfoTip>
        </span>
      </section>

      {loadError && !board && !isLoading ? (
        <div className="live-empty live-empty--page">
          <Inbox aria-hidden="true" size={28} />
          <strong>We couldn&rsquo;t load live orders</strong>
          <p>{loadError}</p>
          <button className="primary-button" onClick={() => void load("manual")} type="button">
            Try again
          </button>
        </div>
      ) : (
        <section className="live-board" data-active={activeColumn}>
          {columns.map((column) => {
            const Icon = COLUMN_ICONS[column.key];
            const empty = emptyCopy(column);
            return (
              <div className={`live-column live-column--${column.key}`} key={column.key}>
                <header className="live-column__head">
                  <span className="live-column__title">
                    <span className="live-column__icon">
                      <Icon aria-hidden="true" size={15} />
                    </span>
                    <h2>{column.title}</h2>
                    <InfoTip label={column.title}>
                      <HelpRows title={column.title} {...columnHelp(column.key, role)} />
                    </InfoTip>
                  </span>
                  <span
                    className="live-column__count"
                    title={`${pluralize(column.total, "order")} in this column`}
                  >
                    {isLoading ? "…" : column.total}
                  </span>
                </header>
                <p className="live-column__hint">{column.hint}</p>
                <div className="live-column__body">
                  {isLoading ? (
                    <>
                      <div className="live-skeleton" />
                      <div className="live-skeleton" />
                    </>
                  ) : column.orders.length === 0 ? (
                    <div className="live-empty">
                      <Icon aria-hidden="true" size={22} />
                      <strong>{empty.title}</strong>
                      <p>{empty.text}</p>
                    </div>
                  ) : (
                    column.orders.map((order) => (
                      <LiveCard
                        amount={money.format(order.total_amount, order.restaurant_id)}
                        column={column}
                        key={order.id}
                        now={now}
                        onOpen={openOrder}
                        order={order}
                        showRestaurant={isAdmin}
                      />
                    ))
                  )}
                  {!isLoading && column.staleTotal > 0 ? (
                    <details className="live-stale">
                      <summary>
                        <span className="live-stale__count">{column.staleTotal}</span>
                        <span className="live-stale__label">
                          older {column.staleTotal === 1 ? "order" : "orders"}, open more than{" "}
                          {staleWords}
                        </span>
                      </summary>
                      <p className="live-stale__note">
                        {STATIC_HELP.stale.what} {STATIC_HELP.stale.action}
                      </p>
                      {column.stale.map((order) => (
                        <LiveCard
                          amount={money.format(order.total_amount, order.restaurant_id)}
                          column={column}
                          key={order.id}
                          now={now}
                          onOpen={openOrder}
                          order={order}
                          showRestaurant={isAdmin}
                          stale
                        />
                      ))}
                      {column.staleTotal > column.stale.length ? (
                        <p className="live-column__more">
                          Showing the newest {column.stale.length} of {column.staleTotal}. The
                          Orders page has the full list.
                        </p>
                      ) : null}
                    </details>
                  ) : null}
                  {!isLoading && column.truncated && column.staleTotal === 0 ? (
                    <p className="live-column__more">
                      Showing the newest {board?.stage_limit ?? 100}. The Orders page has the full
                      list.
                    </p>
                  ) : null}
                </div>
              </div>
            );
          })}
        </section>
      )}

      {!isLoading && board && nothingAtAll && !filtering ? (
        <p className="live-footnote">
          No orders in progress and none finished today. New orders appear here as soon as they
          are paid for.
        </p>
      ) : null}
    </div>
  );
}
