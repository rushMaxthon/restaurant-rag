import { CheckCheck, CircleAlert, Inbox, RefreshCw } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

import type { KitchenOrder, OrderStatus } from '../lib/api'
import { idsOf, newlyArrived, nextStatus } from '../lib/board'
import { matchesFilter, type BoardFilter } from '../lib/metrics'
import { useAdvanceOrder, type BoardScope } from '../lib/queries'
import { isEnabled, playNewOrderChime } from '../lib/sound'
import { Ticket } from './Ticket'

export interface BoardColumn {
  status: OrderStatus
  title: string
  blurb: string
  orders: KitchenOrder[]
  /** Matching this column but beyond the page the server returned. */
  hidden: number
  isLoading: boolean
}

/**
 * The rail: one column per stage of the work, New through Ready.
 *
 * The columns are a PROP, not something this component fetches. They were
 * fetched here at first and reported upward through an effect so the summary
 * bar could count the same rows — which never settled: `useQueries` hands back
 * a new array on every render, so the effect fired, set state in the shell,
 * re-rendered this, and React eventually gave up with "Maximum update depth
 * exceeded". The shell owns the data and counts it during render; this renders
 * it. One source, no synchronisation.
 *
 * What does live here is the announcement of a new ticket. `seenIds` is what
 * the board held on the previous poll — a ref rather than state, because
 * updating it must not itself cause a render or every poll would re-announce
 * everything — and `now` ticks so the timers move.
 */
export function Board({
  columns,
  failed,
  scope,
  filter,
  search,
}: {
  columns: BoardColumn[]
  failed: boolean
  scope: BoardScope
  filter: BoardFilter
  search: string
}) {
  const advance = useAdvanceOrder(scope)

  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    // Every 15s rather than every second: the timers read in whole minutes, so
    // a faster tick would re-render the board to change nothing. Not 60s,
    // because a ticket would then sit up to a minute at the wrong urgency.
    const timer = setInterval(() => setNow(new Date()), 15000)
    return () => clearInterval(timer)
  }, [])

  const everyOrder = useMemo(() => columns.flatMap((column) => column.orders), [columns])
  const stillLoading = columns.some((column) => column.isLoading)

  /**
   * The board's contents as a plain string.
   *
   * Keyed on VALUE rather than on the array, for the same reason the columns
   * are a prop: the array's identity changes every render, so an effect keyed
   * on it runs every render. This changes only when a ticket actually arrives
   * or leaves.
   */
  const idsKey = everyOrder.map((order) => order.id).join(',')

  const seenIds = useRef<Set<string> | null>(null)
  const [freshIds, setFreshIds] = useState<Set<string>>(new Set())

  useEffect(() => {
    if (stillLoading) {
      return
    }
    const previous = seenIds.current
    const current = idsOf(everyOrder)

    if (previous === null) {
      // The first successful poll. Every ticket is technically new, and
      // announcing all of them is a fanfare for a board somebody just opened.
      seenIds.current = current
      return
    }

    const arrived = newlyArrived(previous, everyOrder)
    seenIds.current = current
    if (arrived.length === 0) {
      return
    }

    setFreshIds(new Set(arrived))
    if (isEnabled()) {
      playNewOrderChime()
    }
    const timer = setTimeout(() => setFreshIds(new Set()), 4000)
    return () => clearTimeout(timer)
    // `idsKey` IS `everyOrder`, by value. Depending on the array itself
    // reintroduces the per-render churn the key exists to remove, so the rule
    // is silenced on the next line only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idsKey, stillLoading])

  const [failures, setFailures] = useState<Record<string, string>>({})

  function handleAdvance(order: KitchenOrder) {
    const next = nextStatus(order.status)
    if (!next) {
      return
    }
    setFailures((current) => {
      if (!(order.id in current)) {
        return current
      }
      const rest = { ...current }
      delete rest[order.id]
      return rest
    })
    advance.mutate(
      { orderId: order.id, nextStatus: next, order },
      {
        onError: (error) =>
          setFailures((current) => ({
            ...current,
            [order.id]: error instanceof Error ? error.message : 'That did not go through.',
          })),
      },
    )
  }

  const pendingId =
    advance.isPending && advance.variables
      ? (advance.variables as { orderId: string }).orderId
      : null

  // The whole board is unusable, not one column of it. Showing four columns of
  // tickets nobody can advance is worse than saying so.
  if (failed && everyOrder.length === 0) {
    return (
      <div className="kds-fault">
        <div className="kds-fault__inner">
          <span className="kds-fault__icon">
            <CircleAlert size={24} />
          </span>
          <h2>The board isn’t updating</h2>
          <p>
            The kitchen can’t reach the server. Orders already placed are safe — this screen
            will catch up as soon as the connection is back.
          </p>
          <button className="kds-btn" onClick={() => window.location.reload()} type="button">
            <RefreshCw size={15} /> Try again
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="kds-board">
      {columns.map((column) => {
        const visible = column.orders.filter((order) =>
          matchesFilter(order, filter, search, now),
        )
        const filtering = filter !== 'ALL' || search.trim() !== ''
        return (
          <section className="kds-col" data-col={column.status} key={column.status}>
            <header className="kds-col__head">
              <span className="kds-col__dot" />
              <h2 className="kds-col__title">{column.title}</h2>
              <span className="kds-col__count">{visible.length}</span>
            </header>
            <div className="kds-col__body">
              {column.isLoading && column.orders.length === 0 ? (
                <>
                  <div className="kds-skeleton" />
                  <div className="kds-skeleton" />
                </>
              ) : null}

              {visible.map((order) => (
                <Ticket
                  error={failures[order.id] ?? null}
                  fresh={freshIds.has(order.id)}
                  key={order.id}
                  now={now}
                  onAdvance={() => handleAdvance(order)}
                  order={order}
                  pending={pendingId === order.id}
                />
              ))}

              {/* Only ever rendered when the queue outgrew one page. It says
                  the count rather than a vague "and more", because a cook
                  deciding whether to call the manager needs the number — and
                  because a board that quietly shows part of a queue is the bug
                  this whole change exists to remove. */}
              {column.hidden > 0 ? (
                <p className="kds-col__overflow">
                  {column.hidden} more {column.hidden === 1 ? 'ticket is' : 'tickets are'} waiting
                  and not shown here. Work through these first, or ask your manager.
                </p>
              ) : null}

              {!column.isLoading && visible.length === 0 ? (
                <div className="kds-empty">
                  <span className="kds-empty__icon">
                    {filtering ? <Inbox size={18} /> : <CheckCheck size={18} />}
                  </span>
                  <strong>{filtering ? 'Nothing matches' : emptyTitleFor(column.status)}</strong>
                  <span>{filtering ? 'Try another filter' : column.blurb}</span>
                </div>
              ) : null}
            </div>
          </section>
        )
      })}
    </div>
  )
}

/** Worded per column, so an empty rail reads as calm rather than as broken. */
function emptyTitleFor(status: OrderStatus): string {
  switch (status) {
    case 'PLACED':
      return 'No new orders'
    case 'ACCEPTED':
      return 'Nothing waiting'
    case 'PREPARING':
      return 'Nothing on the pass'
    default:
      return 'All handed over'
  }
}
