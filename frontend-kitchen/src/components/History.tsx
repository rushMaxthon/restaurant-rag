import {
  AlertTriangle,
  ArrowLeft,
  Bike,
  CalendarClock,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  History as HistoryIcon,
  Loader2,
  RefreshCw,
  Search,
  Store,
  X,
} from 'lucide-react'
import { useEffect, useState } from 'react'

import type { KitchenOrder } from '../lib/api'
import { clockTime, orderCode, payKind } from '../lib/board'
import {
  completedLabel,
  itemCount,
  pageSummary,
  searchTerm,
  settledPaymentLabel,
} from '../lib/history'
import { useOrderHistory, type BoardScope } from '../lib/queries'
import { OrderItems } from './OrderItems'

/**
 * Orders that already went out, for "did #3F2A go out?" and "what was in it?".
 *
 * An overlay rather than a separate screen, on purpose: the board underneath
 * stays mounted, so it keeps polling, keeps its socket and still chimes for a
 * new ticket while somebody is looking something up. A cook who opened the
 * history to answer the phone must not miss the next order because of it.
 *
 * Strictly read-only. There is no action on a finished order — the flow is
 * linear and DELIVERED is its end — so the detail view has no button that
 * could imply otherwise.
 *
 * The scope is the board's own, passed in, and the server resolves it with
 * the same `resolve_order_board_scope`: a pinned cook's history is their
 * branch's, and asking for another is refused there, not merely hidden here.
 */
export function History({
  scope,
  showBranch,
  pollIntervalMs,
  onClose,
}: {
  scope: BoardScope
  /** True while the board shows every branch, so each order says whose it was. */
  showBranch: boolean
  /** The board's own poll rate, so an order finished on another tablet shows up here too. */
  pollIntervalMs: number
  onClose: () => void
}) {
  const [input, setInput] = useState('')
  const [search, setSearch] = useState<string | null>(null)
  const [page, setPage] = useState(0)
  const [selected, setSelected] = useState<KitchenOrder | null>(null)

  // Debounced so a code typed one character at a time is one request, not
  // eight. The page resets in the change handler, not here, so the list never
  // briefly asks for page 3 of a search that has one result.
  useEffect(() => {
    const timer = setTimeout(() => setSearch(searchTerm(input)), 300)
    return () => clearTimeout(timer)
  }, [input])

  // Escape backs out one level: detail -> list -> board.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key !== 'Escape') return
      if (selected) setSelected(null)
      else onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selected, onClose])

  const history = useOrderHistory(scope, { search, page, enabled: true, pollIntervalMs })
  const rows = history.data?.rows ?? []
  const summary = pageSummary(page, rows.length, history.data?.total ?? 0)

  return (
    <div className="kds-history" role="dialog" aria-modal="true" aria-label="Completed orders">
      <button
        aria-label="Close completed orders"
        className="kds-history__scrim"
        onClick={onClose}
        tabIndex={-1}
        type="button"
      />
      <section className="kds-history__panel">
        {selected ? (
          <HistoryDetail
            now={new Date()}
            onBack={() => setSelected(null)}
            order={selected}
            showBranch={showBranch}
          />
        ) : (
          <>
            <header className="kds-history__head">
              <span className="kds-history__icon">
                <HistoryIcon size={16} />
              </span>
              <div className="kds-history__titles">
                <h2>Completed orders</h2>
                <p>{search ? `All dates · matching “${search}”` : 'Today'}</p>
              </div>
              <button
                aria-label="Close completed orders"
                className="kds-iconbtn"
                onClick={onClose}
                type="button"
              >
                <X size={18} />
              </button>
            </header>

            <label className="kds-search kds-history__search">
              <Search size={13} />
              <input
                aria-label="Search completed orders by order number"
                onChange={(event) => {
                  setInput(event.target.value)
                  setPage(0)
                }}
                placeholder="Search order # (all dates)"
                value={input}
              />
              {history.isFetching ? <Loader2 className="kds-spin" size={13} /> : null}
            </label>

            <div className="kds-history__list">
              {history.isLoading ? (
                <>
                  <div className="kds-skeleton" />
                  <div className="kds-skeleton" />
                  <div className="kds-skeleton" />
                </>
              ) : history.isError && rows.length === 0 ? (
                <div className="kds-empty">
                  <span className="kds-empty__icon">
                    <CircleAlert size={18} />
                  </span>
                  <strong>Couldn’t load completed orders</strong>
                  <span>
                    {history.error instanceof Error ? history.error.message : 'Try again.'}
                  </span>
                  <button className="kds-btn kds-btn--ghost" onClick={() => void history.refetch()} type="button">
                    <RefreshCw size={14} /> Try again
                  </button>
                </div>
              ) : rows.length === 0 ? (
                <div className="kds-empty">
                  <span className="kds-empty__icon">
                    <HistoryIcon size={18} />
                  </span>
                  <strong>{search ? 'No completed order matches' : 'Nothing completed yet today'}</strong>
                  <span>
                    {search
                      ? 'Check the number on the receipt — the first eight characters are enough.'
                      : 'Orders appear here once they are marked Delivered or Collected.'}
                  </span>
                </div>
              ) : (
                rows.map((order) => (
                  <HistoryRow
                    key={order.id}
                    now={new Date()}
                    onOpen={() => setSelected(order)}
                    order={order}
                    showBranch={showBranch}
                  />
                ))
              )}
            </div>

            {summary.total > 0 ? (
              <footer className="kds-history__pager">
                <span>
                  {summary.from}–{summary.to} of {summary.total}
                </span>
                <div className="kds-history__pager-btns">
                  <button
                    aria-label="Previous page"
                    className="kds-iconbtn"
                    disabled={!summary.hasPrevious || history.isFetching}
                    onClick={() => setPage((current) => Math.max(0, current - 1))}
                    type="button"
                  >
                    <ChevronLeft size={18} />
                  </button>
                  <button
                    aria-label="Next page"
                    className="kds-iconbtn"
                    disabled={!summary.hasNext || history.isFetching}
                    onClick={() => setPage((current) => current + 1)}
                    type="button"
                  >
                    <ChevronRight size={18} />
                  </button>
                </div>
              </footer>
            ) : null}
          </>
        )}
      </section>
    </div>
  )
}

