import { ChefHat, History as HistoryIcon, LogOut, Search, Volume2, VolumeX } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from 'react'
import { useQuery } from '@tanstack/react-query'

import { api, type KitchenOrder } from './lib/api'
import { useAuth } from './lib/auth-context'
import { BOARD_COLUMNS, formatWait } from './lib/board'
import { boardMetrics, type BoardFilter } from './lib/metrics'
import { isAudioReady, setEnabled, subscribeAudioReady, unlockOnAnyGesture } from './lib/sound'
import { Board, type BoardColumn } from './components/Board'
import { History } from './components/History'
import { SignIn } from './components/SignIn'
import { useBoard, type BoardScope } from './lib/queries'
import { pollIntervalFor, type RealtimeStatus } from './lib/realtime'
import { useRealtimeBoard } from './lib/useRealtime'

const SOUND_KEY = 'kitchen-sound'
const BRANCH_KEY = 'kitchen-branch'

/** The toolbar, left to right. Only filters this data can honestly answer. */
const FILTERS: { key: BoardFilter; label: string; group: 'stage' | 'type' }[] = [
  { key: 'ALL', label: 'All', group: 'stage' },
  { key: 'PLACED', label: 'New', group: 'stage' },
  { key: 'ACCEPTED', label: 'Accepted', group: 'stage' },
  { key: 'PREPARING', label: 'Cooking', group: 'stage' },
  { key: 'OUT_FOR_DELIVERY', label: 'Ready', group: 'stage' },
  // There is no Dine-in: `OrderFulfillmentType` is DELIVERY or PICKUP, and a
  // filter for a third kind would always come back empty.
  { key: 'DELIVERY', label: 'Delivery', group: 'type' },
  { key: 'PICKUP', label: 'Pickup', group: 'type' },
  { key: 'PRIORITY', label: 'Priority', group: 'type' },
]

