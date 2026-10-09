/**
 * The maths behind the live rider map, kept out of the component so it can be
 * tested without a browser.
 *
 * The map is drawn by hand from OpenStreetMap's standard 256px Web Mercator
 * tiles rather than through a map library: this panel takes no runtime
 * dependencies (CLAUDE.md), and Google's JS map needs a billing account the
 * platform has not set up yet. Projection, fit and tile maths are ~60 lines;
 * that is the whole of what a library would have bought here.
 */

import type { Rider, WaitingFleetOrder } from '../types/app';

export const TILE = 256;
export const MIN_ZOOM = 3;
export const MAX_ZOOM = 18;
/** A single pin is shown at neighbourhood scale, not on one doorstep. */
const SINGLE_PIN_ZOOM = 15;
/** Nothing to show yet: a city-wide view. */
const EMPTY_ZOOM = 12;
/** Older than this and the pin is where the rider WAS, so it is drawn faded. */
export const STALE_MS = 5 * 60_000;

export interface LatLng {
  lat: number;
  lng: number;
}

/** Surat: where the platform's kitchens are, and so where an empty map opens. */
export const DEFAULT_CENTER: LatLng = { lat: 21.17, lng: 72.83 };

export function project(lat: number, lng: number, zoom: number): { x: number; y: number } {
  const scale = TILE * 2 ** zoom;
  const sin = Math.sin((lat * Math.PI) / 180);
  return {
    x: ((lng + 180) / 360) * scale,
    y: (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * scale,
  };
}

export function unproject(x: number, y: number, zoom: number): LatLng {
  const scale = TILE * 2 ** zoom;
  const n = Math.PI - (2 * Math.PI * y) / scale;
  return {
    lng: (x / scale) * 360 - 180,
    lat: (180 / Math.PI) * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n))),
  };
}

/** The highest zoom at which every point fits inside the box, with a margin for the pins themselves. */
export function fitView(points: LatLng[], width: number, height: number, pad = 60): { center: LatLng; zoom: number } {
  if (points.length === 0) return { center: DEFAULT_CENTER, zoom: EMPTY_ZOOM };
  const lats = points.map(p => p.lat);
  const lngs = points.map(p => p.lng);
  const box = { n: Math.max(...lats), s: Math.min(...lats), e: Math.max(...lngs), w: Math.min(...lngs) };
  const center = { lat: (box.n + box.s) / 2, lng: (box.e + box.w) / 2 };
  if (points.length === 1) return { center, zoom: SINGLE_PIN_ZOOM };
  for (let zoom = SINGLE_PIN_ZOOM; zoom > MIN_ZOOM; zoom -= 1) {
    const ne = project(box.n, box.e, zoom);
    const sw = project(box.s, box.w, zoom);
    if (ne.x - sw.x <= width - pad * 2 && sw.y - ne.y <= height - pad * 2) return { center, zoom };
  }
  return { center, zoom: MIN_ZOOM };
}

export interface TilePlacement {
  key: string;
  url: string;
  left: number;
  top: number;
}

/** Every tile that touches a `width` x `height` viewport centred on `center`. */
export function tilesFor(center: LatLng, zoom: number, width: number, height: number): TilePlacement[] {
  const c = project(center.lat, center.lng, zoom);
  const originX = c.x - width / 2;
  const originY = c.y - height / 2;
  const count = 2 ** zoom;
  const out: TilePlacement[] = [];
  for (let ty = Math.floor(originY / TILE); ty <= Math.floor((originY + height) / TILE); ty += 1) {
    if (ty < 0 || ty >= count) continue;
    for (let tx = Math.floor(originX / TILE); tx <= Math.floor((originX + width) / TILE); tx += 1) {
      const wrapped = ((tx % count) + count) % count;
      out.push({
        key: `${zoom}/${tx}/${ty}`,
        url: `https://tile.openstreetmap.org/${zoom}/${wrapped}/${ty}.png`,
        left: Math.round(tx * TILE - originX),
        top: Math.round(ty * TILE - originY),
      });
    }
  }
  return out;
}

/** Where a point lands inside the viewport, in CSS pixels. */
export function screenPoint(point: LatLng, center: LatLng, zoom: number, width: number, height: number) {
  const p = project(point.lat, point.lng, zoom);
  const c = project(center.lat, center.lng, zoom);
  return { left: p.x - c.x + width / 2, top: p.y - c.y + height / 2 };
}

