/**
 * Distance and arrival time, worked out on the phone from the rider's own GPS.
 *
 * Straight-line distance x 1.3 for the roads - the same road factor the
 * backend prices with (`delivery_road_factor`) - at 18 km/h, a two-wheeler's
 * typical average through city traffic. An estimate, labelled "about", and
 * refreshed with every GPS fix; no paid routing API is called.
 */

const ROAD_FACTOR = 1.3;
const CITY_KMH = 18;
/** Closer than this and "x m away" is noise from the GPS itself. */
const ARRIVED_M = 80;

export function metresBetween(
  lat1: number,
  lng1: number,
  lat2: number,
  lng2: number,
): number {
  const r = 6_371_000;
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLng = toRad(lng2 - lng1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2;
  return 2 * r * Math.asin(Math.sqrt(a));
}

export function etaMinutes(straightMetres: number): number {
  const roadKm = (straightMetres * ROAD_FACTOR) / 1000;
  return Math.max(1, Math.round((roadKm / CITY_KMH) * 60));
}

export function awayLabel(straightMetres: number): string {
  if (straightMetres < ARRIVED_M) return 'Arriving now';
  const road = straightMetres * ROAD_FACTOR;
  const distance =
    road < 1000
      ? `${Math.round(road / 50) * 50} m`
      : `${(road / 1000).toFixed(1)} km`;
  return `${distance} away · about ${etaMinutes(straightMetres)} min`;
}

/** The whole job: ride to the restaurant (straight-line, so x road factor) plus the trip (already road km). */
export function jobMinutes(
  pickupStraightMetres: number | null,
  tripRoadKm: number,
): number {
  const roadKm =
    ((pickupStraightMetres ?? 0) * ROAD_FACTOR) / 1000 + tripRoadKm;
  return Math.max(1, Math.round((roadKm / CITY_KMH) * 60));
}