export function App() {
  const { session, signOut } = useAuth()

  const [soundOn, setSoundOn] = useState<boolean>(() => {
    try {
      return localStorage.getItem(SOUND_KEY) !== 'off'
    } catch {
      return true
    }
  })
  useEffect(() => {
    setEnabled(soundOn)
    try {
      localStorage.setItem(SOUND_KEY, soundOn ? 'on' : 'off')
    } catch {
      // A board that cannot remember the setting still honours it this session.
    }
  }, [soundOn])

  // Sign-in is not the only way onto this board — a saved session skips it —
  // so any tap anywhere has to be able to unlock audio, not just that button.
  useEffect(() => unlockOnAnyGesture(), [])
  const audioReady = useSyncExternalStore(subscribeAudioReady, isAudioReady)
  // Switched on but still blocked by the browser: the one state in which the
  // speaker icon alone would be lying.
  const soundBlocked = soundOn && !audioReady

  // Over the board, never instead of it — see `History` for why.
  const [historyOpen, setHistoryOpen] = useState(false)
  const closeHistory = useCallback(() => setHistoryOpen(false), [])

  const [branchId, setBranchId] = useState<string | null>(() => {
    try {
      return localStorage.getItem(BRANCH_KEY)
    } catch {
      return null
    }
  })

  const pinnedLocationId = session?.restaurantLocationId ?? null
  const canChooseBranch = Boolean(session && !pinnedLocationId && session.restaurantId)

  // Fetched for every role, not just the ones that can switch branch: the
  // header names the restaurant and the branch, and one deployment serves
  // every tenant — a board that cannot say whose kitchen it is showing is a
  // board somebody eventually works the wrong queue from.
  const restaurantQuery = useQuery({
    queryKey: ['restaurant', session?.restaurantId ?? 'none'],
    queryFn: () => api.restaurant(session!.restaurantId!),
    enabled: Boolean(session?.restaurantId),
    staleTime: 5 * 60 * 1000,
  })

  const scope = useMemo<BoardScope>(
    () => ({
      restaurantId: session?.restaurantId ?? null,
      // The pin always wins. If the server says this account belongs to one
      // branch, the board must not even ask about another.
      locationId: pinnedLocationId ?? (canChooseBranch ? branchId : null),
    }),
    [session?.restaurantId, pinnedLocationId, canChooseBranch, branchId],
  )

  const chooseBranch = useCallback((next: string) => {
    const value = next || null
    setBranchId(value)
    try {
      if (value) {
        localStorage.setItem(BRANCH_KEY, value)
      } else {
        localStorage.removeItem(BRANCH_KEY)
      }
    } catch {
      // Remembered for this session only.
    }
  }, [])

  const [filter, setFilter] = useState<BoardFilter>('ALL')
  const [search, setSearch] = useState('')

  /**
   * The board's data, owned here.
   *
   * It used to be fetched inside `Board` and reported back up through an
   * effect so the summary bar could count the same rows. That never settled —
   * `useQueries` returns a new array every render, so the effect fired on
   * every render and React ended at "Maximum update depth exceeded". Counting
   * during render from one source has no such failure mode, and the numbers
   * cannot drift from the columns beneath them because they ARE the columns.
   */
  // The socket only says "something changed"; `useBoard` still does all the
  // fetching. Polling slows to a safety net while the socket is live.
  const realtime = useRealtimeBoard(
    session?.restaurantId ? session.token : null,
    scope,
    signOut,
  )
  const results = useBoard(
    scope,
    Boolean(session?.restaurantId),
    pollIntervalFor(realtime ?? 'offline'),
  )
  const columns = useMemo<BoardColumn[]>(
    () =>
      BOARD_COLUMNS.map((column, index) => ({
        ...column,
        orders: (results[index]?.data?.orders ?? []) as KitchenOrder[],
        // Orders matching this column that the page could not carry. Normally
        // 0 — the live window keeps the queue well under the page limit — but
        // it is rendered rather than assumed, because the whole class of bug
        // being fixed here was a board that showed part of a queue and gave no
        // sign of it.
        hidden: results[index]?.data?.hidden ?? 0,
        isLoading: results[index]?.isLoading ?? false,
      })),
    [results],
  )
  const boardFailed = results.some((result) => result.isError)

  // A clock in the header, ticking once a minute because it shows minutes.
  const [clock, setClock] = useState(() => new Date())
  useEffect(() => {
    const timer = setInterval(() => setClock(new Date()), 30000)
    return () => clearInterval(timer)
  }, [])

  const metrics = useMemo(() => boardMetrics(columns, clock), [columns, clock])

  if (!session) {
    return <SignIn />
  }

  // An ADMIN has no restaurant of their own and the board cannot guess one —
  // the same rule every tenant-scoped screen follows. Saying so beats four
  // empty columns that look like a quiet service.
  if (session.role === 'ADMIN' && !session.restaurantId) {
    return (
      <div className="kds">
        <Header
          branchName={null}
          clock={clock}
          onSignOut={signOut}
          onToggleSound={() => setSoundOn((on) => !on)}
          restaurantName={null}
          soundBlocked={soundBlocked}
          soundOn={soundOn}
          stale={false}
        />
        <div className="kds-fault">
          <div className="kds-fault__inner">
            <h2>No restaurant on this account</h2>
            <p>
              Admin accounts have no kitchen of their own. Sign in with the restaurant’s owner
              or kitchen account to open its board.
            </p>
            <button className="kds-btn kds-btn--ghost" onClick={signOut} type="button">
              Switch account
            </button>
          </div>
        </div>
      </div>
    )
  }

  const branches = restaurantQuery.data?.locations ?? []
  const currentBranch =
    branches.find((location) => location.id === scope.locationId) ?? null
  const branchName = currentBranch?.branch_name ?? (scope.locationId ? null : 'All branches')

  return (
    <div className="kds">
      <Header
        branchName={branchName}
        clock={clock}
        // The branch's own open flag, from `/restaurants/{id}`. Not a mode set
        // here: this app has nothing to set it with.
        isOpen={currentBranch?.is_open}
        onOpenHistory={() => setHistoryOpen(true)}
        onSignOut={signOut}
        onToggleSound={() => setSoundOn((on) => !on)}
        restaurantName={restaurantQuery.data?.name ?? null}
        realtime={realtime}
        soundBlocked={soundBlocked}
        soundOn={soundOn}
        stale={boardFailed}
      />

      <div className="kds-metrics">
        <Metric label="New" value={metrics.newCount} />
        <Metric label="Accepted" value={metrics.acceptedCount} />
        <Metric label="Cooking" value={metrics.cookingCount} />
        <Metric label="Ready" value={metrics.readyCount} />
        <Metric
          label="Overdue"
          // Coloured only when it is not zero. A permanently red tile stops
          // being read within a shift.
          tone={metrics.overdue > 0 ? 'late' : 'muted'}
          value={metrics.overdue}
        />
        <Metric
          label="Median wait"
          tone="muted"
          // "Wait", not "prep": this counts from when the customer ordered,
          // and the backend records no start-of-cooking instant.
          value={metrics.medianWait === null ? '—' : formatWait(metrics.medianWait)}
        />
      </div>

      <div className="kds-toolbar">
        <label className="kds-search">
          <Search size={13} />
          <input
            aria-label="Search by order number"
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Order #"
            value={search}
          />
        </label>

        <div className="kds-chips">
          {FILTERS.map((entry, index) => (
            <span key={entry.key} style={{ display: 'contents' }}>
              {index > 0 && entry.group !== FILTERS[index - 1]?.group ? (
                <span className="kds-chip__sep" />
              ) : null}
              <button
                aria-pressed={filter === entry.key}
                className="kds-chip"
                data-active={filter === entry.key}
                onClick={() => setFilter(entry.key)}
                type="button"
              >
                {entry.label}
              </button>
            </span>
          ))}
        </div>

        {canChooseBranch ? (
          <select
            aria-label="Branch"
            className="kds-chip"
            onChange={(event) => chooseBranch(event.target.value)}
            style={{ marginLeft: 'auto' }}
            value={branchId ?? ''}
          >
            <option value="">All branches</option>
            {branches.map((location) => (
              <option key={location.id} value={location.id}>
                {location.branch_name}
              </option>
            ))}
          </select>
        ) : null}
      </div>

      <Board
        columns={columns}
        failed={boardFailed}
        filter={filter}
        scope={scope}
        search={search}
      />

      {historyOpen ? (
        <History
          // A branch switch starts the history over — page 3 of one branch is
          // not a page of another.
          key={`${scope.restaurantId ?? 'any'}:${scope.locationId ?? 'all'}`}
          onClose={closeHistory}
          pollIntervalMs={pollIntervalFor(realtime ?? 'offline')}
          scope={scope}
          // Only when the board spans branches; a pinned cook's history is
          // one branch and saying so on every row would be noise.
          showBranch={scope.locationId === null}
        />
      ) : null}
    </div>
  )
}

