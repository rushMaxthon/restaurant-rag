import { AlertTriangle, Bike, CalendarClock, Loader2, Store } from 'lucide-react'

import type { KitchenOrder } from '../lib/api'
import {
  advanceLabel,
  formatWait,
  lineDetail,
  nextStatus,
  orderCode,
  urgencyOf,
  waitingMinutes,
} from '../lib/board'
import { priorityLabel } from '../lib/metrics'

/**
 * One order, as a kitchen reads it.
 *
 * The scan order is ORDER -> TIME -> ITEMS -> ACTION, and the layout follows
 * it exactly: code and elapsed minutes on one line, the dishes as the visual
 * bulk, one full-width action at the bottom. Quantity is the heaviest thing
 * on the card and always in the same column, because on a busy rail it is the
 * first thing anybody looks for.
 *
 * What is deliberately NOT here matters as much. No prices, no payment
 * method beyond whether cash is owed, no delivery address — a cook needs none
 * of them, and an address is somebody's home displayed on a wall. No table
 * number and no dine-in, because `OrderFulfillmentType` is DELIVERY or PICKUP
 * and nothing else. No veg/non-veg mark, because `OrderItemResponse` carries
 * no `is_veg` and a dot guessed from a dish name is exactly the kind of claim
 * that gets a plate sent back.
 */
export function Ticket({
  order,
  now,
  fresh,
  pending,
  error,
  onAdvance,
}: {
  order: KitchenOrder
  now: Date
  /** Arrived since the last poll — worth one animation, then never again. */
  fresh: boolean
  pending: boolean
  error: string | null
  onAdvance: () => void
}) {
  const urgency = urgencyOf(order, now)
  const waited = waitingMinutes(order, now)
  const flag = priorityLabel(order, now)
  const label = advanceLabel(order)
  const canAdvance = nextStatus(order.status) !== null
  const isDelivery = order.fulfillment_type === 'DELIVERY'
  const isScheduled = order.schedule_type === 'SCHEDULED' && Boolean(order.scheduled_at)
  // The name the customer gave at checkout, falling back to the account's.
  const who = order.contact_name?.trim() || order.customer?.full_name?.trim() || null

  return (
    <article className="kds-ticket" data-urgency={urgency} data-fresh={fresh}>
      <header className="kds-ticket__head">
        <span className="kds-code">{orderCode(order)}</span>
        {/* Derived from how long it has waited, not read off a field — this
            backend has no priority column, and a badge with nothing behind it
            is worse than none. */}
        {flag ? (
          <span className="kds-flag" data-level={flag}>
            {flag}
          </span>
        ) : null}
        <span className="kds-elapsed">
          <span className="kds-elapsed__mins">{formatWait(waited)}</span>
          <span className="kds-elapsed__at">{clockTime(order.placed_at)}</span>
        </span>
      </header>

      <div className="kds-meta">
        {isDelivery ? <Bike size={12} /> : <Store size={12} />}
        <span>{isDelivery ? 'Delivery' : 'Pickup'}</span>
        {who ? (
          <>
            <span className="kds-meta__sep">·</span>
            <span>{who}</span>
          </>
        ) : null}
        {isScheduled ? (
          <>
            <span className="kds-meta__sep">·</span>
            <span className="kds-meta__sched">
              <CalendarClock size={11} /> {clockTime(order.scheduled_at)}
            </span>
          </>
        ) : null}
      </div>

      <ul className="kds-items">
        {order.items.map((line) => {
          const mods = lineDetail(line)
          return (
            <li className="kds-item" key={line.id}>
              <span className="kds-item__qty">{line.quantity}×</span>
              <div className="kds-item__body">
                <p className="kds-item__name">{line.item_name_snapshot}</p>
                {mods ? <p className="kds-item__mods">{mods}</p> : null}
                {line.special_instructions ? (
                  <p className="kds-item__note">“{line.special_instructions}”</p>
                ) : null}
              </div>
            </li>
          )
        })}
      </ul>

      {order.special_instructions ? (
        <p className="kds-note">
          <AlertTriangle size={13} />
          <span>{order.special_instructions}</span>
        </p>
      ) : null}

      <footer className="kds-foot">
        <span className="kds-pay" data-kind={payKind(order.payment_status)}>
          {payLabel(order.payment_status)}
        </span>
        {canAdvance && label ? (
          <button
            className="kds-act"
            // The last step completes an order rather than passing it on, so
            // it reads as done instead of competing with the orange that
            // everywhere else means "this one next".
            data-kind={order.status === 'OUT_FOR_DELIVERY' ? 'finish' : 'next'}
            disabled={pending}
            onClick={onAdvance}
            type="button"
          >
            {pending ? <Loader2 className="kds-spin" size={14} /> : null}
            {pending ? 'Working…' : label}
          </button>
        ) : null}
      </footer>

      {/* The server's own sentence. It refuses an advance for real reasons — a
          payment that has not settled, a status that moved under the cook's
          finger — and paraphrasing would lose the one that matters. */}
      {error ? <p className="kds-ticket__error">{error}</p> : null}
    </article>
  )
}

function clockTime(iso: string | null): string {
  if (!iso) return ''
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) return ''
  return new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(at)
}

/**
 * The only payment fact a kitchen acts on: whether cash is owed at handover.
 *
 * Everything else is the office's problem, so PAID is stated once and quietly
 * rather than being the loudest thing in the footer.
 */
function payLabel(status: string): string {
  switch (status.toUpperCase()) {
    case 'COD':
      return 'Collect cash'
    case 'PAID':
      return 'Paid'
    case 'REFUNDED':
      return 'Refunded'
    default:
      return 'Unpaid'
  }
}

function payKind(status: string): string {
  const upper = status.toUpperCase()
  if (upper === 'COD') return 'COD'
  if (upper === 'PAID' || upper === 'REFUNDED') return 'PAID'
  return 'UNPAID'
}