function HistoryRow({
  order,
  now,
  showBranch,
  onOpen,
}: {
  order: KitchenOrder
  now: Date
  showBranch: boolean
  onOpen: () => void
}) {
  const isDelivery = order.fulfillment_type === 'DELIVERY'
  const who = order.contact_name?.trim() || order.customer?.full_name?.trim() || null
  return (
    <button className="kds-hrow" onClick={onOpen} type="button">
      <span className="kds-code">{orderCode(order)}</span>
      <span className="kds-hrow__time">{completedLabel(order.completed_at, now)}</span>
      <span className="kds-hrow__meta">
        {isDelivery ? <Bike size={12} /> : <Store size={12} />}
        <span>{isDelivery ? 'Delivery' : 'Pickup'}</span>
        {who ? (
          <>
            <span className="kds-meta__sep">·</span>
            <span className="kds-hrow__who">{who}</span>
          </>
        ) : null}
        {showBranch && order.restaurant_location ? (
          <>
            <span className="kds-meta__sep">·</span>
            <span>{order.restaurant_location.branch_name}</span>
          </>
        ) : null}
      </span>
      <span className="kds-hrow__count">{itemCount(order.items)}</span>
      <ChevronRight className="kds-hrow__chev" size={16} />
    </button>
  )
}

/** One finished order in full: every dish, size, option and half, and nothing to press. */
function HistoryDetail({
  order,
  now,
  showBranch,
  onBack,
}: {
  order: KitchenOrder
  now: Date
  showBranch: boolean
  onBack: () => void
}) {
  const isDelivery = order.fulfillment_type === 'DELIVERY'
  const isScheduled = order.schedule_type === 'SCHEDULED' && Boolean(order.scheduled_at)
  const who = order.contact_name?.trim() || order.customer?.full_name?.trim() || null
  return (
    <>
      <header className="kds-history__head">
        <button aria-label="Back to completed orders" className="kds-iconbtn" onClick={onBack} type="button">
          <ArrowLeft size={18} />
        </button>
        <div className="kds-history__titles">
          <h2>{orderCode(order)}</h2>
          <p>{isDelivery ? 'Delivered' : 'Collected'} · {completedLabel(order.completed_at, now)}</p>
        </div>
        <span className="kds-history__badge">Completed</span>
      </header>

      <div className="kds-history__detail">
        <dl className="kds-facts">
          <div>
            <dt>Ordered</dt>
            <dd>{completedLabel(order.placed_at, now)}</dd>
          </div>
          {isScheduled ? (
            <div>
              <dt>Scheduled for</dt>
              <dd className="kds-meta__sched">
                <CalendarClock size={12} /> {clockTime(order.scheduled_at)}
              </dd>
            </div>
          ) : null}
          <div>
            <dt>Type</dt>
            <dd>{isDelivery ? 'Delivery' : 'Pickup'}</dd>
          </div>
          {who ? (
            <div>
              <dt>Customer</dt>
              <dd>{who}</dd>
            </div>
          ) : null}
          {showBranch && order.restaurant_location ? (
            <div>
              <dt>Branch</dt>
              <dd>{order.restaurant_location.branch_name}</dd>
            </div>
          ) : null}
          <div>
            <dt>Payment</dt>
            <dd>
              <span className="kds-pay" data-kind={payKind(order.payment_status)}>
                {settledPaymentLabel(order.payment_status)}
              </span>
            </dd>
          </div>
        </dl>

        <h3 className="kds-history__section">{itemCount(order.items)}</h3>
        <OrderItems items={order.items} />

        {order.special_instructions ? (
          <p className="kds-note">
            <AlertTriangle size={13} />
            <span>{order.special_instructions}</span>
          </p>
        ) : null}
      </div>
    </>
  )
}
