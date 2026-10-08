/**
 * The super admin's live map: every rider on shift where they last reported,
 * every fleet order still waiting for one, and a one-click way to put the
 * nearest free rider on it.
 *
 * Assigning goes through the same `reassign` route as the order page, so the
 * server's rules hold here too: an offline or busy rider is refused, a Pidge
 * booking cannot be taken, and the rider still has to accept the offer on
 * their phone. The map only shortens the walk to that button.
 */
import { Bike, LocateFixed, Minus, Plus, RefreshCw, Store, UserCheck } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';

import { ApiError, api } from '../services/api';
import {
  MAX_ZOOM,
  MIN_ZOOM,
  distanceLabel,
  fitView,
  groupByPickup,
  nearestRiders,
  riderPinTone,
  riderPoint,
  screenPoint,
  tilesFor,
  unproject,
  project,
  type LatLng,
} from '../services/liveMap';
import { lastSeenLabel } from '../services/riders';
import type { Rider, ToastMessage, WaitingFleetOrder } from '../types/app';

const POLL_MS = 10_000;

const ASSIGN_ERROR: Record<string, string> = {
  rider_offline: 'That rider has just gone offline.',
  rider_busy: 'That rider is already answering another order.',
  courier_has_it: 'A Pidge rider has this order. Cancel it there first.',
  delivery_finished: 'This order is already finished.',
};

interface Props {
  token: string;
  onToast: (title: string, description: string, tone?: ToastMessage['tone']) => void;
}

function initials(name: string): string {
  return (
    name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map(part => part[0]?.toUpperCase() ?? '')
      .join('') || '?'
  );
}

function waitedLabel(iso: string, now: Date): string {
  const minutes = Math.max(0, Math.round((now.getTime() - Date.parse(iso)) / 60_000));
  return minutes < 1 ? 'just now' : `${minutes} min`;
}

function pickupOf(order: WaitingFleetOrder): LatLng | null {
  return order.pickup_lat == null || order.pickup_lng == null ? null : { lat: order.pickup_lat, lng: order.pickup_lng };
}