function Metric({
  label,
  value,
  tone,
}: {
  label: string
  value: number | string
  tone?: 'late' | 'muted'
}) {
  return (
    <span className="kds-metric" data-tone={tone}>
      <span className="kds-metric__label">{label}</span>
      <span className="kds-metric__value">{value}</span>
    </span>
  )
}

function Header({
  restaurantName,
  branchName,
  isOpen,
  clock,
  realtime,
  stale,
  soundOn,
  soundBlocked,
  onToggleSound,
  onOpenHistory,
  onSignOut,
}: {
  restaurantName: string | null
  branchName: string | null
  isOpen?: boolean
  clock: Date
  realtime?: RealtimeStatus | null
  stale: boolean
  soundOn: boolean
  /** Sound is switched on, but the browser has not been tapped since loading. */
  soundBlocked: boolean
  onToggleSound: () => void
  /** Absent where there is no board to have a history of (an admin with no restaurant). */
  onOpenHistory?: () => void
  onSignOut: () => void
}) {
  return (
    <header className="kds-top">
      <span className="kds-brand">
        <span className="kds-brand__mark">
          <ChefHat size={15} strokeWidth={2.4} />
        </span>
        Kitchen
      </span>

      {restaurantName ? (
        <span className="kds-where">
          <span>{restaurantName}</span>
          {branchName ? (
            <>
              <span className="kds-where__sep">·</span>
              <span className="kds-where__branch">{branchName}</span>
            </>
          ) : null}
        </span>
      ) : null}

      <div className="kds-top__right">
        <LiveIndicator realtime={realtime ?? null} stale={stale} />

        <span className="kds-clock">
          {new Intl.DateTimeFormat(undefined, {
            weekday: 'short',
            day: 'numeric',
            month: 'short',
          }).format(clock)}
          {' · '}
          {new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(
            clock,
          )}
        </span>

        {isOpen === undefined ? null : (
          <span className="kds-open" data-open={isOpen}>
            {isOpen ? 'OPEN' : 'CLOSED'}
          </span>
        )}

        {/* Tapping it is itself the gesture that unlocks audio (so is any
            other tap); it disappears the moment the browser allows sound. */}
        {onOpenHistory ? (
          <button
            aria-label="Completed orders"
            className="kds-historybtn"
            onClick={onOpenHistory}
            type="button"
          >
            <HistoryIcon size={14} />
            <span className="kds-historybtn__label">Completed</span>
          </button>
        ) : null}

        {soundBlocked ? (
          <button className="kds-soundhint" type="button">
            <VolumeX size={13} /> Tap to enable sound
          </button>
        ) : null}

        <button
          aria-label={soundOn ? 'Mute new order sound' : 'Unmute new order sound'}
          aria-pressed={soundOn}
          className="kds-iconbtn"
          data-on={soundOn}
          onClick={onToggleSound}
          type="button"
        >
          {soundOn ? <Volume2 size={16} /> : <VolumeX size={16} />}
        </button>

        <button
          aria-label="Sign out"
          className="kds-iconbtn"
          onClick={onSignOut}
          type="button"
        >
          <LogOut size={16} />
        </button>
      </div>
    </header>
  )
}

/**
 * Three honest states. "Live" only when a push can actually arrive; "Polling"
 * when the board is fresh but only as fresh as the next poll (socket down, or
 * realtime switched off server-side); "Not updating" when REST itself fails —
 * which outranks everything, because then nothing on screen is current.
 */
function LiveIndicator({ realtime, stale }: { realtime: RealtimeStatus | null; stale: boolean }) {
  const state = stale ? 'stale' : realtime === 'live' ? 'live' : 'polling'
  const label = state === 'stale' ? 'Not updating' : state === 'live' ? 'Live' : 'Polling'
  const title =
    state === 'polling'
      ? 'Realtime updates unavailable — refreshing every few seconds'
      : undefined
  return (
    <span className="kds-live" data-state={state} title={title}>
      <span className="kds-live__dot" />
      {label}
    </span>
  )
}