export function metresBetween(a: LatLng, b: LatLng): number {
  const r = 6_371_000;
  const rad = (d: number) => (d * Math.PI) / 180;
  const dLat = rad(b.lat - a.lat);
  const dLng = rad(b.lng - a.lng);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * r * Math.asin(Math.sqrt(h));
}

export function riderPoint(rider: Rider): LatLng | null {
  return rider.last_latitude == null || rider.last_longitude == null
    ? null
    : { lat: rider.last_latitude, lng: rider.last_longitude };
}

export type RiderPinTone = 'free' | 'busy' | 'stale';

export function riderPinTone(rider: Rider, now: Date = new Date()): RiderPinTone {
  const seen = rider.last_location_at ? Date.parse(rider.last_location_at) : NaN;
  if (!Number.isFinite(seen) || now.getTime() - seen > STALE_MS) return 'stale';
  return rider.status === 'ON_TRIP' || rider.active_order_id ? 'busy' : 'free';
}

/**
 * Who could take an order at `pickup`: online, not carrying one, with a
 * known, recent position - nearest first. The server re-checks all of it on assign
 * (`offers.reassign` refuses offline and busy riders); this is the shortlist.
 */
export function nearestRiders(
  riders: Rider[],
  pickup: LatLng,
  now: Date = new Date(),
): { rider: Rider; metres: number }[] {
  return riders
    // Stale is left out, not ranked last: a position 20 minutes old says
    // where the rider was, and "900 m away" beside it would be a guess.
    .filter(r => r.status === 'ONLINE' && riderPinTone(r, now) === 'free')
    .map(r => ({ rider: r, point: riderPoint(r) }))
    .filter((r): r is { rider: Rider; point: LatLng } => r.point !== null)
    .map(({ rider, point }) => ({ rider, metres: metresBetween(point, pickup) }))
    .sort((a, b) => a.metres - b.metres);
}

export function distanceLabel(metres: number): string {
  return metres < 1000 ? `${Math.max(50, Math.round(metres / 50) * 50)} m` : `${(metres / 1000).toFixed(1)} km`;
}

/**
 * Waiting orders that share a kitchen share a pin. Two orders from one bakery
 * would otherwise be drawn exactly on top of each other, and the admin would
 * see one where there are two. Input order (oldest first) is kept.
 */
export function groupByPickup(orders: WaitingFleetOrder[]): { key: string; at: LatLng; orders: WaitingFleetOrder[] }[] {
  const groups = new Map<string, { key: string; at: LatLng; orders: WaitingFleetOrder[] }>();
  for (const order of orders) {
    if (order.pickup_lat == null || order.pickup_lng == null) continue;
    const key = `${order.pickup_lat.toFixed(5)},${order.pickup_lng.toFixed(5)}`;
    const group = groups.get(key) ?? { key, at: { lat: order.pickup_lat, lng: order.pickup_lng }, orders: [] };
    group.orders.push(order);
    groups.set(key, group);
  }
  return [...groups.values()];
}

/** How long a pin takes to glide to a rider's new position. */
export const GLIDE_MS = 1200;

/**
 * Where a gliding pin is at `t` (0..1) between its old and new position.
 * Interpolated in lat/lng, not screen pixels, so panning and zooming mid-glide
 * move the pin with the map instead of dragging it behind. Ease-out cubic:
 * quick to start, no overshoot - a pin that bounces past a rider is a lie.
 */
export function glideAt(from: LatLng, to: LatLng, t: number): LatLng {
  const k = t >= 1 ? 1 : t <= 0 ? 0 : 1 - (1 - t) ** 3;
  if (k === 1) return to;
  return { lat: from.lat + (to.lat - from.lat) * k, lng: from.lng + (to.lng - from.lng) * k };
}

/** Heading from `a` to `b` in degrees clockwise from north (0 north, 90 east). */
export function bearingDeg(a: LatLng, b: LatLng): number {
  const rad = (d: number) => (d * Math.PI) / 180;
  const y = Math.sin(rad(b.lng - a.lng)) * Math.cos(rad(b.lat));
  const x =
    Math.cos(rad(a.lat)) * Math.sin(rad(b.lat)) - Math.sin(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.cos(rad(b.lng - a.lng));
  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
}