export function RiderLiveMap({ token, onToast }: Props) {
  const [riders, setRiders] = useState<Rider[] | null>(null);
  const [waiting, setWaiting] = useState<WaitingFleetOrder[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [assigning, setAssigning] = useState<string | null>(null);
  const [now, setNow] = useState(() => new Date());

  const boxRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  // Null until the admin pans or zooms; until then the view is derived from
  // the pins, so it keeps fitting everyone as riders move and orders arrive.
  const [manualView, setManualView] = useState<{ center: LatLng; zoom: number } | null>(null);
  const dragRef = useRef<{ x: number; y: number; center: LatLng } | null>(null);

  const [reload, setReload] = useState(0);
  const load = useCallback(() => setReload(n => n + 1), []);

  useEffect(() => {
    let alive = true;
    const tick = () =>
      Promise.all([api.listLiveRiders(token), api.listWaitingFleetOrders(token)])
        .then(([live, open]) => {
          if (!alive) return;
          setRiders(live);
          setWaiting(open);
          setError(null);
          setNow(new Date());
        })
        .catch((e: unknown) => {
          if (!alive) return;
          setError(e instanceof ApiError ? e.message : 'Could not load the live map.');
          setNow(new Date());
        });
    void tick();
    const id = window.setInterval(() => void tick(), POLL_MS);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [token, reload]);

  // Measured the moment the box mounts, then kept current by an observer. The
  // observer alone was not enough: Chrome delivers its first reading only on a
  // rendering step, and a tab opened in the background never took one, which
  // left a full-size box drawing nothing (2026-10-08).
  const measureRef = useCallback((el: HTMLDivElement | null) => {
    boxRef.current = el;
    if (!el) return undefined;
    const read = () => {
      const rect = el.getBoundingClientRect();
      setSize(prev =>
        prev.width === Math.round(rect.width) && prev.height === Math.round(rect.height)
          ? prev
          : { width: Math.round(rect.width), height: Math.round(rect.height) },
      );
    };
    read();
    const observer = new ResizeObserver(read);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const points = useMemo(() => {
    const out: LatLng[] = [];
    for (const r of riders ?? []) {
      const p = riderPoint(r);
      if (p) out.push(p);
    }
    for (const o of waiting ?? []) {
      const p = pickupOf(o);
      if (p) out.push(p);
    }
    return out;
  }, [riders, waiting]);

  const loaded = riders !== null || error !== null;
  // Drawn even when loading failed: a blank box reads as a broken map, the
  // city with an error beside it reads as what it is.
  const view =
    manualView ?? (loaded && size.width > 0 ? fitView(points, size.width, size.height) : null);
  const setView = (next: { center: LatLng; zoom: number }) => setManualView(next);
  const refit = () => setManualView(null);

  const zoomBy = (step: number) => {
    if (view) setManualView({ ...view, zoom: Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, view.zoom + step)) });
  };

  // Wheel zoom needs a non-passive listener, or the page scrolls as well.
  // Re-attached when the view changes, so it always zooms from where it is.
  useEffect(() => {
    const el = boxRef.current;
    if (!el || !view) return undefined;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const step = event.deltaY < 0 ? 1 : -1;
      setManualView({ ...view, zoom: Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, view.zoom + step)) });
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [view]);

  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!view || (event.target as HTMLElement).closest('button')) return;
    dragRef.current = { x: event.clientX, y: event.clientY, center: view.center };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag || !view) return;
    const c = project(drag.center.lat, drag.center.lng, view.zoom);
    setView({
      zoom: view.zoom,
      center: unproject(c.x - (event.clientX - drag.x), c.y - (event.clientY - drag.y), view.zoom),
    });
  };
  const onPointerUp = () => {
    dragRef.current = null;
  };

  const selected = waiting?.find(o => o.order_id === selectedId) ?? null;
  const selectedPickup = selected ? pickupOf(selected) : null;
  const shortlist = selectedPickup && riders ? nearestRiders(riders, selectedPickup, now) : [];

  const focusOrder = (order: WaitingFleetOrder) => {
    setSelectedId(order.order_id);
    const p = pickupOf(order);
    if (p && view) {
      setView({ center: p, zoom: Math.max(view.zoom, 14) });
    }
  };

  const assign = async (order: WaitingFleetOrder, rider: Rider) => {
    setAssigning(rider.user_id);
    try {
      await api.reassignFleetDelivery(token, order.order_id, rider.user_id);
      onToast('Offer sent', `${rider.full_name} has been asked to take ${order.order_code}.`, 'success');
      load();
    } catch (e) {
      const detail = e instanceof ApiError && typeof e.detail === 'string' ? e.detail : '';
      onToast('Could not assign', ASSIGN_ERROR[detail] ?? (e instanceof Error ? e.message : 'Try again.'), 'error');
      load();
    } finally {
      setAssigning(null);
    }
  };

  const counts = useMemo(() => {
    const c = { free: 0, busy: 0, stale: 0 };
    for (const r of riders ?? []) c[riderPinTone(r, now)] += 1;
    return c;
  }, [riders, now]);

  const tiles = view && size.width > 0 ? tilesFor(view.center, view.zoom, size.width, size.height) : [];
  const place = (p: LatLng) => (view ? screenPoint(p, view.center, view.zoom, size.width, size.height) : null);

  return (
    <div className="rmap">
      <div className="rmap__stage">
        <div
          className="rmap__canvas"
          ref={measureRef}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
          role="application"
          aria-label="Live map of riders and orders waiting for one"
        >
          <div className="rmap__tiles" aria-hidden="true">
            {tiles.map(t => (
              <img key={t.key} src={t.url} alt="" draggable={false} className="rmap__tile" style={{ left: t.left, top: t.top }} />
            ))}
          </div>

          {selected && selected.drop_lat != null && selected.drop_lng != null
            ? (() => {
                const at = place({ lat: selected.drop_lat, lng: selected.drop_lng });
                return at ? (
                  <span className="rmap__pin rmap__pin--drop" style={{ left: at.left, top: at.top }} title="Customer">
                    <span className="rmap__dot" />
                  </span>
                ) : null;
              })()
            : null}

          {groupByPickup(waiting ?? []).map(group => {
            const at = place(group.at);
            if (!at) return null;
            const index = group.orders.findIndex(o => o.order_id === selectedId);
            const first = group.orders[0];
            const label = group.orders.length === 1 && first ? first.order_code : `${group.orders.length} orders`;
            return (
              <button
                key={group.key}
                type="button"
                className={index >= 0 ? 'rmap__pin rmap__pin--order rmap__pin--active' : 'rmap__pin rmap__pin--order'}
                style={{ left: at.left, top: at.top }}
                // A stacked pin cycles through its orders on each click.
                onClick={() => {
                  const next = group.orders[(index + 1) % group.orders.length];
                  if (next) focusOrder(next);
                }}
                title={group.orders.map(o => `${o.order_code} · ${o.restaurant_name}`).join(', ')}
              >
                <Store size={14} aria-hidden="true" />
                <span className="rmap__pin-label">{label}</span>
              </button>
            );
          })}

          {(riders ?? []).map(rider => {
            const p = riderPoint(rider);
            const at = p ? place(p) : null;
            if (!at) return null;
            const tone = riderPinTone(rider, now);
            return (
              <span
                key={rider.user_id}
                className={`rmap__pin rmap__pin--rider rmap__pin--${tone}`}
                style={{ left: at.left, top: at.top }}
                title={`${rider.full_name} · ${tone === 'busy' ? 'on a trip' : tone === 'free' ? 'free' : 'not updating'} · ${lastSeenLabel(rider.last_location_at, now)}`}
              >
                {initials(rider.full_name)}
              </span>
            );
          })}

          <div className="rmap__controls">
            <button type="button" className="rmap__control" onClick={() => zoomBy(1)} aria-label="Zoom in">
              <Plus size={16} />
            </button>
            <button type="button" className="rmap__control" onClick={() => zoomBy(-1)} aria-label="Zoom out">
              <Minus size={16} />
            </button>
            <button type="button" className="rmap__control" onClick={refit} aria-label="Show everyone">
              <LocateFixed size={16} />
            </button>
          </div>

          <div className="rmap__legend">
            <span><i className="rmap__swatch rmap__swatch--free" /> Free {counts.free}</span>
            <span><i className="rmap__swatch rmap__swatch--busy" /> On a trip {counts.busy}</span>
            <span><i className="rmap__swatch rmap__swatch--stale" /> Not updating {counts.stale}</span>
          </div>

          <a className="rmap__credit" href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">
            © OpenStreetMap contributors
          </a>
        </div>
      </div>

      <aside className="rmap__side">
        <div className="rmap__side-head">
          <h3>Needs a rider</h3>
          <button type="button" className="secondary-button" onClick={() => void load()}>
            <RefreshCw size={14} aria-hidden="true" />
            Refresh
          </button>
        </div>
        {error ? <p className="inline-error">{error}</p> : null}
        {waiting && waiting.length === 0 ? (
          <p className="rmap__muted">Every fleet order has a rider. New ones appear here the moment a kitchen accepts.</p>
        ) : null}
        <ul className="rmap__list">
          {(waiting ?? []).map(order => (
            <li key={order.order_id}>
              <button
                type="button"
                className={order.order_id === selectedId ? 'rmap__order rmap__order--active' : 'rmap__order'}
                onClick={() => focusOrder(order)}
              >
                <span className="rmap__order-top">
                  <strong>{order.order_code}</strong>
                  <span className="rmap__muted">waiting {waitedLabel(order.ordered_at, now)}</span>
                </span>
                <span className="rmap__muted">{order.restaurant_name}</span>
                {order.offered_to ? (
                  <span className="rmap__asking">Asking {order.offered_to}…</span>
                ) : order.provider === 'unassigned' ? (
                  <span className="rmap__asking rmap__asking--alert">Nobody took it</span>
                ) : null}
              </button>
            </li>
          ))}
        </ul>

        {selected ? (
          <div className="rmap__shortlist">
            <h4>Nearest free riders to {selected.restaurant_name}</h4>
            {selectedPickup === null ? (
              <p className="rmap__muted">This branch has no map pin, so distance cannot be worked out.</p>
            ) : shortlist.length === 0 ? (
              <p className="rmap__muted">No free rider with a recent position. Ask a rider to go online.</p>
            ) : (
              <ul className="rmap__list">
                {shortlist.slice(0, 6).map(({ rider, metres }) => (
                  <li key={rider.user_id} className="rmap__rider">
                    <span className="rmap__avatar" aria-hidden="true">
                      <Bike size={14} />
                    </span>
                    <span className="rmap__rider-name">
                      <strong>{rider.full_name}</strong>
                      <span className="rmap__muted">
                        {distanceLabel(metres)} away · seen {lastSeenLabel(rider.last_location_at, now).toLowerCase()}
                      </span>
                    </span>
                    <button
                      type="button"
                      className="primary-button"
                      disabled={assigning !== null}
                      onClick={() => void assign(selected, rider)}
                    >
                      <UserCheck size={14} aria-hidden="true" />
                      {assigning === rider.user_id ? 'Sending…' : 'Assign'}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : waiting && waiting.length > 0 ? (
          <p className="rmap__muted">Pick an order to see the nearest free riders.</p>
        ) : null}
      </aside>
    </div>
  );
}
