import {
  Ban,
  CheckCircle2,
  CircleAlert,
  EyeOff,
  Hourglass,
  Loader2,
  Minus,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  UtensilsCrossed,
  X,
} from 'lucide-react'
import { useEffect, useMemo, useState, type FormEvent } from 'react'

import type { DishStockChange, KitchenMenuItem, SizeStockChange } from '../lib/api'
import {
  MENU_FILTERS,
  backInStockNeedsCount,
  changedCount,
  countText,
  matchesMenuFilter,
  menuSummary,
  sectionsOf,
  sizeLabel,
  stockLabel,
  stockState,
  type MenuFilter,
} from '../lib/menu'
import { useKitchenMenu, useStockChange, type BoardScope } from '../lib/queries'

/**
 * The kitchen's side of the menu: what is in stock right now.
 *
 * An overlay over the board, like the completed orders and for the same
 * reason — the board underneath keeps polling and chiming while a cook marks
 * the curry sold out. What is ON the menu, and at what price, stays the
 * owner's: a dish they hid is listed (so the kitchen knows why it is missing
 * from the storefront) but cannot be shown again from here.
 */
export function Menu({
  scope,
  showBranch,
  branchName,
  onClose,
}: {
  scope: BoardScope
  showBranch: boolean
  branchName: string | null
  onClose: () => void
}) {
  const menu = useKitchenMenu(scope, true)
  const change = useStockChange(scope)
  const [filter, setFilter] = useState<MenuFilter>('ALL')
  const [search, setSearch] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})

  // Escape backs out one level: editor -> list -> board.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key !== 'Escape') return
      if (editingId) setEditingId(null)
      else onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [editingId, onClose])

  const items = useMemo(() => menu.data ?? [], [menu.data])
  const visible = useMemo(() => items.filter((item) => matchesMenuFilter(item, filter, search)), [items, filter, search])
  const sections = useMemo(() => sectionsOf(visible, showBranch), [visible, showBranch])
  const summary = useMemo(() => menuSummary(items), [items])
  const pendingId = change.isPending ? change.variables?.item.id ?? null : null

  async function send(item: KitchenMenuItem, run: () => Promise<unknown>): Promise<boolean> {
    setErrors((current) => {
      if (!(item.id in current)) return current
      const rest = { ...current }
      delete rest[item.id]
      return rest
    })
    try {
      await run()
      return true
    } catch (error) {
      // The server's own sentence: a 404 means the dish left this branch.
      setErrors((current) => ({
        ...current,
        [item.id]: error instanceof Error ? error.message : 'That did not save.',
      }))
      return false
    }
  }

  const updateDish = (item: KitchenMenuItem, dishChange: DishStockChange) =>
    send(item, () => change.mutateAsync({ kind: 'dish', item, change: dishChange }))

  const updateSize = (item: KitchenMenuItem, sizeId: string, sizeChange: SizeStockChange) =>
    send(item, () => change.mutateAsync({ kind: 'size', item, sizeId, change: sizeChange }))

  function toggle(item: KitchenMenuItem) {
    if (!item.out_of_stock) void updateDish(item, { out_of_stock: true })
    // Back on at a count of zero would still be sold out: ask for a count.
    else if (backInStockNeedsCount(item)) setEditingId(item.id)
    else void updateDish(item, { out_of_stock: false })
  }

  return (
    <div className="kds-history" role="dialog" aria-modal="true" aria-label="Menu and stock">
      <button aria-label="Close menu" className="kds-history__scrim" onClick={onClose} tabIndex={-1} type="button" />
      <section className="kds-history__panel kds-menu">
        <header className="kds-history__head">
          <span className="kds-history__icon">
            <UtensilsCrossed size={16} />
          </span>
          <div className="kds-history__titles">
            <h2>Menu &amp; stock</h2>
            <p>{branchName ?? 'This branch'}</p>
          </div>
          <button aria-label="Close menu" className="kds-iconbtn" onClick={onClose} type="button">
            <X size={18} />
          </button>
        </header>

        <div className="kds-menu__summary">
          <span className="kds-menu__stat" data-tone={summary.out ? 'late' : undefined}>
            <Ban size={13} /> {summary.out} out of stock
          </span>
          <span className="kds-menu__stat" data-tone={summary.low ? 'warn' : undefined}>
            <Hourglass size={13} /> {summary.low} running low
          </span>
          <span className="kds-menu__stat">
            <EyeOff size={13} /> {summary.hidden} hidden
          </span>
        </div>

        <label className="kds-search kds-history__search">
          <Search size={13} />
          <input
            aria-label="Search dishes"
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search dishes"
            value={search}
          />
          {menu.isFetching ? <Loader2 className="kds-spin" size={13} /> : null}
        </label>

        <div className="kds-chips kds-menu__filters">
          {MENU_FILTERS.map((entry) => (
            <button
              aria-pressed={filter === entry.key}
              className="kds-chip"
              data-active={filter === entry.key}
              key={entry.key}
              onClick={() => setFilter(entry.key)}
              type="button"
            >
              {entry.label}
            </button>
          ))}
        </div>

        <div className="kds-history__list">
          {menu.isLoading ? (
            <>
              <div className="kds-skeleton" />
              <div className="kds-skeleton" />
              <div className="kds-skeleton" />
            </>
          ) : menu.isError && items.length === 0 ? (
            <div className="kds-empty">
              <span className="kds-empty__icon">
                <CircleAlert size={18} />
              </span>
              <strong>Couldn’t load the menu</strong>
              <span>{menu.error instanceof Error ? menu.error.message : 'Try again.'}</span>
              <button className="kds-btn kds-btn--ghost" onClick={() => void menu.refetch()} type="button">
                <RefreshCw size={14} /> Try again
              </button>
            </div>
          ) : items.length === 0 ? (
            <div className="kds-empty">
              <span className="kds-empty__icon">
                <UtensilsCrossed size={18} />
              </span>
              <strong>No dishes on this menu yet</strong>
              <span>Dishes are added by the restaurant owner in the admin panel.</span>
            </div>
          ) : sections.length === 0 ? (
            <div className="kds-empty">
              <span className="kds-empty__icon">
                <Search size={18} />
              </span>
              <strong>Nothing matches</strong>
              <span>Try another filter or clear the search.</span>
            </div>
          ) : (
            sections.map((section) => (
              <div className="kds-menu__section" key={section.title}>
                <h3 className="kds-menu__section-title">{section.title}</h3>
                {section.dishes.map((item) => (
                  <MenuRow
                    editing={editingId === item.id}
                    error={errors[item.id] ?? null}
                    item={item}
                    key={item.id}
                    onCloseEditor={() => setEditingId(null)}
                    onEdit={() => setEditingId(editingId === item.id ? null : item.id)}
                    onSave={async (dishChange, sizeChanges) => {
                      if (Object.keys(dishChange).length && !(await updateDish(item, dishChange))) return false
                      for (const { sizeId, change: sizeChange } of sizeChanges) {
                        if (!(await updateSize(item, sizeId, sizeChange))) return false
                      }
                      return true
                    }}
                    onStep={(delta) =>
                      item.stock_quantity === null
                        ? undefined
                        : void updateDish(item, { stock_quantity: Math.max(0, item.stock_quantity + delta) })
                    }
                    onToggle={() => toggle(item)}
                    pending={pendingId === item.id}
                  />
                ))}
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  )
}

function MenuRow({
  item,
  pending,
  error,
  editing,
  onToggle,
  onStep,
  onEdit,
  onCloseEditor,
  onSave,
}: {
  item: KitchenMenuItem
  pending: boolean
  error: string | null
  editing: boolean
  onToggle: () => void
  onStep: (delta: number) => void
  onEdit: () => void
  onCloseEditor: () => void
  onSave: (dish: DishStockChange, sizes: { sizeId: string; change: SizeStockChange }[]) => Promise<boolean>
}) {
  const state = stockState(item)
  const counted = item.stock_quantity !== null
  const isOut = item.out_of_stock
  const toggleLabel = isOut ? (backInStockNeedsCount(item) ? 'Restock…' : 'Back in stock') : 'Mark out of stock'

  return (
    <article className="kds-mrow" data-state={state}>
      <div className="kds-mrow__top">
        <button className="kds-mrow__main" onClick={onEdit} type="button" aria-expanded={editing}>
          <span className="kds-mrow__name">
            <span className="kds-veg" data-veg={item.is_veg} aria-label={item.is_veg ? 'Vegetarian' : 'Non-vegetarian'} />
            {item.name}
          </span>
          <span className="kds-mrow__meta">
            <span className="kds-mrow__pill" data-state={state}>
              {stockLabel(item)}
            </span>
            {item.stock_daily_quantity !== null ? (
              <span className="kds-mrow__refill">
                <RefreshCw size={11} /> {item.stock_daily_quantity} each morning
              </span>
            ) : null}
            {item.sizes.map((size) => (
              <span className="kds-mrow__size" data-sold-out={size.stock_quantity === 0} key={size.id}>
                {size.name}: {sizeLabel(size)}
              </span>
            ))}
          </span>
          {state === 'hidden' ? (
            <span className="kds-mrow__note">The owner has taken this off the menu. Stock can still be kept ready.</span>
          ) : null}
        </button>

        <div className="kds-mrow__actions">
          {counted && !isOut ? (
            <span className="kds-stepper">
              <button
                aria-label={`One fewer ${item.name}`}
                disabled={pending || item.stock_quantity === 0}
                onClick={() => onStep(-1)}
                type="button"
              >
                <Minus size={14} />
              </button>
              <span className="kds-stepper__value">{item.stock_quantity}</span>
              <button aria-label={`One more ${item.name}`} disabled={pending} onClick={() => onStep(1)} type="button">
                <Plus size={14} />
              </button>
            </span>
          ) : null}
          {/* Short on the line, full for a screen reader. */}
          <button
            aria-label={`${toggleLabel}: ${item.name}`}
            className="kds-mrow__toggle"
            data-kind={isOut ? 'restore' : 'out'}
            disabled={pending}
            onClick={onToggle}
            title={toggleLabel}
            type="button"
          >
            {pending ? <Loader2 className="kds-spin" size={13} /> : isOut ? <CheckCircle2 size={13} /> : <Ban size={13} />}
            {isOut ? (backInStockNeedsCount(item) ? 'Restock' : 'In stock') : 'Out'}
          </button>
          <button aria-label={`Edit stock: ${item.name}`} className="kds-iconbtn" onClick={onEdit} type="button">
            <Pencil size={13} />
          </button>
        </div>
      </div>

      {editing ? <StockEditor item={item} onClose={onCloseEditor} onSave={onSave} pending={pending} /> : null}

      {error ? (
        <p className="kds-ticket__error" role="alert">
          {error}
        </p>
      ) : null}
    </article>
  )
}

/** Everything about one dish's stock. Only boxes that were changed are sent. */
function StockEditor({
  item,
  pending,
  onClose,
  onSave,
}: {
  item: KitchenMenuItem
  pending: boolean
  onClose: () => void
  onSave: (dish: DishStockChange, sizes: { sizeId: string; change: SizeStockChange }[]) => Promise<boolean>
}) {
  const [outOfStock, setOutOfStock] = useState(item.out_of_stock)
  const [count, setCount] = useState(countText(item.stock_quantity))
  const [daily, setDaily] = useState(countText(item.stock_daily_quantity))
  const [sizes, setSizes] = useState(() =>
    Object.fromEntries(
      item.sizes.map((size) => [size.id, { count: countText(size.stock_quantity), daily: countText(size.stock_daily_quantity) }]),
    ),
  )
  const [problem, setProblem] = useState<string | null>(null)

  async function submit(event: FormEvent) {
    event.preventDefault()
    try {
      const dish: DishStockChange = {}
      if (outOfStock !== item.out_of_stock) dish.out_of_stock = outOfStock
      const nextCount = changedCount(count, item.stock_quantity)
      if (nextCount.changed) dish.stock_quantity = nextCount.value
      const nextDaily = changedCount(daily, item.stock_daily_quantity)
      if (nextDaily.changed) dish.stock_daily_quantity = nextDaily.value
      const sizeChanges = item.sizes.flatMap((size) => {
        const typed = sizes[size.id]
        const sizeChange: SizeStockChange = {}
        const c = changedCount(typed.count, size.stock_quantity)
        if (c.changed) sizeChange.stock_quantity = c.value
        const d = changedCount(typed.daily, size.stock_daily_quantity)
        if (d.changed) sizeChange.stock_daily_quantity = d.value
        return Object.keys(sizeChange).length ? [{ sizeId: size.id, change: sizeChange }] : []
      })
      setProblem(null)
      if (!Object.keys(dish).length && !sizeChanges.length) {
        onClose()
        return
      }
      if (await onSave(dish, sizeChanges)) onClose()
    } catch (error) {
      setProblem(error instanceof Error ? error.message : 'Check the numbers and try again.')
    }
  }

  return (
    <form className="kds-mrow__edit" onSubmit={submit}>
      {!item.is_available ? (
        <p className="kds-mrow__note">
          <EyeOff size={13} /> Hidden by the owner: customers cannot see it whatever its stock.
        </p>
      ) : null}
      <label className="kds-field kds-field--check">
        <input checked={outOfStock} onChange={(event) => setOutOfStock(event.target.checked)} type="checkbox" />
        <span>
          <strong>Out of stock</strong> — stays on the menu, but nobody can order it
        </span>
      </label>
      <div className="kds-mrow__fields">
        <label className="kds-field">
          <span>Left now</span>
          <input inputMode="numeric" onChange={(event) => setCount(event.target.value)} placeholder="Not counted" value={count} />
          <small>Goes down with every order. Empty means not counted.</small>
        </label>
        <label className="kds-field">
          <span>Each morning</span>
          <input inputMode="numeric" onChange={(event) => setDaily(event.target.value)} placeholder="Restocked by hand" value={daily} />
          <small>The count is set back to this every morning.</small>
        </label>
      </div>
      {item.sizes.length ? (
        <div className="kds-mrow__sizes">
          <small>A size with its own count sells from it; an empty size uses the dish’s count.</small>
          {item.sizes.map((size) => (
            <div className="kds-mrow__fields" key={size.id}>
              <label className="kds-field">
                <span>{size.name} — left now</span>
                <input
                  inputMode="numeric"
                  onChange={(event) => setSizes({ ...sizes, [size.id]: { ...sizes[size.id], count: event.target.value } })}
                  placeholder="Uses dish count"
                  value={sizes[size.id].count}
                />
              </label>
              <label className="kds-field">
                <span>{size.name} — each morning</span>
                <input
                  inputMode="numeric"
                  onChange={(event) => setSizes({ ...sizes, [size.id]: { ...sizes[size.id], daily: event.target.value } })}
                  placeholder="Restocked by hand"
                  value={sizes[size.id].daily}
                />
              </label>
            </div>
          ))}
        </div>
      ) : null}
      {problem ? (
        <p className="kds-ticket__error" role="alert">
          {problem}
        </p>
      ) : null}
      <div className="kds-mrow__editactions">
        <button className="kds-btn kds-btn--ghost" onClick={onClose} type="button">
          Cancel
        </button>
        <button className="kds-btn" disabled={pending} type="submit">
          {pending ? <Loader2 className="kds-spin" size={14} /> : null}
          Save stock
        </button>
      </div>
    </form>
  )
}
